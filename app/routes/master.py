"""
app/routes/master.py — route master admin (multi-tenant).

Gestisce:
- Login master admin
- CRUD tenant (crea/leggi/modifica/disattiva)
- CRUD template (crea/leggi/modifica/elimina/esporta da tenant)
- Impersonation con audit log e notifica al tenant
- Statistiche tenant
- Configurazione globale master
- Reset password admin tenant

Tutti gli endpoint (tranne login) richiedono ruolo master_admin.
"""

import json
import os
import secrets
import shutil
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app, g
from flask_jwt_extended import create_access_token, jwt_required, get_jwt

from app.auth import (
    authenticate_master, cambia_password_master, get_current_master_user,
    require_master_role, hash_password
)
from app.db import get_master_db, _open_db, _get_tenant_key

bp = Blueprint('master', __name__, url_prefix='/api/master')


# =========================================================================
# Auth master
# =========================================================================

@bp.route('/auth/login', methods=['POST'])
def master_login():
    """
    Login master admin.

    Body JSON: { username, password }
    Returns: { ok, token, user } oppure { ok: false, errore }
    """
    dati = request.get_json(silent=True)
    if not dati:
        return jsonify({'ok': False, 'errore': 'Body JSON mancante.'}), 400

    username = (dati.get('username') or '').strip()
    password = (dati.get('password') or '').strip()

    if not username or not password:
        return jsonify({
            'ok': False,
            'errore': 'Username e password sono obbligatori.'
        }), 400

    result = authenticate_master(username, password)
    status = 200 if result['ok'] else 401
    return jsonify(result), status


@bp.route('/auth/password', methods=['POST'])
@require_master_role()
def cambia_password():
    """
    Cambia la password dell'account master admin autenticato.

    Fino a questa route l'account di piattaforma non aveva alcun modo di
    cambiare la propria password dall'interfaccia: poteva resettare quella
    degli admin tenant, ma non la propria.

    Body JSON: { password_attuale, password_nuova }

    Returns:
        200: { ok: true, messaggio }
        400: { ok: false, errore } — dati mancanti o password non valida
        401: { ok: false, errore } — password attuale errata
    """
    dati = request.get_json(silent=True)
    if not dati:
        return jsonify({'ok': False, 'errore': 'Body JSON mancante.'}), 400

    password_attuale = (dati.get('password_attuale') or '').strip()
    password_nuova = (dati.get('password_nuova') or '').strip()

    if not password_attuale or not password_nuova:
        return jsonify({
            'ok': False,
            'errore': 'Password attuale e nuova sono obbligatorie.'
        }), 400

    master_user = get_current_master_user()
    if not master_user:
        return jsonify({'ok': False, 'errore': 'Master admin non trovato.'}), 401

    result = cambia_password_master(
        master_user['id'], password_attuale, password_nuova)

    if not result['ok']:
        status = 401 if result['errore'] == 'Password attuale non corretta.' else 400
        return jsonify(result), status

    return jsonify({'ok': True, 'messaggio': 'Password aggiornata.'}), 200


# =========================================================================
# CRUD Tenant
# =========================================================================

@bp.route('/tenants', methods=['GET'])
@require_master_role()
def lista_tenants():
    """Restituisce tutti i tenant registrati."""
    master = get_master_db()
    rows = master.execute(
        "SELECT id, slug, nome, db_filename, is_active, visibile_login, created_at "
        "FROM tenants ORDER BY nome"
    ).fetchall()
    return jsonify({'ok': True, 'tenants': [dict(r) for r in rows]}), 200


@bp.route('/tenants', methods=['POST'])
@require_master_role()
def crea_tenant():
    """
    Crea un nuovo tenant.

    Body JSON: { slug, nome, template_id? }
    - slug: identificatore URL-safe univoco
    - nome: nome visualizzato
    - template_id: ID del template da usare (opzionale, default: schema vuoto)

    Provisioning:
    1. Genera chiave cifratura per il nuovo DB
    2. Copia template DB (o crea da schema) come tenant DB
    3. Inserisce admin seed nel nuovo DB
    4. Registra tenant nel master DB
    5. Salva chiave in tenant_keys.json
    """
    dati = request.get_json(silent=True)
    if not dati:
        return jsonify({'ok': False, 'errore': 'Body JSON mancante.'}), 400

    slug = (dati.get('slug') or '').strip().lower()
    nome = (dati.get('nome') or '').strip()
    template_id = dati.get('template_id')

    if not slug or not nome:
        return jsonify({
            'ok': False,
            'errore': 'Slug e nome sono obbligatori.'
        }), 400

    # Validazione slug: solo lettere minuscole, numeri, trattino
    import re
    if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', slug) or len(slug) < 3:
        return jsonify({
            'ok': False,
            'errore': 'Slug non valido. Usa solo lettere minuscole, numeri e trattini (min 3 caratteri).'
        }), 400

    master = get_master_db()

    # Verifica unicita' slug
    existing = master.execute(
        "SELECT id FROM tenants WHERE slug = ?", (slug,)
    ).fetchone()
    if existing:
        return jsonify({
            'ok': False,
            'errore': f"Slug '{slug}' gia' in uso."
        }), 409

    # Genera chiave e percorsi
    tenant_key = secrets.token_hex(32)
    db_filename = f"tenant_{slug}.db"
    db_path = os.path.join(current_app.config['TENANT_DB_DIR'], db_filename)

    # Provisioning DB
    try:
        if template_id:
            # Copia da template
            tmpl = master.execute(
                "SELECT db_filename FROM tenant_templates WHERE id = ?",
                (template_id,)
            ).fetchone()
            if not tmpl:
                return jsonify({
                    'ok': False,
                    'errore': 'Template non trovato.'
                }), 404

            template_path = os.path.join(
                current_app.config['TEMPLATE_DB_DIR'],
                tmpl['db_filename']
            )
            if not os.path.exists(template_path):
                return jsonify({
                    'ok': False,
                    'errore': 'File template non trovato sul disco.'
                }), 500

            # Leggi chiave template
            keys_path = current_app.config['TENANT_KEYS_PATH']
            with open(keys_path, 'r', encoding='utf-8') as f:
                keys = json.load(f)
            template_key_name = f"_template_{tmpl['db_filename'].replace('.db', '').replace('template_', '')}"
            template_key = keys.get(template_key_name)
            if not template_key:
                return jsonify({
                    'ok': False,
                    'errore': 'Chiave template non trovata.'
                }), 500

            # Copia e re-cifra con nuova chiave
            shutil.copy2(template_path, db_path)
            conn = _open_db(db_path, template_key)
            conn.execute(f"PRAGMA rekey='{tenant_key}'")
            conn.commit()
        else:
            # Crea da schema vuoto.
            # __file__ = app/routes/master.py -> serve risalire 3 livelli per
            # arrivare alla project root dove sta migrations/.
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            schema_path = os.path.join(project_root, 'migrations', 'init_db.sql')
            conn = _open_db(db_path, tenant_key)
            with open(schema_path, 'r', encoding='utf-8') as f:
                conn.executescript(f.read())
            conn.commit()

        # Inserisci admin seed con password generata.
        # DELETE+INSERT (no INSERT OR IGNORE) per garantire che la password
        # generata venga effettivamente scritta: schema/template hanno gia'
        # un seed admin con password di default, OR IGNORE preserverebbe
        # quel record rendendo la password generata inutilizzabile.
        admin_password = secrets.token_urlsafe(12)
        admin_hash = hash_password(admin_password)
        conn.execute(
            "DELETE FROM users WHERE username='admin' OR sigla='ADM'"
        )
        conn.execute(
            "INSERT INTO users (username, password_hash, role, sigla) "
            "VALUES (?, ?, 'admin', 'ADM')",
            ('admin', admin_hash)
        )

        # Inserisci tenant_slug nella config
        conn.execute(
            "INSERT OR IGNORE INTO config (chiave, valore, descrizione) "
            "VALUES ('tenant_slug', ?, 'Slug del tenant proprietario')",
            (slug,)
        )
        conn.commit()
        conn.close()

    except Exception as e:
        # Cleanup in caso di errore.
        # Su Windows os.remove fallisce se conn e' ancora aperta -> chiudere prima.
        try:
            conn.close()
        except Exception:
            pass
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                # File ancora bloccato: lasciamo orphan, rimuovibile manualmente
                current_app.logger.warning(
                    "Provisioning fallito ma DB orphan non rimosso: %s", db_path
                )
        return jsonify({
            'ok': False,
            'errore': f'Errore provisioning DB: {e}'
        }), 500

    # Salva chiave nel file keys
    try:
        keys_path = current_app.config['TENANT_KEYS_PATH']
        with open(keys_path, 'r', encoding='utf-8') as f:
            keys = json.load(f)
        keys[slug] = tenant_key
        with open(keys_path, 'w', encoding='utf-8') as f:
            json.dump(keys, f, indent=2)
    except Exception as e:
        # DB creato ma chiave non salvata: cleanup
        if os.path.exists(db_path):
            os.remove(db_path)
        return jsonify({
            'ok': False,
            'errore': f'Errore salvataggio chiave: {e}'
        }), 500

    # Registra nel master DB
    master.execute(
        "INSERT INTO tenants (slug, nome, db_filename) VALUES (?, ?, ?)",
        (slug, nome, db_filename)
    )
    master.commit()

    tenant_row = master.execute(
        "SELECT id, slug, nome, db_filename, is_active, visibile_login, created_at "
        "FROM tenants WHERE slug = ?",
        (slug,)
    ).fetchone()

    return jsonify({
        'ok': True,
        'tenant': dict(tenant_row),
        'admin_password': admin_password,
        'messaggio': f"Tenant '{nome}' creato. Password admin: {admin_password} — comunicarla e farla cambiare."
    }), 201


@bp.route('/tenants/<int:tenant_id>', methods=['PUT'])
@require_master_role()
def modifica_tenant(tenant_id):
    """
    Modifica nome, stato o visibilita' di un tenant.

    Body JSON: { nome?, is_active?, visibile_login? }
    """
    dati = request.get_json(silent=True)
    if not dati:
        return jsonify({'ok': False, 'errore': 'Body JSON mancante.'}), 400

    master = get_master_db()
    tenant = master.execute(
        "SELECT * FROM tenants WHERE id = ?", (tenant_id,)
    ).fetchone()

    if not tenant:
        return jsonify({'ok': False, 'errore': 'Tenant non trovato.'}), 404

    # Aggiorna campi forniti
    fields = []
    values = []
    for campo in ('nome', 'is_active', 'visibile_login'):
        if campo in dati:
            fields.append(f"{campo} = ?")
            values.append(dati[campo])

    if not fields:
        return jsonify({'ok': False, 'errore': 'Nessun campo da aggiornare.'}), 400

    values.append(tenant_id)
    master.execute(
        f"UPDATE tenants SET {', '.join(fields)} WHERE id = ?",
        values
    )
    master.commit()

    updated = master.execute(
        "SELECT id, slug, nome, db_filename, is_active, visibile_login, created_at "
        "FROM tenants WHERE id = ?",
        (tenant_id,)
    ).fetchone()

    return jsonify({'ok': True, 'tenant': dict(updated)}), 200


@bp.route('/tenants/<int:tenant_id>', methods=['DELETE'])
@require_master_role()
def disattiva_tenant(tenant_id):
    """Disattiva un tenant (soft delete: is_active = 0)."""
    master = get_master_db()
    tenant = master.execute(
        "SELECT id, slug FROM tenants WHERE id = ?", (tenant_id,)
    ).fetchone()

    if not tenant:
        return jsonify({'ok': False, 'errore': 'Tenant non trovato.'}), 404

    master.execute(
        "UPDATE tenants SET is_active = 0 WHERE id = ?", (tenant_id,)
    )
    master.commit()

    return jsonify({
        'ok': True,
        'messaggio': f"Tenant '{tenant['slug']}' disattivato."
    }), 200


@bp.route('/tenants/<int:tenant_id>/stats', methods=['GET'])
@require_master_role()
def stats_tenant(tenant_id):
    """
    Restituisce statistiche di un tenant: utenti, calendari, ultimo accesso.
    """
    master = get_master_db()
    tenant = master.execute(
        "SELECT slug, nome FROM tenants WHERE id = ?", (tenant_id,)
    ).fetchone()

    if not tenant:
        return jsonify({'ok': False, 'errore': 'Tenant non trovato.'}), 404

    try:
        g.tenant_slug = tenant['slug']
        from app.db import get_db
        db = get_db()

        utenti = db.execute(
            "SELECT COUNT(*) as tot, "
            "SUM(CASE WHEN role='admin' THEN 1 ELSE 0 END) as admins, "
            "SUM(CASE WHEN role='manager' THEN 1 ELSE 0 END) as managers, "
            "SUM(CASE WHEN role='basic' THEN 1 ELSE 0 END) as basics "
            "FROM users WHERE is_active = 1"
        ).fetchone()

        calendari = db.execute(
            "SELECT COUNT(*) as tot FROM calendari"
        ).fetchone()

        presets = db.execute(
            "SELECT COUNT(*) as tot FROM struttura_presets"
        ).fetchone()

        stats = {
            'utenti_totali': utenti['tot'],
            'admins': utenti['admins'],
            'managers': utenti['managers'],
            'basics': utenti['basics'],
            'calendari': calendari['tot'],
            'presets': presets['tot'],
        }

        # Chiudi connessione tenant per non interferire
        db.close()
        g.pop('db', None)

    except Exception as e:
        return jsonify({
            'ok': False,
            'errore': f'Errore lettura stats: {e}'
        }), 500

    return jsonify({
        'ok': True,
        'tenant': {'slug': tenant['slug'], 'nome': tenant['nome']},
        'stats': stats
    }), 200


@bp.route('/tenants/<int:tenant_id>/reset-admin', methods=['POST'])
@require_master_role()
def reset_admin_password(tenant_id):
    """
    Reset password dell'admin di un tenant.

    Genera una nuova password casuale e la restituisce al master admin.
    """
    master = get_master_db()
    tenant = master.execute(
        "SELECT slug, nome FROM tenants WHERE id = ?", (tenant_id,)
    ).fetchone()

    if not tenant:
        return jsonify({'ok': False, 'errore': 'Tenant non trovato.'}), 404

    new_password = secrets.token_urlsafe(12)
    new_hash = hash_password(new_password)

    try:
        g.tenant_slug = tenant['slug']
        from app.db import get_db
        db = get_db()

        admin = db.execute(
            "SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
        ).fetchone()

        if not admin:
            return jsonify({
                'ok': False,
                'errore': 'Nessun admin trovato in questo tenant.'
            }), 404

        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (new_hash, admin['id'])
        )
        db.commit()
        db.close()
        g.pop('db', None)

    except Exception as e:
        return jsonify({
            'ok': False,
            'errore': f'Errore reset password: {e}'
        }), 500

    return jsonify({
        'ok': True,
        'messaggio': f"Password admin di '{tenant['nome']}' resettata.",
        'nuova_password': new_password
    }), 200


# =========================================================================
# Impersonation
# =========================================================================

@bp.route('/tenants/<int:tenant_id>/impersonate', methods=['POST'])
@require_master_role()
def impersonate_tenant(tenant_id):
    """
    Genera un JWT per operare come admin di un tenant.

    Il JWT include il claim 'impersonated_by' con l'ID del master admin.
    L'azione viene loggata in impersonation_log e viene scritta una
    notifica nel DB del tenant visibile al suo admin.

    Body JSON opzionale: { motivo: "descrizione intervento" }
    """
    dati = request.get_json(silent=True) or {}
    motivo = (dati.get('motivo') or '').strip() or 'Accesso tecnico'

    master = get_master_db()
    tenant = master.execute(
        "SELECT id, slug, nome FROM tenants WHERE id = ? AND is_active = 1",
        (tenant_id,)
    ).fetchone()

    if not tenant:
        return jsonify({'ok': False, 'errore': 'Tenant non trovato o disattivato.'}), 404

    master_user = get_current_master_user()
    if not master_user:
        return jsonify({'ok': False, 'errore': 'Master admin non trovato.'}), 401

    # Trova l'admin del tenant
    try:
        g.tenant_slug = tenant['slug']
        from app.db import get_db
        db = get_db()

        admin = db.execute(
            "SELECT id, username, role, sigla FROM users "
            "WHERE role = 'admin' AND is_active = 1 ORDER BY id LIMIT 1"
        ).fetchone()

        if not admin:
            db.close()
            g.pop('db', None)
            return jsonify({
                'ok': False,
                'errore': 'Nessun admin attivo in questo tenant.'
            }), 404

        # Scrivi notifica nel tenant DB
        now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        notifica = json.dumps({
            'tipo': 'impersonation',
            'master_user': master_user['username'],
            'motivo': motivo,
            'data': now,
        })
        db.execute(
            "INSERT OR REPLACE INTO config (chiave, valore, descrizione) "
            "VALUES ('_notifica_impersonation', ?, "
            "'Notifica ultimo accesso master admin')",
            (notifica,)
        )
        db.commit()
        db.close()
        g.pop('db', None)

    except Exception as e:
        return jsonify({
            'ok': False,
            'errore': f'Errore accesso tenant: {e}'
        }), 500

    # Log nel master DB
    master.execute(
        "INSERT INTO impersonation_log (master_user_id, tenant_id, azione, dettaglio) "
        "VALUES (?, ?, 'enter', ?)",
        (master_user['id'], tenant_id, motivo)
    )
    master.commit()

    # Genera JWT come admin del tenant
    token = create_access_token(
        identity=str(admin['id']),
        additional_claims={
            'tenant': tenant['slug'],
            'role': 'admin',
            'impersonated_by': master_user['id'],
        }
    )

    return jsonify({
        'ok': True,
        'token': token,
        'tenant': tenant['slug'],
        'user': {
            'id': admin['id'],
            'username': admin['username'],
            'role': admin['role'],
            'sigla': admin['sigla'],
        },
        'messaggio': f"Accesso come admin di '{tenant['nome']}'. Notifica inviata."
    }), 200


@bp.route('/impersonation-log', methods=['GET'])
@require_master_role()
def lista_impersonation_log():
    """Restituisce l'audit log di tutte le impersonation."""
    master = get_master_db()
    rows = master.execute(
        "SELECT il.id, il.azione, il.dettaglio, il.created_at, "
        "mu.username as master_username, t.slug as tenant_slug, t.nome as tenant_nome "
        "FROM impersonation_log il "
        "JOIN master_users mu ON il.master_user_id = mu.id "
        "JOIN tenants t ON il.tenant_id = t.id "
        "ORDER BY il.created_at DESC "
        "LIMIT 100"
    ).fetchall()

    return jsonify({
        'ok': True,
        'log': [dict(r) for r in rows]
    }), 200


# =========================================================================
# CRUD Template
# =========================================================================

@bp.route('/templates', methods=['GET'])
@require_master_role()
def lista_templates():
    """Restituisce tutti i template disponibili."""
    master = get_master_db()
    rows = master.execute(
        "SELECT id, nome, descrizione, db_filename, created_at "
        "FROM tenant_templates ORDER BY nome"
    ).fetchall()
    return jsonify({'ok': True, 'templates': [dict(r) for r in rows]}), 200


@bp.route('/templates', methods=['POST'])
@require_master_role()
def crea_template():
    """
    Crea un nuovo template vuoto (da schema init_db.sql).

    Body JSON: { nome, descrizione? }
    """
    dati = request.get_json(silent=True)
    if not dati:
        return jsonify({'ok': False, 'errore': 'Body JSON mancante.'}), 400

    nome = (dati.get('nome') or '').strip()
    descrizione = (dati.get('descrizione') or '').strip()

    if not nome:
        return jsonify({'ok': False, 'errore': 'Nome obbligatorio.'}), 400

    master = get_master_db()

    # Verifica unicita' nome
    existing = master.execute(
        "SELECT id FROM tenant_templates WHERE nome = ?", (nome,)
    ).fetchone()
    if existing:
        return jsonify({
            'ok': False,
            'errore': f"Template '{nome}' gia' esistente."
        }), 409

    # Crea file DB template
    import re
    slug = re.sub(r'[^a-z0-9]+', '_', nome.lower()).strip('_')
    db_filename = f"template_{slug}.db"
    db_path = os.path.join(current_app.config['TEMPLATE_DB_DIR'], db_filename)

    template_key = secrets.token_hex(32)

    try:
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'migrations', 'init_db.sql'
        )
        conn = _open_db(db_path, template_key)
        with open(schema_path, 'r', encoding='utf-8') as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()
    except Exception as e:
        if os.path.exists(db_path):
            os.remove(db_path)
        return jsonify({
            'ok': False,
            'errore': f'Errore creazione template DB: {e}'
        }), 500

    # Salva chiave
    try:
        keys_path = current_app.config['TENANT_KEYS_PATH']
        with open(keys_path, 'r', encoding='utf-8') as f:
            keys = json.load(f)
        keys[f"_template_{slug}"] = template_key
        with open(keys_path, 'w', encoding='utf-8') as f:
            json.dump(keys, f, indent=2)
    except Exception as e:
        if os.path.exists(db_path):
            os.remove(db_path)
        return jsonify({
            'ok': False,
            'errore': f'Errore salvataggio chiave template: {e}'
        }), 500

    # Registra nel master DB
    master.execute(
        "INSERT INTO tenant_templates (nome, descrizione, db_filename) VALUES (?, ?, ?)",
        (nome, descrizione, db_filename)
    )
    master.commit()

    tmpl = master.execute(
        "SELECT id, nome, descrizione, db_filename, created_at "
        "FROM tenant_templates WHERE nome = ?",
        (nome,)
    ).fetchone()

    return jsonify({'ok': True, 'template': dict(tmpl)}), 201


@bp.route('/templates/<int:template_id>', methods=['PUT'])
@require_master_role()
def modifica_template(template_id):
    """
    Modifica nome o descrizione di un template.

    Body JSON: { nome?, descrizione? }
    """
    dati = request.get_json(silent=True)
    if not dati:
        return jsonify({'ok': False, 'errore': 'Body JSON mancante.'}), 400

    master = get_master_db()
    tmpl = master.execute(
        "SELECT id FROM tenant_templates WHERE id = ?", (template_id,)
    ).fetchone()
    if not tmpl:
        return jsonify({'ok': False, 'errore': 'Template non trovato.'}), 404

    fields = []
    values = []
    for campo in ('nome', 'descrizione'):
        if campo in dati:
            fields.append(f"{campo} = ?")
            values.append(dati[campo])

    if not fields:
        return jsonify({'ok': False, 'errore': 'Nessun campo da aggiornare.'}), 400

    values.append(template_id)
    master.execute(
        f"UPDATE tenant_templates SET {', '.join(fields)} WHERE id = ?",
        values
    )
    master.commit()

    updated = master.execute(
        "SELECT id, nome, descrizione, db_filename, created_at "
        "FROM tenant_templates WHERE id = ?",
        (template_id,)
    ).fetchone()

    return jsonify({'ok': True, 'template': dict(updated)}), 200


@bp.route('/templates/<int:template_id>', methods=['DELETE'])
@require_master_role()
def elimina_template(template_id):
    """Elimina un template (DB file + registro)."""
    master = get_master_db()
    tmpl = master.execute(
        "SELECT id, nome, db_filename FROM tenant_templates WHERE id = ?",
        (template_id,)
    ).fetchone()
    if not tmpl:
        return jsonify({'ok': False, 'errore': 'Template non trovato.'}), 404

    # Rimuovi file DB
    db_path = os.path.join(
        current_app.config['TEMPLATE_DB_DIR'], tmpl['db_filename']
    )
    if os.path.exists(db_path):
        os.remove(db_path)

    # Rimuovi chiave dal file keys
    try:
        keys_path = current_app.config['TENANT_KEYS_PATH']
        with open(keys_path, 'r', encoding='utf-8') as f:
            keys = json.load(f)
        import re
        slug = re.sub(r'[^a-z0-9]+', '_', tmpl['nome'].lower()).strip('_')
        keys.pop(f"_template_{slug}", None)
        with open(keys_path, 'w', encoding='utf-8') as f:
            json.dump(keys, f, indent=2)
    except Exception:
        pass

    # Rimuovi dal master DB
    master.execute(
        "DELETE FROM tenant_templates WHERE id = ?", (template_id,)
    )
    master.commit()

    return jsonify({
        'ok': True,
        'messaggio': f"Template '{tmpl['nome']}' eliminato."
    }), 200


@bp.route('/templates/from-tenant/<int:tenant_id>', methods=['POST'])
@require_master_role()
def crea_template_da_tenant(tenant_id):
    """
    Crea un template copiando la configurazione da un tenant esistente.

    Copia: flag_turno, tipi_richiesta, regole_conflitto, vincoli,
    tipi_qualitativo, config, preset_ottimizzazione.
    Non copia: utenti, calendari, desiderata, assegnazioni, history.

    Body JSON: { nome, descrizione? }
    """
    dati = request.get_json(silent=True)
    if not dati:
        return jsonify({'ok': False, 'errore': 'Body JSON mancante.'}), 400

    nome = (dati.get('nome') or '').strip()
    descrizione = (dati.get('descrizione') or '').strip()

    if not nome:
        return jsonify({'ok': False, 'errore': 'Nome obbligatorio.'}), 400

    master = get_master_db()
    tenant = master.execute(
        "SELECT slug, nome as tenant_nome FROM tenants WHERE id = ?",
        (tenant_id,)
    ).fetchone()
    if not tenant:
        return jsonify({'ok': False, 'errore': 'Tenant non trovato.'}), 404

    # Verifica unicita' nome template
    existing = master.execute(
        "SELECT id FROM tenant_templates WHERE nome = ?", (nome,)
    ).fetchone()
    if existing:
        return jsonify({
            'ok': False,
            'errore': f"Template '{nome}' gia' esistente."
        }), 409

    # Crea template DB: copia intero tenant DB e poi elimina dati non-config
    import re
    slug = re.sub(r'[^a-z0-9]+', '_', nome.lower()).strip('_')
    db_filename = f"template_{slug}.db"
    db_path = os.path.join(current_app.config['TEMPLATE_DB_DIR'], db_filename)
    template_key = secrets.token_hex(32)

    try:
        # Copia il DB tenant
        tenant_db_path = os.path.join(
            current_app.config['TENANT_DB_DIR'],
            f"tenant_{tenant['slug']}.db"
        )
        tenant_key = _get_tenant_key(tenant['slug'])
        shutil.copy2(tenant_db_path, db_path)

        # Re-cifra con chiave template
        conn = _open_db(db_path, tenant_key)
        conn.execute(f"PRAGMA rekey='{template_key}'")
        conn.commit()

        # Elimina dati non-config (utenti, calendari, assegnazioni, history, ecc.)
        tabelle_da_svuotare = [
            'users', 'calendari', 'versioni_calendario', 'giorni_calendario',
            'deadline_utenti', 'calendario_turni', 'desiderata',
            'working_desiderata', 'assegnazioni_turni', 'history',
            'history_ptr', 'wd_history', 'wd_history_ptr',
            'solver_esecuzioni', 'style_history',
            'struttura_presets', 'sovragruppi', 'gruppi', 'preset_turni',
            'preset_turni_qualitativo', 'posti_fissi', 'posti_fissi_utenti',
            'preset_esclusioni_turno_per_utente',
            'manager_accesso_utenti', 'manager_accesso_turni',
            'vincoli_utente', 'vincoli_solver_utente', 'esclusioni_utente',
        ]
        for tabella in tabelle_da_svuotare:
            try:
                conn.execute(f"DELETE FROM {tabella}")
            except Exception:
                pass
        conn.commit()
        conn.close()

    except Exception as e:
        if os.path.exists(db_path):
            os.remove(db_path)
        return jsonify({
            'ok': False,
            'errore': f'Errore creazione template da tenant: {e}'
        }), 500

    # Salva chiave
    try:
        keys_path = current_app.config['TENANT_KEYS_PATH']
        with open(keys_path, 'r', encoding='utf-8') as f:
            keys = json.load(f)
        keys[f"_template_{slug}"] = template_key
        with open(keys_path, 'w', encoding='utf-8') as f:
            json.dump(keys, f, indent=2)
    except Exception as e:
        if os.path.exists(db_path):
            os.remove(db_path)
        return jsonify({
            'ok': False,
            'errore': f'Errore salvataggio chiave: {e}'
        }), 500

    # Registra nel master DB
    if not descrizione:
        descrizione = f"Esportato da tenant '{tenant['tenant_nome']}'"
    master.execute(
        "INSERT INTO tenant_templates (nome, descrizione, db_filename) VALUES (?, ?, ?)",
        (nome, descrizione, db_filename)
    )
    master.commit()

    tmpl = master.execute(
        "SELECT id, nome, descrizione, db_filename, created_at "
        "FROM tenant_templates WHERE nome = ?",
        (nome,)
    ).fetchone()

    return jsonify({'ok': True, 'template': dict(tmpl)}), 201


# =========================================================================
# Configurazione globale master
# =========================================================================

# =============================================================================
# PROPOSTE DI CONFIGURAZIONE AI TENANT
# =============================================================================

def _estrai_parti_proponibili(db):
    """
    Legge da un tenant le sole parti che si possono proporre altrove.

    Il servizio `proposte` dichiara quali sono e con che nome si riconoscono;
    qui si va a prenderle, con le colonne che servono a ricostruirle.

    Args:
        db: connessione al database del tenant.

    Returns:
        dict: le quattro parti, ciascuna come lista di righe.
    """
    query = {
        'flag_turno':
            "SELECT id, nome, parent_id, descrizione, orario_inizio, orario_fine, "
            "pausa_minuti, ore_primo_giorno, ore_ultimo_giorno, "
            "mostra_in_struttura, tipo FROM flag_turno",
        'tipi_qualitativo':
            "SELECT id, nome, descrizione, carico_lavoro FROM tipi_qualitativo",
        'tipi_richiesta':
            "SELECT id, sigla, descrizione, tipo, counting_flag, flag_id, "
            "ore_default, ordine FROM tipi_richiesta",
        'regole_conflitto':
            "SELECT id, nome, tipo_regola, flag_a_id, flag_b_id, offset_giorni, "
            "categoria, stile, blocca_inserimento, peso_numerico "
            "FROM regole_conflitto",
    }

    return {
        chiave: [dict(r) for r in db.execute(sql).fetchall()]
        for chiave, sql in query.items()
    }


def _apri_tenant(slug):
    """
    Connessione al database di un tenant.

    Args:
        slug (str): identificativo del tenant.

    Returns:
        connessione SQLCipher.
    """
    percorso = os.path.join(
        current_app.config['TENANT_DB_DIR'], f'tenant_{slug}.db'
    )
    return _open_db(percorso, _get_tenant_key(slug))


@bp.route('/tenants/<int:tenant_id>/configurazione', methods=['GET'])
@require_master_role()
def leggi_configurazione_tenant(tenant_id):
    """
    Il vocabolario di un tenant, nella forma in cui si puo' proporre altrove.

    Serve al master per due cose: vedere com'e' fatto un tenant, e prendere
    da uno ben configurato il materiale da proporre agli altri.
    """
    tenant = get_master_db().execute(
        "SELECT slug, nome FROM tenants WHERE id=?", (tenant_id,)
    ).fetchone()
    if not tenant:
        return jsonify({'ok': False, 'errore': 'Tenant non trovato.'}), 404

    try:
        db = _apri_tenant(tenant['slug'])
        parti = _estrai_parti_proponibili(db)
    except Exception as e:
        current_app.logger.warning(
            'Lettura configurazione del tenant %s fallita: %s', tenant['slug'], e
        )
        return jsonify({'ok': False, 'errore': 'Database del tenant non leggibile.'}), 500

    return jsonify({
        'ok': True, 'tenant': tenant['nome'], 'configurazione': parti,
    }), 200


@bp.route('/tenants/<int:tenant_id>/proposta', methods=['POST'])
@require_master_role()
def proponi_configurazione(tenant_id):
    """
    Deposita una proposta nel database del tenant.

    Non applica niente: sara' l'amministratore del tenant a confrontarla con
    quello che ha e a decidere. Una proposta in attesa per volta.

    Body JSON: { nome, configurazione, note? }
    """
    tenant = get_master_db().execute(
        "SELECT slug FROM tenants WHERE id=?", (tenant_id,)
    ).fetchone()
    if not tenant:
        return jsonify({'ok': False, 'errore': 'Tenant non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    nome = (dati.get('nome') or '').strip()
    configurazione = dati.get('configurazione')
    if not nome or not configurazione:
        return jsonify({
            'ok': False, 'errore': 'Servono un nome e una configurazione.'
        }), 400

    try:
        db = _apri_tenant(tenant['slug'])
        # Una in attesa per volta: la precedente si intende superata.
        db.execute(
            "UPDATE proposte_configurazione SET stato='ritirata', "
            "decisa_at=datetime('now') WHERE stato='in_attesa'"
        )
        db.execute(
            "INSERT INTO proposte_configurazione (nome, proposta, proposta_da, note) "
            "VALUES (?,?,?,?)",
            (nome, json.dumps(configurazione), get_current_master_user()['username'],
             (dati.get('note') or '').strip() or None)
        )
        db.commit()
    except Exception as e:
        current_app.logger.warning(
            'Proposta al tenant %s fallita: %s', tenant['slug'], e
        )
        return jsonify({'ok': False, 'errore': 'Invio della proposta non riuscito.'}), 500

    return jsonify({'ok': True, 'messaggio': 'Proposta inviata.'}), 201


@bp.route('/config', methods=['GET'])
@require_master_role()
def get_master_config():
    """Restituisce tutte le configurazioni master."""
    master = get_master_db()
    rows = master.execute(
        "SELECT chiave, valore, descrizione FROM master_config ORDER BY chiave"
    ).fetchall()
    return jsonify({
        'ok': True,
        'config': {r['chiave']: r['valore'] for r in rows}
    }), 200


@bp.route('/config', methods=['PUT'])
@require_master_role()
def update_master_config():
    """
    Aggiorna configurazioni master.

    Body JSON: { chiave: valore, ... }
    """
    dati = request.get_json(silent=True)
    if not dati:
        return jsonify({'ok': False, 'errore': 'Body JSON mancante.'}), 400

    master = get_master_db()
    for chiave, valore in dati.items():
        master.execute(
            "UPDATE master_config SET valore = ? WHERE chiave = ?",
            (str(valore), chiave)
        )
    master.commit()

    return jsonify({'ok': True, 'messaggio': 'Configurazione aggiornata.'}), 200
