"""
app/routes/basic.py — route per i lavoratori Basic.

Endpoint:
    GET    /api/basic/calendari                              → calendari in stato APERTO
    GET    /api/basic/calendari/<id>/desiderata              → miei desiderata per il calendario
    PUT    /api/basic/calendari/<id>/desiderata              → salva/aggiorna una desiderata
    DELETE /api/basic/calendari/<id>/desiderata/<giorno>     → cancella desiderata di un giorno
    GET    /api/basic/calendari/<id>/desiderata-globale      → griglia completa + privacy applicata
    PUT    /api/basic/privacy                                → aggiorna offusca (0/1/2) dell'utente
    GET    /api/basic/preferenze                             → mie preferenze generali turni
    PUT    /api/basic/preferenze                             → aggiorna preferenza per un turno
"""

from datetime import datetime

from flask import Blueprint, request, jsonify

from app.auth import require_role, get_current_user
from app.db import query_one, query_all, execute_write
from app.services.calendario_state import ottieni_calendario_aperto
from app.services.websocket import (
    broadcast_desiderata_changed,
    broadcast_privacy_changed,
)

bp = Blueprint('basic', __name__, url_prefix='/api/basic')


def _modalita_ordinamento():
    cfg = query_one(
        "SELECT valore FROM config WHERE chiave='modalita_ordinamento_desiderata'"
    )
    return cfg['valore'] if cfg else 'alfabetico_intragruppo'


# =============================================================================
# CALENDARI APERTI
# =============================================================================

@bp.route('/calendari', methods=['GET'])
@require_role('admin', 'manager', 'basic')
def lista_calendari():
    """
    Restituisce i calendari con stato APERTO, visibili ai lavoratori per
    inserire i propri desiderata. Include la deadline personalizzata per
    l'utente corrente, se presente.

    Returns:
        200: { ok: true, calendari: [ { id, mese, anno, stato,
               deadline_globale, deadline_personale, desiderata_congelati } ] }
    """
    me = get_current_user()
    calendari = query_all(
        "SELECT id, mese, anno, stato, ore_giornaliere_default, "
        "deadline_globale, desiderata_congelati "
        "FROM calendari WHERE stato = 'APERTO' ORDER BY anno DESC, mese DESC"
    )
    for cal in calendari:
        dl = query_one(
            "SELECT deadline FROM deadline_utenti WHERE calendario_id=? AND user_id=?",
            (cal['id'], me['id'])
        )
        cal['deadline_personale'] = dl['deadline'] if dl else None

    return jsonify({'ok': True, 'calendari': calendari}), 200


# =============================================================================
# DESIDERATA
# =============================================================================

@bp.route('/calendari/<int:cal_id>/desiderata', methods=['GET'])
@require_role('admin', 'manager', 'basic')
def miei_desiderata(cal_id):
    """
    Restituisce i desiderata del lavoratore corrente per un calendario,
    insieme ai giorni del mese con i loro attributi.

    Args:
        cal_id (int): ID del calendario.

    Returns:
        200: { ok: true, calendario: {...}, desiderata: [...], giorni: [...] }
        404: { ok: false, errore: str }
    """
    cal = query_one(
        "SELECT id, mese, anno, stato, ore_giornaliere_default, "
        "deadline_globale, desiderata_congelati "
        "FROM calendari WHERE id=?", (cal_id,)
    )
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    me = get_current_user()
    desiderata = query_all(
        """
        SELECT d.id, d.giorno, d.tipo_richiesta_id,
               tr.sigla AS req_sigla, tr.descrizione AS req_descrizione,
               tr.tipo AS req_tipo, d.note, d.updated_at
        FROM desiderata d
        LEFT JOIN tipi_richiesta tr ON d.tipo_richiesta_id = tr.id
        WHERE d.calendario_id=? AND d.user_id=?
        ORDER BY d.giorno
        """,
        (cal_id, me['id'])
    )

    giorni = query_all(
        "SELECT giorno, is_lavorativo, ore_lavorative, tipo "
        "FROM giorni_calendario WHERE calendario_id=? ORDER BY giorno",
        (cal_id,)
    )

    return jsonify({
        'ok': True,
        'calendario': cal,
        'desiderata': desiderata,
        'giorni': giorni,
    }), 200


@bp.route('/calendari/<int:cal_id>/desiderata', methods=['PUT'])
@require_role('admin', 'manager', 'basic')
def salva_desiderata(cal_id):
    """
    Salva o aggiorna una desiderata per un giorno del calendario.

    Controlli applicati:
    - Il calendario deve essere in stato APERTO.
    - I desiderata non devono essere già congelati.
    - La deadline (personale se presente, altrimenti globale) non deve essere scaduta.

    Body JSON:
        giorno (int): giorno del mese (1-31).
        tipo_richiesta_id (int): ID del tipo di richiesta.
        note (str|null): note opzionali.

    Returns:
        200: { ok: true, messaggio: str }
        400: { ok: false, errore: str }
        403: { ok: false, errore: 'Deadline scaduta' }
        404: { ok: false, errore: str }
    """
    cal = ottieni_calendario_aperto(
        cal_id, "id, stato, deadline_globale, desiderata_congelati")
    if cal['desiderata_congelati']:
        return jsonify({'ok': False, 'errore': 'I desiderata sono stati congelati.'}), 400

    me = get_current_user()
    if me.get('escluso_turni'):
        return jsonify({
            'ok': False,
            'errore': 'Utente escluso dai turni: non è possibile inserire desiderata.'
        }), 403

    # Verifica deadline (personale ha precedenza sulla globale)
    dl = query_one(
        "SELECT deadline FROM deadline_utenti WHERE calendario_id=? AND user_id=?",
        (cal_id, me['id'])
    )
    deadline_str = dl['deadline'] if dl else cal['deadline_globale']
    if deadline_str:
        try:
            if datetime.now() > datetime.fromisoformat(deadline_str):
                return jsonify({'ok': False, 'errore': 'Deadline scaduta.'}), 403
        except (ValueError, TypeError):
            pass  # deadline malformata: ignoriamo

    dati    = request.get_json(silent=True) or {}
    giorno  = dati.get('giorno')
    tipo_id = dati.get('tipo_richiesta_id')

    if not giorno or not tipo_id:
        return jsonify({'ok': False,
                        'errore': 'giorno e tipo_richiesta_id sono obbligatori.'}), 400

    # Note rimosse dal foglio desiderata (decisione di prodotto): salvato sempre NULL.
    execute_write(
        """
        INSERT INTO desiderata
            (calendario_id, user_id, giorno, tipo_richiesta_id, note,
             updated_at, updated_by)
        VALUES (?,?,?,?,NULL,datetime('now'),?)
        ON CONFLICT(calendario_id, user_id, giorno) DO UPDATE SET
            tipo_richiesta_id = excluded.tipo_richiesta_id,
            note              = NULL,
            updated_at        = excluded.updated_at,
            updated_by        = excluded.updated_by
        """,
        (cal_id, me['id'], giorno, tipo_id, me['id'])
    )

    # Broadcast real-time agli altri client sulla stessa room calendario.
    tr = query_one(
        "SELECT sigla, tipo FROM tipi_richiesta WHERE id=?", (tipo_id,)
    )
    entry = {
        'tipo_richiesta_id': tipo_id,
        'req_sigla': tr['sigla'] if tr else '',
        'req_tipo':  tr['tipo']  if tr else '',
    }
    broadcast_desiderata_changed(
        cal_id, me['id'], giorno, entry, 'desiderata', me['id'],
        author_offusca=me.get('offusca', 0) or 0,
    )

    return jsonify({'ok': True, 'messaggio': f'Desiderata giorno {giorno} salvata.'}), 200


@bp.route('/calendari/<int:cal_id>/desiderata/<int:giorno>', methods=['DELETE'])
@require_role('admin', 'manager', 'basic')
def cancella_desiderata(cal_id, giorno):
    """
    Cancella la desiderata di un giorno per il lavoratore corrente.

    Non è possibile cancellare dopo il congelamento dei desiderata.

    Args:
        cal_id (int): ID del calendario.
        giorno (int): giorno del mese.

    Returns:
        200: { ok: true, messaggio: str }
        400: { ok: false, errore: str }
        404: { ok: false, errore: str }
    """
    cal = query_one(
        "SELECT id, desiderata_congelati FROM calendari WHERE id=?", (cal_id,)
    )
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404
    if cal['desiderata_congelati']:
        return jsonify({'ok': False, 'errore': 'I desiderata sono stati congelati.'}), 400

    me = get_current_user()
    if me.get('escluso_turni'):
        return jsonify({
            'ok': False,
            'errore': 'Utente escluso dai turni: non è possibile inserire desiderata.'
        }), 403

    des = query_one(
        "SELECT id FROM desiderata WHERE calendario_id=? AND user_id=? AND giorno=?",
        (cal_id, me['id'], giorno)
    )
    if not des:
        return jsonify({'ok': False, 'errore': 'Desiderata non trovata.'}), 404

    execute_write(
        "DELETE FROM desiderata WHERE calendario_id=? AND user_id=? AND giorno=?",
        (cal_id, me['id'], giorno)
    )
    broadcast_desiderata_changed(
        cal_id, me['id'], giorno, None, 'desiderata', me['id'],
        author_offusca=me.get('offusca', 0) or 0,
    )
    return jsonify({'ok': True, 'messaggio': f'Desiderata giorno {giorno} cancellata.'}), 200


@bp.route('/calendari/<int:cal_id>/desiderata-globale', methods=['GET'])
@require_role('admin', 'manager', 'basic')
def desiderata_globale(cal_id):
    """
    Restituisce la griglia completa desiderata per un calendario:
    calendario, giorni, utenti ordinati secondo modalità globale, desiderata
    di tutti con privacy applicata.

    Privacy:
    - Manager/admin vedono sempre tutto senza mascheramento.
    - Per basic (diverso dall'autore), applica il flag `offusca` dell'autore:
        * offusca=2 → nessuna desiderata visibile
        * offusca=1 → sigla sostituita con 'X' per richieste di tipo 'assenza'
    - Il proprio riga è sempre visibile per intero.

    Returns:
        200: { ok: true, calendario, giorni, utenti[], sovragruppi[],
               desiderata[], modalita }
        404: calendario non trovato
    """
    cal = query_one(
        "SELECT id, mese, anno, stato, ore_giornaliere_default, "
        "deadline_globale, desiderata_congelati, appearance_snapshot "
        "FROM calendari WHERE id=?", (cal_id,)
    )
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    # Appearance snapshot del calendario (fallback al preset default se null).
    # Riusa gli stessi CSS vars della griglia turni nelle viste desiderata.
    import json as _json
    raw = cal.get('appearance_snapshot')
    if not raw:
        preset_app = query_one(
            "SELECT appearance FROM struttura_presets WHERE is_default=1 LIMIT 1"
        )
        raw = preset_app['appearance'] if preset_app else None
    try:
        cal['appearance'] = _json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        cal['appearance'] = {}

    me = get_current_user()
    mascheramento_attivo = me['role'] == 'basic'

    giorni = query_all(
        "SELECT giorno, is_lavorativo, ore_lavorative, tipo "
        "FROM giorni_calendario WHERE calendario_id=? ORDER BY giorno",
        (cal_id,)
    )

    # deadline personale
    dl = query_one(
        "SELECT deadline FROM deadline_utenti WHERE calendario_id=? AND user_id=?",
        (cal_id, me['id'])
    )
    cal['deadline_personale'] = dl['deadline'] if dl else None

    modalita = _modalita_ordinamento()

    # Struttura corrente: preset di default (fallback primo preset)
    preset = query_one(
        "SELECT id FROM struttura_presets WHERE is_default=1 LIMIT 1"
    ) or query_one("SELECT id FROM struttura_presets ORDER BY id LIMIT 1")

    # Sovragruppi dallo snapshot del calendario (calendario_turni) per avere
    # lo stesso style (colore di sfondo) mostrato nella griglia turni.
    # Join con la tabella preset sovragruppi per recuperare ordine_desiderata.
    sg_rows = query_all(
        """
        SELECT DISTINCT ct.sg_id AS id, ct.sg_sigla AS sigla, ct.sg_nome AS nome,
               ct.sg_ordine AS ordine, ct.sg_style AS style_json,
               sg.ordine_desiderata AS ordine_desiderata
        FROM calendario_turni ct
        LEFT JOIN sovragruppi sg ON ct.sg_id = sg.id
        WHERE ct.calendario_id = ? AND ct.sg_id IS NOT NULL
        ORDER BY COALESCE(sg.ordine_desiderata, ct.sg_ordine), ct.sg_id
        """,
        (cal_id,)
    )
    sovragruppi = []
    for s in sg_rows:
        try:
            style = _json.loads(s['style_json']) if s['style_json'] else {}
        except (ValueError, TypeError):
            style = {}
        sovragruppi.append({
            'id': s['id'],
            'sigla': s['sigla'],
            'nome': s['nome'],
            'ordine': s['ordine'],
            'ordine_desiderata': s['ordine_desiderata'],
            'style': style,
        })

    # Utenti attivi con sovragruppo — ordinamento secondo modalita
    utenti = query_all(
        "SELECT u.id, u.sigla, u.role, u.sovragruppo_id, u.offusca, "
        "u.ordine_desiderata, sg.sigla AS sg_sigla, sg.nome AS sg_nome, "
        "COALESCE(sg.ordine_desiderata, sg.ordine, 0) AS sg_ordine_effettivo "
        "FROM users u "
        "LEFT JOIN sovragruppi sg ON u.sovragruppo_id = sg.id "
        "WHERE u.is_active=1 AND u.role IN ('basic','manager','admin')",
        ()
    )

    def sort_key(u):
        sigla = (u['sigla'] or '').upper()
        sg_ord = u['sg_ordine_effettivo'] if u['sovragruppo_id'] else 999999
        if modalita == 'alfabetico_globale':
            return (sigla,)
        if modalita == 'alfabetico_intragruppo':
            return (sg_ord, sigla)
        # manuale: per sovragruppo, poi ordine_desiderata, poi sigla come tie-breaker
        return (sg_ord, u['ordine_desiderata'] or 0, sigla)

    utenti.sort(key=sort_key)

    # Desiderata di tutti (con tipo per applicare mascheramento assenze)
    des_rows = query_all(
        """
        SELECT d.user_id, d.giorno, d.tipo_richiesta_id,
               tr.sigla AS req_sigla, tr.tipo AS req_tipo
        FROM desiderata d
        LEFT JOIN tipi_richiesta tr ON d.tipo_richiesta_id = tr.id
        WHERE d.calendario_id = ?
        """,
        (cal_id,)
    )

    # Indice utenti → offusca (per mascheramento)
    offusca_by_uid = {u['id']: (u['offusca'] or 0) for u in utenti}

    desiderata = []
    for d in des_rows:
        uid_autore = d['user_id']
        offusca = offusca_by_uid.get(uid_autore, 0)
        mio = (uid_autore == me['id'])
        # Mascheramento solo se chi guarda è basic e non è l'autore
        if mascheramento_attivo and not mio:
            if offusca == 2:
                continue  # nasconde interamente
            if offusca == 1 and d['req_tipo'] == 'assenza':
                d = dict(d)
                d['req_sigla'] = 'X'
        desiderata.append(d)

    return jsonify({
        'ok': True,
        'calendario': cal,
        'giorni': giorni,
        'utenti': utenti,
        'sovragruppi': sovragruppi,
        'desiderata': desiderata,
        'modalita': modalita,
        'me': {'id': me['id'], 'role': me['role'], 'offusca': me.get('offusca', 0)},
    }), 200


# =============================================================================
# PRIVACY (offusca)
# =============================================================================

@bp.route('/privacy', methods=['PUT'])
@require_role('admin', 'manager', 'basic')
def set_privacy():
    """Aggiorna il flag `offusca` dell'utente corrente. Body: { offusca: 0|1|2 }."""
    dati = request.get_json(silent=True) or {}
    try:
        offusca = int(dati.get('offusca'))
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'errore': 'Valore offusca non valido.'}), 400
    if offusca not in (0, 1, 2):
        return jsonify({'ok': False, 'errore': 'Valore offusca non valido (0/1/2).'}), 400

    me = get_current_user()
    execute_write("UPDATE users SET offusca=? WHERE id=?", (offusca, me['id']))

    # Broadcast: ogni calendario aperto riceve l'aggiornamento privacy cosi'
    # che viste desiderata di altri client applichino il nuovo offuscamento
    # senza richiedere refresh manuale.
    cal_aperti = query_all(
        "SELECT id FROM calendari WHERE stato='APERTO'"
    )
    for c in cal_aperti:
        broadcast_privacy_changed(c['id'], me['id'], offusca, me['id'])

    return jsonify({'ok': True, 'offusca': offusca}), 200


# =============================================================================
# PREFERENZE GENERALI
# =============================================================================

@bp.route('/preferenze', methods=['GET'])
@require_role('admin', 'manager', 'basic')
def mie_preferenze():
    """
    Restituisce le preferenze generali del lavoratore corrente per ogni turno attivo.

    I turni senza preferenza esplicita vengono restituiti con valore default 5.

    Returns:
        200: { ok: true, preferenze: [ { turno_id, sigla, descrizione, valore } ] }
    """
    me = get_current_user()
    preferenze = query_all(
        """
        SELECT t.id AS turno_id, t.sigla, t.descrizione,
               COALESCE(pg.valore, 5) AS valore
        FROM turni t
        LEFT JOIN preferenze_generali pg ON pg.turno_id = t.id AND pg.user_id = ?
        WHERE t.is_active = 1
        ORDER BY t.ordine
        """,
        (me['id'],)
    )
    return jsonify({'ok': True, 'preferenze': preferenze}), 200


@bp.route('/preferenze', methods=['PUT'])
@require_role('admin', 'manager', 'basic')
def aggiorna_preferenza():
    """
    Aggiorna la preferenza del lavoratore corrente per un singolo turno.

    Body JSON:
        turno_id (int): ID del turno.
        valore (int): valore preferenza (0-10).

    Returns:
        200: { ok: true, messaggio: str }
        400: { ok: false, errore: str }
    """
    dati     = request.get_json(silent=True) or {}
    turno_id = dati.get('turno_id')
    valore   = dati.get('valore')

    if turno_id is None or valore is None:
        return jsonify({'ok': False,
                        'errore': 'turno_id e valore sono obbligatori.'}), 400

    valore = int(valore)
    if not (0 <= valore <= 10):
        return jsonify({'ok': False,
                        'errore': 'Valore deve essere compreso tra 0 e 10.'}), 400

    me = get_current_user()
    execute_write(
        """
        INSERT INTO preferenze_generali (user_id, turno_id, valore) VALUES (?,?,?)
        ON CONFLICT(user_id, turno_id) DO UPDATE SET valore = excluded.valore
        """,
        (me['id'], turno_id, valore)
    )
    return jsonify({'ok': True, 'messaggio': 'Preferenza aggiornata.'}), 200
