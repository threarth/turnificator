"""
app/routes/auth.py — route di autenticazione JWT (multi-tenant).

Endpoint:
    POST /api/auth/login    → login tenant con username/password/tenant
    POST /api/auth/logout   → logout (lato client: elimina il token)
    GET  /api/auth/me       → info utente corrente (richiede token valido)
    GET  /api/auth/tenants  → lista tenant visibili per il dropdown login (pubblico)
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.auth import authenticate_user, get_current_user
from app.db import get_master_db

bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@bp.route('/tenants', methods=['GET'])
def lista_tenant_login():
    """
    Restituisce la lista dei tenant visibili per il dropdown di login.

    Endpoint pubblico (no auth). Il comportamento dipende dalla config
    master 'dropdown_login_attivo':
    - Se '1': restituisce { dropdown: true, tenants: [{slug, nome}, ...] }
    - Se '0': restituisce { dropdown: false } (il client mostra campo slug)

    Returns:
        200: { dropdown: bool, tenants?: [{slug, nome}] }
    """
    master_db = get_master_db()
    config_row = master_db.execute(
        "SELECT valore FROM master_config WHERE chiave = 'dropdown_login_attivo'"
    ).fetchone()

    if not config_row or config_row['valore'] != '1':
        return jsonify({'dropdown': False}), 200

    rows = master_db.execute(
        "SELECT slug, nome FROM tenants "
        "WHERE is_active = 1 AND visibile_login = 1 "
        "ORDER BY nome"
    ).fetchall()

    return jsonify({
        'dropdown': True,
        'tenants': [{'slug': r['slug'], 'nome': r['nome']} for r in rows]
    }), 200


@bp.route('/login', methods=['POST'])
def login():
    """
    Autentica un utente tenant e restituisce un token JWT.

    Body JSON richiesto:
        tenant (str): slug del tenant.
        username (str): nome utente.
        password (str): password in chiaro.

    Returns:
        200: { ok: true, token, user: { id, username, role, sigla }, tenant }
        400: { ok: false, errore: 'Dati mancanti' }
        401: { ok: false, errore: 'Credenziali non valide' }
    """
    dati = request.get_json(silent=True)
    if not dati:
        return jsonify({'ok': False, 'errore': 'Body JSON mancante.'}), 400

    tenant_slug = (dati.get('tenant') or '').strip()
    username = (dati.get('username') or '').strip()
    password = (dati.get('password') or '').strip()

    if not tenant_slug:
        return jsonify({
            'ok': False,
            'errore': 'Organizzazione (tenant) obbligatoria.'
        }), 400

    if not username or not password:
        return jsonify({
            'ok': False,
            'errore': 'Username e password sono obbligatori.'
        }), 400

    # Verifica che il tenant esista e sia attivo
    master_db = get_master_db()
    tenant_row = master_db.execute(
        "SELECT id FROM tenants WHERE slug = ? AND is_active = 1",
        (tenant_slug,)
    ).fetchone()

    if not tenant_row:
        return jsonify({
            'ok': False,
            'errore': 'Organizzazione non trovata o disattivata.'
        }), 401

    try:
        login_result = authenticate_user(username, password, tenant_slug)
    except Exception:
        return jsonify({
            'ok': False,
            'errore': 'Errore di connessione al database dell\'organizzazione.'
        }), 500

    if not login_result['ok']:
        return jsonify(login_result), 401

    return jsonify(login_result), 200


@bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """
    Logout dell'utente corrente.

    Il token JWT è stateless: il logout lato server non invalida il token.
    Il client deve eliminare il token dal proprio storage.
    In un sistema con blacklist token si aggiungerebbe qui la revoca.

    Returns:
        200: { ok: true, messaggio: 'Logout effettuato.' }
    """
    return jsonify({'ok': True, 'messaggio': 'Logout effettuato. Elimina il token dal client.'}), 200


@bp.route('/me', methods=['GET'])
@jwt_required()
def me():
    """
    Restituisce i dati dell'utente autenticato dalla richiesta corrente.

    Per utenti tenant: restituisce user + tenant slug.
    Per master admin: restituisce user con role='master_admin' e tenant=null.
    Se in impersonation: include il flag impersonated=true.

    Returns:
        200: { ok, user: { id, username, role, sigla }, tenant?, impersonated? }
        401: { errore: 'Utente non trovato' }
    """
    from flask_jwt_extended import get_jwt

    claims = get_jwt()
    role = claims.get('role')
    tenant_slug = claims.get('tenant')
    impersonated_by = claims.get('impersonated_by')

    # Master admin senza impersonation
    if role == 'master_admin' and not tenant_slug:
        from app.auth import get_current_master_user
        master_user = get_current_master_user()
        if not master_user:
            return jsonify({'errore': 'Master admin non trovato.'}), 401
        return jsonify({
            'ok': True,
            'user': {
                'id':       master_user['id'],
                'username': master_user['username'],
                'role':     'master_admin',
            },
            'tenant': None,
        }), 200

    # Utente tenant (o master in impersonation)
    utente = get_current_user()
    if not utente:
        return jsonify({'errore': 'Utente non trovato.'}), 401

    user_data = {
        'id':            utente['id'],
        'username':      utente['username'],
        'role':          utente['role'],
        'sigla':         utente['sigla'],
        'escluso_turni': bool(utente.get('escluso_turni', 0)),
    }
    # Flag gestione calendari per manager/admin
    if utente['role'] in ('admin', 'manager'):
        user_data['puo_gestire_calendari'] = bool(
            utente.get('puo_gestire_calendari', 0)
        )

    result = {
        'ok': True,
        'user': user_data,
        'tenant': tenant_slug,
    }

    if impersonated_by:
        result['impersonated'] = True

    return jsonify(result), 200
