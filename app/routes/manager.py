"""
app/routes/manager.py — route per il Manager.

Endpoint:
    GET    /api/manager/calendari                              → calendari accessibili
    GET    /api/manager/calendari/<id>/struttura               → struttura completa + assegnazioni
    GET    /api/manager/calendari/<id>/assegnazioni            → tutte le assegnazioni
    POST   /api/manager/calendari/<id>/assegnazioni            → inserisce/aggiorna assegnazione
    POST   /api/manager/calendari/<id>/salva-batch             → salva più assegnazioni in batch (incolla)
    DELETE /api/manager/calendari/<id>/assegnazioni/<ass_id>   → svuota cella (turno scoperto)
    GET    /api/manager/calendari/<id>/disponibili             → lavoratori disponibili (query params)
    GET    /api/manager/calendari/<id>/desiderata              → desiderata originali di tutti gli utenti
    GET    /api/manager/calendari/<id>/working-desiderata      → tutti i working_desiderata
    PUT    /api/manager/calendari/<id>/working-desiderata      → aggiorna un working_desiderata
    POST   /api/manager/calendari/<id>/working-desiderata/salva-batch → salva più WD in batch (incolla)
    GET    /api/manager/calendari/<id>/ore                     → calcolo ore mensili
    GET    /api/manager/calendari/<id>/esclusioni-manuali     → esclusioni manuali
    PUT    /api/manager/calendari/<id>/esclusioni-manuali     → salva esclusioni manuali
    GET    /api/manager/calendari/<id>/celle-bloccate         → celle bloccate
    PUT    /api/manager/calendari/<id>/celle-bloccate         → salva celle bloccate
    POST   /api/manager/calendari/<id>/ottimizza             → lancia optimizer
    GET    /api/manager/calendari/<id>/history                 → info stato history
    POST   /api/manager/calendari/<id>/undo                    → annulla ultima operazione
    POST   /api/manager/calendari/<id>/redo                    → ripete ultima operazione annullata
"""

import json

from flask import Blueprint, request, jsonify

from app.auth import require_role, get_current_user
from app.db import get_db, query_one, query_all, execute_write
from app.services.calendario_state import ottieni_calendario_aperto
from app.services.validatori import valida_assegnazione, get_disponibili
from app.services.ore import calcola_ore_mensili
from app.services.history import aggiungi_step, undo, redo, get_info_history
from app.services.wd_history import wd_aggiungi_step, wd_undo, wd_redo, wd_get_info_history
from app.services.solver import esegui_solver
from app.services.accesso_manager import manager_puo_turno, manager_puo_utente
from app.services.fasce_orarie import (
    carica_mappa_flag, discende_da_nome, e_notturna
)
from app.services.config_snapshot import (
    carica_config_snapshot,
    snap_manager_puo_turno, snap_manager_puo_utente, snap_tipi_richiesta,
)
from app.services.websocket import (
    broadcast_assegnazione, broadcast_svuota,
    broadcast_undo_redo, broadcast_solver,
    broadcast_desiderata_changed,
)

bp = Blueprint('manager', __name__, url_prefix='/api/manager')

# Termine interno per la struttura, usato finche' il tenant non sceglie
# la propria parola nella procedura guidata. Il plurale e' dichiarato,
# non derivato: dal singolare non e' ricavabile.
ETICHETTA_STRUTTURA_DEFAULT = {'singolare': 'Sovragruppo', 'plurale': 'Sovragruppi'}


# =============================================================================
# CALENDARI
# =============================================================================

@bp.route('/calendari', methods=['GET'])
@require_role('admin', 'manager')
def lista_calendari():
    """
    Restituisce i calendari principali (esclude effettivi).

    Returns:
        200: { ok: true, calendari: [ { id, mese, anno, stato, versione, tipo, ... } ] }
    """
    from app.services.auto_close import controlla_auto_chiusura_effettivi
    controlla_auto_chiusura_effettivi()

    calendari = query_all(
        "SELECT id, mese, anno, stato, ore_giornaliere_default, "
        "deadline_globale, desiderata_congelati, versione, tipo, chiuso_il, created_at "
        "FROM calendari WHERE tipo='programmato' "
        "ORDER BY anno DESC, mese DESC"
    )
    return jsonify({'ok': True, 'calendari': calendari}), 200


@bp.route('/calendari/<int:cal_id>/effettivo', methods=['GET'])
@require_role('admin', 'manager')
def get_effettivo(cal_id):
    """Ritorna info dell'EFFETTIVO associato a un calendario principale."""
    from app.services.effettivo import effettivo_ha_modifiche

    eff = query_one(
        "SELECT id, stato, chiuso_il FROM calendari "
        "WHERE parent_id=? AND tipo='effettivo'",
        (cal_id,))
    if not eff:
        return jsonify({'ok': True, 'effettivo': None}), 200

    # Info del calendario parent (principale) per label frontend
    parent = query_one(
        "SELECT versione, chiuso_il FROM calendari WHERE id=?", (cal_id,))

    return jsonify({
        'ok': True,
        'effettivo': {
            'id': eff['id'],
            'stato': eff['stato'],
            'chiuso_il': eff['chiuso_il'],
            'ha_modifiche': effettivo_ha_modifiche(eff['id']),
            'parent_versione': parent['versione'] if parent else None,
            'parent_chiuso_il': parent['chiuso_il'] if parent else None,
        }
    }), 200


# =============================================================================
# STRUTTURA COMPLETA CALENDARIO
# =============================================================================

def _arricchisci_con_tipo_richiesta(righe, cal_id):
    """
    Aggiunge sigla e tipo della richiesta, come erano quando il calendario
    e' stato creato.

    Rinominare o riclassificare un tipo richiesta non deve cambiare il
    significato di un desiderata gia' espresso: 'assenza' o 'lavorativo'
    decide anche il colore della cella.

    Args:
        righe (list): righe con `tipo_richiesta_id`.
        cal_id (int): calendario da cui prendere lo snapshot.

    Returns:
        list: le stesse righe, con `req_sigla` e `req_tipo` valorizzati.
    """
    tipi = snap_tipi_richiesta(carica_config_snapshot(cal_id))
    if not tipi:
        return righe

    for r in righe:
        tipo = tipi.get(r.get('tipo_richiesta_id'))
        if tipo:
            r['req_sigla'] = tipo.get('sigla')
            r['req_tipo'] = tipo.get('tipo')

    return righe


def _etichetta_struttura():
    """
    La parola con cui il tenant chiama le sue strutture.

    "Sovragruppo" e' il termine interno e resta il ripiego finche' nessuno ha
    scelto il proprio: reparto, ambulatorio, presidio.

    Returns:
        dict: {singolare, plurale}.
    """
    righe = query_all(
        "SELECT chiave, valore FROM config "
        "WHERE chiave IN ('etichetta_struttura', 'etichetta_strutture')"
    )
    valori = {r['chiave']: r['valore'] for r in righe}
    singolare = valori.get('etichetta_struttura')
    if not singolare:
        return dict(ETICHETTA_STRUTTURA_DEFAULT)

    return {
        'singolare': singolare,
        'plurale': valori.get('etichetta_strutture') or singolare,
    }


@bp.route('/calendari/<int:cal_id>/struttura', methods=['GET'])
@require_role('admin', 'manager')
def struttura_calendario(cal_id):
    """
    Restituisce la struttura completa del calendario: metadati, giorni,
    gerarchia sovragruppi/gruppi/turni, assegnazioni e working_desiderata.

    Args:
        cal_id (int): ID del calendario.

    Returns:
        200: { ok: true, calendario: {...}, giorni: [...], sovragruppi: [...],
               assegnazioni: [...], working_desiderata: [...] }
        404: { ok: false, errore: str }
    """
    from app.services.auto_close import controlla_auto_chiusura_effettivi
    controlla_auto_chiusura_effettivi()

    cal = query_one(
        "SELECT id, mese, anno, stato, ore_giornaliere_default, "
        "deadline_globale, desiderata_congelati, style, regole_snapshot, preset_id, "
        "versione, tipo, parent_id, chiuso_il, appearance_snapshot "
        "FROM calendari WHERE id=?", (cal_id,)
    )
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    giorni = query_all(
        "SELECT giorno, is_lavorativo, ore_lavorative, tipo "
        "FROM giorni_calendario WHERE calendario_id=? ORDER BY giorno",
        (cal_id,)
    )

    # Costruisce la gerarchia dallo snapshot in calendario_turni (autosufficiente)
    ct_rows = query_all(
        """
        SELECT id AS turno_id, local_id, sigla AS t_sigla, nome AS t_nome, ordine AS t_ordine,
               gruppo_id AS g_id, gruppo_sigla AS g_sigla, gruppo_nome AS g_nome,
               gruppo_ordine AS g_ordine, style AS g_style, turno_style,
               sg_id, sg_sigla, sg_nome, sg_ordine, sg_style,
               flag_nome, flag_id, tipi_qualitativi,
               peso_turno, ore_turno, ore_primo_giorno, ore_ultimo_giorno,
               apri_festivi, apri_superfestivi, aperture_straordinarie,
               is_disabled, is_hidden
        FROM calendario_turni
        WHERE calendario_id = ?
        ORDER BY sg_ordine, g_ordine, ordine
        """,
        (cal_id,)
    )

    sg_map = {}
    for row in ct_rows:
        sg_key = row['sg_sigla']
        if sg_key not in sg_map:
            sg_map[sg_key] = {
                'id': row.get('sg_id'),
                'sigla': row['sg_sigla'], 'nome': row['sg_nome'],
                'ordine': row['sg_ordine'],
                'style': json.loads(row.get('sg_style', '{}')),
                '_gruppi': {}
            }
        g_map = sg_map[sg_key]['_gruppi']
        g_key = (row['g_sigla'], row['g_ordine'])
        if g_key not in g_map:
            g_map[g_key] = {
                'id': row['g_id'], 'sigla': row['g_sigla'], 'nome': row['g_nome'],
                'ordine': row['g_ordine'], 'style': json.loads(row.get('g_style', '{}')),
                'turni': []
            }
        g_map[g_key]['turni'].append({
            'id': row['turno_id'],
            'local_id': row['local_id'],
            'sigla': row['t_sigla'],
            'descrizione': row['t_nome'],
            'style': json.loads(row.get('turno_style', '{}')),
            'flag_nome': row.get('flag_nome'),
            'flag_id': row.get('flag_id'),
            # Le tipologie del turno servono ai conteggi del context menu.
            'tipi_qualitativi': json.loads(row.get('tipi_qualitativi') or '[]'),
            'peso_turno': row.get('peso_turno', 1),
            'ore_turno': row.get('ore_turno'),
            'ore_primo_giorno': row.get('ore_primo_giorno'),
            'ore_ultimo_giorno': row.get('ore_ultimo_giorno'),
            'apri_festivi': row.get('apri_festivi', 0),
            'apri_superfestivi': row.get('apri_superfestivi', 0),
            'aperture_straordinarie': json.loads(row.get('aperture_straordinarie', '[]') or '[]'),
            'is_disabled': row.get('is_disabled', 0),
            'is_hidden': row.get('is_hidden', 0),
        })

    sovragruppi = []
    for sg in sorted(sg_map.values(), key=lambda x: x['ordine']):
        gruppi = sorted(sg.pop('_gruppi').values(), key=lambda x: x['ordine'])
        sovragruppi.append({**sg, 'gruppi': gruppi})

    # Calcola accessibilità turni/utenti per il manager corrente
    me = get_current_user()
    utenti_acc_list = None
    is_admin = me['role'] == 'admin'
    config_snap = carica_config_snapshot(cal_id)

    # Helper per check accesso (usa snapshot se disponibile, altrimenti live)
    def _puo_turno(mid, ptid):
        if config_snap:
            return snap_manager_puo_turno(config_snap, mid, ptid)
        return manager_puo_turno(mid, ptid)

    def _puo_utente(mid, uid):
        if config_snap:
            return snap_manager_puo_utente(config_snap, mid, uid)
        return manager_puo_utente(mid, uid)

    if not is_admin:
        all_u = query_all(
            "SELECT id FROM users WHERE is_active=1 AND escluso_turni=0"
        )
        utenti_acc_ids = [
            u['id'] for u in all_u
            if _puo_utente(me['id'], u['id'])
        ]
        if len(utenti_acc_ids) < len(all_u):
            utenti_acc_list = utenti_acc_ids

    # Annota ogni turno con flag accessibile (check da snapshot o live)
    turni_totali = 0
    turni_accessibili_count = 0
    for sg in sovragruppi:
        for g in sg['gruppi']:
            for t in g['turni']:
                turni_totali += 1
                if is_admin:
                    t['accessibile'] = True
                    turni_accessibili_count += 1
                else:
                    acc = _puo_turno(me['id'], int(t['local_id']))
                    t['accessibile'] = acc
                    if acc:
                        turni_accessibili_count += 1

    cal_dict = dict(cal)
    cal_dict['style'] = json.loads(cal_dict.get('style', '{}'))
    regole_snap = json.loads(cal_dict.pop('regole_snapshot', '[]') or '[]')
    # Appearance snapshot: colonna dedicata, con fallback ai defaults
    from app.services.config_snapshot import APPEARANCE_DEFAULT
    try:
        app_raw = cal_dict.pop('appearance_snapshot', None)
        app_data = json.loads(app_raw) if app_raw else {}
    except (json.JSONDecodeError, TypeError):
        app_data = {}
    cal_dict['appearance'] = {**APPEARANCE_DEFAULT, **app_data}
    # Fallback: se il calendario non ha snapshot, usa le regole live
    if not regole_snap:
        from app.services.validatori import _get_regole_attive_db
        regole_snap = [dict(r) for r in _get_regole_attive_db()]

    _ricalcola_tutti_conflitti(cal_id)

    assegnazioni = query_all(
        "SELECT id, turno_id, giorno, user_id, originale_user_id, forza_inserimento, "
        "forza_note, conflitto, conflitti, updated_at "
        "FROM assegnazioni_turni WHERE calendario_id=? ORDER BY giorno, turno_id",
        (cal_id,)
    )

    working_des = query_all(
        "SELECT id, user_id, giorno, tipo_richiesta_id, note "
        "FROM working_desiderata WHERE calendario_id=? ORDER BY user_id, giorno",
        (cal_id,)
    )

    # ── Notti ultimo giorno mese precedente ──────────────────────
    # Trova i turni notturni del calendario corrente. Il riconoscimento passa
    # dalla gerarchia e non dal nome: una fascia notturna puo' chiamarsi come
    # vuole l'utente, purche' discenda dal concetto 'notturno'.
    mappa_flag = carica_mappa_flag(config_snap)
    notti_local_ids = [
        t['local_id']
        for sg in sovragruppi
        for g_item in sg['gruppi']
        for t in g_item['turni']
        if e_notturna(t.get('flag_nome'), mappa_flag)
    ]

    notti_mese_prec = None  # None = nessun calendario precedente
    if notti_local_ids:
        prev_mese = cal['mese'] - 1 if cal['mese'] > 1 else 12
        prev_anno = cal['anno'] if cal['mese'] > 1 else cal['anno'] - 1
        prev_cal = query_one(
            "SELECT id, mese, anno FROM calendari WHERE mese=? AND anno=?",
            (prev_mese, prev_anno)
        )
        if prev_cal:
            import calendar as _cal_mod
            ultimo_giorno = _cal_mod.monthrange(prev_anno, prev_mese)[1]
            # Mappa local_id → turno_id del mese precedente
            prev_turni = query_all(
                "SELECT id, local_id FROM calendario_turni "
                "WHERE calendario_id=? AND local_id IN ({})".format(
                    ','.join(['?'] * len(notti_local_ids))
                ),
                [prev_cal['id']] + notti_local_ids
            )
            prev_map = {r['local_id']: r['id'] for r in prev_turni}
            # Assegnazioni dell'ultimo giorno per quei turni
            if prev_map:
                prev_turno_ids = list(prev_map.values())
                prev_ass = query_all(
                    "SELECT turno_id, user_id FROM assegnazioni_turni "
                    "WHERE calendario_id=? AND giorno=? AND turno_id IN ({})".format(
                        ','.join(['?'] * len(prev_turno_ids))
                    ),
                    [prev_cal['id'], ultimo_giorno] + prev_turno_ids
                )
                # Inverti mappa: prev_turno_id → local_id
                inv_map = {v: k for k, v in prev_map.items()}
                notti_mese_prec = {
                    inv_map[a['turno_id']]: a['user_id']
                    for a in prev_ass if a['turno_id'] in inv_map
                }
            else:
                notti_mese_prec = {}
        # Se prev_cal non esiste, notti_mese_prec resta None

    return jsonify({
        'ok': True,
        'calendario': cal_dict,
        'giorni': giorni,
        'sovragruppi': sovragruppi,
        'assegnazioni': assegnazioni,
        'working_desiderata': working_des,
        'regole_conflitto': regole_snap,
        'config_snapshot': config_snap or {},
        'flag_turno': config_snap.get('flag_turno', []) if config_snap else [
            dict(r) for r in query_all(
                "SELECT id, nome, parent_id FROM flag_turno"
            )
        ],
        'utenti_accessibili': utenti_acc_list,
        # Come l'utente chiama le sue strutture: la config e' riservata
        # all'admin, quindi al manager la parola arriva di qui.
        'etichetta_struttura': _etichetta_struttura(),
        'accesso_info': {
            'turni_accessibili': turni_accessibili_count,
            'turni_totali': turni_totali,
        },
        'notti_mese_prec': notti_mese_prec,
    }), 200


# =============================================================================
# ASSEGNAZIONI TURNI
# =============================================================================

def _ricalcola_tutti_conflitti(cal_id, escludi_ass_id=None):
    """
    Ricalcola i conflitti per tutte le assegnazioni assegnate (user_id non NULL)
    del calendario. Restituisce la lista aggiornata nel formato vicini atteso
    dal frontend. escludi_ass_id esclude il record appena salvato (già aggiornato).
    """
    righe = query_all(
        "SELECT id, turno_id, giorno, user_id FROM assegnazioni_turni "
        "WHERE calendario_id=? AND user_id IS NOT NULL",
        (cal_id,)
    )
    aggiornati = []
    for r in righe:
        if escludi_ass_id is not None and r['id'] == escludi_ass_id:
            continue
        try:
            res = valida_assegnazione(cal_id, r['turno_id'], r['user_id'], r['giorno'])
            execute_write(
                "UPDATE assegnazioni_turni SET conflitti=? WHERE id=?",
                (json.dumps(res['conflitti']), r['id'])
            )
            aggiornati.append({
                'turno_id': r['turno_id'],
                'giorno':   r['giorno'],
                'conflitti': res['conflitti'],
            })
        except Exception:
            pass
    return aggiornati


def _ricalcola_conflitti_vicini(cal_id, user_id, giorno, escludi_turno_id=None):
    """
    Ricalcola i conflitti per le assegnazioni dello stesso utente nei giorni
    giorno-1, giorno, giorno+1, escludendo il turno appena salvato/svuotato
    (i cui conflitti sono già corretti dalla chiamata principale).
    """
    if not user_id:
        return []
    aggiornati = []
    for g in (giorno - 1, giorno, giorno + 1):
        if g < 1:
            continue
        righe = query_all(
            "SELECT id, turno_id FROM assegnazioni_turni "
            "WHERE calendario_id=? AND user_id=? AND giorno=?",
            (cal_id, user_id, g)
        )
        for r in righe:
            if escludi_turno_id is not None and r['turno_id'] == escludi_turno_id:
                continue
            try:
                res = valida_assegnazione(cal_id, r['turno_id'], user_id, g)
                cj  = json.dumps(res['conflitti'])
                execute_write(
                    "UPDATE assegnazioni_turni SET conflitti=? WHERE id=?",
                    (cj, r['id'])
                )
                aggiornati.append({
                    'turno_id': r['turno_id'],
                    'giorno':   g,
                    'conflitti': res['conflitti'],
                })
            except Exception:
                pass
    return aggiornati


@bp.route('/calendari/<int:cal_id>/assegnazioni', methods=['GET'])
@require_role('admin', 'manager')
def lista_assegnazioni(cal_id):
    """
    Restituisce tutte le assegnazioni del calendario.

    Returns:
        200: { ok: true, assegnazioni: [...] }
    """
    assegnazioni = query_all(
        "SELECT id, turno_id, giorno, user_id, originale_user_id, forza_inserimento, "
        "forza_note, conflitto, conflitti, updated_at "
        "FROM assegnazioni_turni WHERE calendario_id=? ORDER BY giorno, turno_id",
        (cal_id,)
    )
    return jsonify({'ok': True, 'assegnazioni': assegnazioni}), 200


@bp.route('/calendari/<int:cal_id>/assegnazioni', methods=['POST'])
@require_role('admin', 'manager')
def salva_assegnazione(cal_id):
    """
    Inserisce o aggiorna l'assegnazione di un lavoratore a un turno/giorno.

    Se user_id è null, marca la cella come turno scoperto (conflitto='empty').
    Applica le validazioni tramite valida_assegnazione() e registra la modifica
    nella history per consentire undo/redo.

    Body JSON:
        turno_id (int): ID del turno.
        giorno (int): giorno del mese (1-31).
        user_id (int|null): ID lavoratore, null per turno scoperto.
        forza_inserimento (bool): True per bypassare vincoli bypassabili (default False).
        forza_note (str|null): nota opzionale quando si forza l'inserimento.

    Returns:
        200: { ok: true, id: int, conflitto: str, avviso_domani: bool }
        400: { ok: false, errore: str, codice: str }  — vincolo assoluto
        409: { ok: false, errore: str, codice: str }  — vincolo bypassabile
        404: { ok: false, errore: str }
    """
    cal = ottieni_calendario_aperto(cal_id)

    dati = request.get_json(silent=True) or {}
    turno_id   = dati.get('turno_id')
    giorno     = dati.get('giorno')
    user_id    = dati.get('user_id')
    forza      = bool(dati.get('forza_inserimento', False))
    forza_note = dati.get('forza_note')

    if not turno_id or not giorno:
        return jsonify({'ok': False, 'errore': 'turno_id e giorno sono obbligatori.'}), 400

    me = get_current_user()

    # Check accesso manager (usa snapshot se disponibile)
    if me['role'] != 'admin':
        _snap = carica_config_snapshot(cal_id)
        ct = query_one("SELECT local_id FROM calendario_turni WHERE id=?", (turno_id,))
        if ct:
            _pt_id = int(ct['local_id'])
            if _snap:
                if not snap_manager_puo_turno(_snap, me['id'], _pt_id):
                    return jsonify({'ok': False, 'errore': 'Non hai accesso a questo turno.'}), 403
            elif not manager_puo_turno(me['id'], _pt_id):
                return jsonify({'ok': False, 'errore': 'Non hai accesso a questo turno.'}), 403
        if user_id is not None:
            if _snap:
                if not snap_manager_puo_utente(_snap, me['id'], user_id):
                    return jsonify({'ok': False, 'errore': 'Non hai accesso a questo utente.'}), 403
            elif not manager_puo_utente(me['id'], user_id):
                return jsonify({'ok': False, 'errore': 'Non hai accesso a questo utente.'}), 403

    # Check turno disattivato (non inseribile manualmente)
    ct_stato = query_one(
        "SELECT is_disabled FROM calendario_turni WHERE id=?", (turno_id,)
    )
    if ct_stato and ct_stato.get('is_disabled', 0) and user_id is not None:
        return jsonify({'ok': False, 'errore': 'Turno disattivato, non assegnabile.'}), 400

    # Check utente non escluso dal sistema turni
    if user_id is not None:
        u_check = query_one("SELECT escluso_turni FROM users WHERE id=?", (user_id,))
        if u_check and u_check['escluso_turni']:
            return jsonify({'ok': False, 'errore': 'Utente escluso dal sistema turni.'}), 400

    # Stato precedente per history
    precedente = query_one(
        "SELECT * FROM assegnazioni_turni WHERE calendario_id=? AND turno_id=? AND giorno=?",
        (cal_id, turno_id, giorno)
    )

    if user_id is None:
        conflitti_json = '[]'
        avviso_domani  = False
        conflitto_legacy = 'empty'
    else:
        try:
            risultato = valida_assegnazione(cal_id, turno_id, user_id, giorno, forza)
        except ValueError as e:
            return jsonify({'ok': False, 'errore': str(e)}), 400

        # Bloccato da regola con blocca_inserimento e non forzato
        if risultato.get('bloccato'):
            regole_bloccanti = [c['nome'] for c in risultato['conflitti']
                                if c.get('blocca_inserimento')]
            return jsonify({
                'ok': False,
                'errore': 'Inserimento bloccato da regola.',
                'codice': 'bloccato',
                'regole': regole_bloccanti
            }), 409

        conflitti_json   = json.dumps(risultato['conflitti'])
        avviso_domani    = risultato['avviso_domani']
        # Valore legacy per compatibilità con undo/redo history
        conflitto_legacy = 'free' if not risultato['conflitti'] else 'forced'

    execute_write(
        """
        INSERT INTO assegnazioni_turni
            (calendario_id, turno_id, giorno, user_id, forza_inserimento,
             forza_note, conflitto, conflitti, updated_at, updated_by)
        VALUES (?,?,?,?,?,?,?,?,datetime('now'),?)
        ON CONFLICT(calendario_id, turno_id, giorno) DO UPDATE SET
            user_id           = excluded.user_id,
            forza_inserimento = excluded.forza_inserimento,
            forza_note        = excluded.forza_note,
            conflitto         = excluded.conflitto,
            conflitti         = excluded.conflitti,
            updated_at        = excluded.updated_at,
            updated_by        = excluded.updated_by
        """,
        (cal_id, turno_id, giorno, user_id, int(forza), forza_note,
         conflitto_legacy, conflitti_json, me['id'])
    )

    nuova = query_one(
        "SELECT * FROM assegnazioni_turni WHERE calendario_id=? AND turno_id=? AND giorno=?",
        (cal_id, turno_id, giorno)
    )
    aggiungi_step(
        cal_id, 'assegnazioni_turni', nuova['id'],
        dict(precedente) if precedente else None,
        dict(nuova), me['id']
    )

    # Ricalcola conflitti per tutte le assegnazioni del calendario
    vicini = _ricalcola_tutti_conflitti(cal_id, escludi_ass_id=nuova['id'])
    hist = get_info_history(cal_id)

    broadcast_assegnazione(
        cal_id, turno_id, giorno, user_id,
        nuova.get('conflitto', 'free'),
        nuova.get('conflitti', '[]'),
        hist, me['id']
    )

    return jsonify({
        'ok': True,
        'id': nuova['id'],
        'conflitti': json.loads(nuova.get('conflitti', '[]')),
        'avviso_domani': avviso_domani,
        'vicini': vicini,
    }), 200


@bp.route('/calendari/<int:cal_id>/assegnazioni/<int:ass_id>', methods=['DELETE'])
@require_role('admin', 'manager')
def svuota_assegnazione(cal_id, ass_id):
    """
    Rimuove il lavoratore da un'assegnazione marcandola come turno scoperto.

    Imposta user_id=NULL e conflitto='empty' invece di cancellare il record,
    mantenendo la cella visibile nella griglia.

    Args:
        cal_id (int): ID del calendario.
        ass_id (int): ID dell'assegnazione.

    Returns:
        200: { ok: true, messaggio: str }
        404: { ok: false, errore: str }
    """
    precedente = query_one(
        "SELECT * FROM assegnazioni_turni WHERE id=? AND calendario_id=?",
        (ass_id, cal_id)
    )
    if not precedente:
        return jsonify({'ok': False, 'errore': 'Assegnazione non trovata.'}), 404

    me = get_current_user()

    # Check accesso turno per manager (l'utente assegnato non viene
    # verificato: se il manager vede il turno, puo' svuotare la cella)
    if me['role'] != 'admin':
        _snap = carica_config_snapshot(cal_id)
        ct = query_one("SELECT local_id FROM calendario_turni WHERE id=?", (precedente['turno_id'],))
        if ct:
            _pt_id = int(ct['local_id'])
            if (_snap and not snap_manager_puo_turno(_snap, me['id'], _pt_id)) or \
               (not _snap and not manager_puo_turno(me['id'], _pt_id)):
                return jsonify({'ok': False, 'errore': 'Non hai accesso a questo turno.'}), 403

    execute_write(
        "UPDATE assegnazioni_turni SET user_id=NULL, conflitto='empty', conflitti='[]', "
        "forza_inserimento=0, forza_note=NULL, "
        "updated_at=datetime('now'), updated_by=? WHERE id=?",
        (me['id'], ass_id)
    )

    nuova = query_one("SELECT * FROM assegnazioni_turni WHERE id=?", (ass_id,))
    aggiungi_step(
        cal_id, 'assegnazioni_turni', ass_id,
        dict(precedente), dict(nuova), me['id']
    )

    vicini = _ricalcola_conflitti_vicini(cal_id, precedente['user_id'], precedente['giorno'],
                                         escludi_turno_id=precedente['turno_id'])
    hist = get_info_history(cal_id)
    broadcast_svuota(cal_id, precedente['turno_id'], precedente['giorno'], hist, me['id'])

    return jsonify({'ok': True, 'messaggio': 'Assegnazione svuotata.', 'vicini': vicini}), 200


@bp.route('/calendari/<int:cal_id>/svuota-batch', methods=['POST'])
@require_role('admin', 'manager')
def svuota_batch(cal_id):
    """Svuota più celle in batch (singola transazione + singolo step history).

    Body: { celle: [{turno_id, giorno}, ...] }
    """
    cal = ottieni_calendario_aperto(cal_id)

    me = get_current_user()
    dati = request.get_json(silent=True) or {}
    celle = dati.get('celle', [])
    if not celle:
        return jsonify({'ok': True, 'svuotate': 0}), 200

    # Mappa accesso per manager non-admin
    _snap = None
    ct_to_local = {}
    if me['role'] != 'admin':
        _snap = carica_config_snapshot(cal_id)
        ct_rows = query_all(
            "SELECT id, local_id FROM calendario_turni WHERE calendario_id=?",
            (cal_id,)
        )
        ct_to_local = {r['id']: int(r['local_id']) for r in ct_rows}

    dati_prec = []
    dati_nuovi = []
    users_affected = set()
    ids_to_clear = []

    for c in celle:
        turno_id = c.get('turno_id')
        giorno = c.get('giorno')
        if not turno_id or not giorno:
            continue

        row = query_one(
            "SELECT * FROM assegnazioni_turni "
            "WHERE calendario_id=? AND turno_id=? AND giorno=?",
            (cal_id, turno_id, giorno)
        )
        if not row or row['user_id'] is None:
            continue

        # Check accesso turno per manager (l'utente assegnato non viene
        # verificato: se il manager vede il turno, puo' svuotare la cella)
        if me['role'] != 'admin':
            local = ct_to_local.get(turno_id)
            if local is not None:
                if (_snap and not snap_manager_puo_turno(_snap, me['id'], local)) or \
                   (not _snap and not manager_puo_turno(me['id'], local)):
                    continue

        users_affected.add(row['user_id'])
        ids_to_clear.append(row['id'])

        dati_prec.append({
            'tabella': 'assegnazioni_turni',
            'record_id': row['id'],
            'dati': dict(row),
        })

    if not ids_to_clear:
        return jsonify({'ok': True, 'svuotate': 0}), 200

    # Singola transazione: svuota tutte le celle in un colpo
    db = get_db()
    placeholders = ','.join('?' * len(ids_to_clear))
    db.execute(
        f"UPDATE assegnazioni_turni SET user_id=NULL, conflitto='empty', conflitti='[]', "
        f"forza_inserimento=0, forza_note=NULL, "
        f"updated_at=datetime('now'), updated_by=? "
        f"WHERE id IN ({placeholders})",
        [me['id']] + ids_to_clear
    )
    db.commit()

    # Leggi le righe aggiornate per history
    for rid in ids_to_clear:
        nuova = query_one("SELECT * FROM assegnazioni_turni WHERE id=?", (rid,))
        dati_nuovi.append({
            'tabella': 'assegnazioni_turni',
            'record_id': nuova['id'],
            'dati': dict(nuova),
        })

    # Singolo step history per tutto il batch
    aggiungi_step(cal_id, 'azzera', 0, dati_prec, dati_nuovi, me['id'])

    # Ricalcola conflitti per utenti coinvolti (celle vicine potrebbero avere conflitti risolti)
    giorni_affected = {c.get('giorno') for c in celle if c.get('giorno')}
    for uid in users_affected:
        for g in giorni_affected:
            _ricalcola_conflitti_vicini(cal_id, uid, g)

    hist = get_info_history(cal_id)
    broadcast_solver(cal_id, {'celle_riempite': 0, 'turni_operati': 0}, me['id'])

    return jsonify({
        'ok': True,
        'svuotate': len(dati_prec),
        'history': hist,
    }), 200


@bp.route('/calendari/<int:cal_id>/salva-batch', methods=['POST'])
@require_role('admin', 'manager')
def salva_batch(cal_id):
    """Salva più assegnazioni in batch — singola transazione + singolo step history.

    Usato per incolla celle dalla clipboard.
    Body: { celle: [{turno_id, giorno, user_id, forza_inserimento?}], forza_inserimento? }
    Returns: { ok, salvate, bloccate: [{turno_id, giorno, regole}], history }
    """
    cal = ottieni_calendario_aperto(cal_id)

    me = get_current_user()
    dati = request.get_json(silent=True) or {}
    celle = dati.get('celle', [])
    forza_globale = bool(dati.get('forza_inserimento', False))

    if not celle:
        return jsonify({'ok': True, 'salvate': 0, 'bloccate': []}), 200

    db = get_db()
    _snap = None
    ct_to_local = {}
    if me['role'] != 'admin':
        _snap = carica_config_snapshot(cal_id)
        ct_rows = query_all(
            "SELECT id, local_id FROM calendario_turni WHERE calendario_id=?",
            (cal_id,)
        )
        ct_to_local = {r['id']: int(r['local_id']) for r in ct_rows}

    dati_prec = []
    dati_nuovi = []
    bloccate = []
    users_affected = set()
    giorni_affected = set()

    for c in celle:
        turno_id = c.get('turno_id')
        giorno = c.get('giorno')
        user_id = c.get('user_id')
        forza = forza_globale or bool(c.get('forza_inserimento', False))

        if not turno_id or not giorno:
            continue

        if me['role'] != 'admin':
            local = ct_to_local.get(turno_id)
            if local is not None and (
                (_snap and not snap_manager_puo_turno(_snap, me['id'], local)) or
                (not _snap and not manager_puo_turno(me['id'], local))
            ):
                continue
            if user_id is not None and (
                (_snap and not snap_manager_puo_utente(_snap, me['id'], user_id)) or
                (not _snap and not manager_puo_utente(me['id'], user_id))
            ):
                continue

        # Skip silenzioso se l'utente è escluso dal sistema turni
        if user_id is not None:
            u_check = query_one("SELECT escluso_turni FROM users WHERE id=?", (user_id,))
            if u_check and u_check['escluso_turni']:
                continue

        precedente = query_one(
            "SELECT * FROM assegnazioni_turni WHERE calendario_id=? AND turno_id=? AND giorno=?",
            (cal_id, turno_id, giorno)
        )

        if user_id is None:
            conflitti_json = '[]'
            conflitto_legacy = 'empty'
        else:
            try:
                risultato = valida_assegnazione(cal_id, turno_id, user_id, giorno, forza)
            except ValueError as e:
                bloccate.append({'turno_id': turno_id, 'giorno': giorno, 'regole': [str(e)]})
                continue

            if risultato.get('bloccato'):
                regole_bloccanti = [
                    co['nome'] for co in risultato['conflitti'] if co.get('blocca_inserimento')
                ]
                bloccate.append({'turno_id': turno_id, 'giorno': giorno, 'regole': regole_bloccanti})
                continue

            conflitti_json = json.dumps(risultato['conflitti'])
            conflitto_legacy = 'free' if not risultato['conflitti'] else 'forced'

        db.execute(
            """
            INSERT INTO assegnazioni_turni
                (calendario_id, turno_id, giorno, user_id, forza_inserimento,
                 forza_note, conflitto, conflitti, updated_at, updated_by)
            VALUES (?,?,?,?,?,?,?,?,datetime('now'),?)
            ON CONFLICT(calendario_id, turno_id, giorno) DO UPDATE SET
                user_id           = excluded.user_id,
                forza_inserimento = excluded.forza_inserimento,
                forza_note        = excluded.forza_note,
                conflitto         = excluded.conflitto,
                conflitti         = excluded.conflitti,
                updated_at        = excluded.updated_at,
                updated_by        = excluded.updated_by
            """,
            (cal_id, turno_id, giorno, user_id, int(forza), None,
             conflitto_legacy, conflitti_json, me['id'])
        )

        nuova = query_one(
            "SELECT * FROM assegnazioni_turni WHERE calendario_id=? AND turno_id=? AND giorno=?",
            (cal_id, turno_id, giorno)
        )
        dati_prec.append({
            'tabella': 'assegnazioni_turni',
            'record_id': nuova['id'],
            'dati': dict(precedente) if precedente else None,
        })
        dati_nuovi.append({
            'tabella': 'assegnazioni_turni',
            'record_id': nuova['id'],
            'dati': dict(nuova),
        })
        if user_id:
            users_affected.add(user_id)
        giorni_affected.add(giorno)

    if not dati_prec:
        return jsonify({'ok': True, 'salvate': 0, 'bloccate': bloccate}), 200

    # Singolo commit per tutto il batch (evita perdita dati con WAL + commit multipli)
    db.commit()

    aggiungi_step(cal_id, 'incolla', 0, dati_prec, dati_nuovi, me['id'])

    for uid in users_affected:
        for g in giorni_affected:
            _ricalcola_conflitti_vicini(cal_id, uid, g)

    hist = get_info_history(cal_id)
    broadcast_solver(cal_id, {'celle_riempite': len(dati_prec), 'turni_operati': 0}, me['id'])

    return jsonify({
        'ok': True,
        'salvate': len(dati_prec),
        'bloccate': bloccate,
        'history': hist,
    }), 200


# =============================================================================
# SCAMBIO / SPOSTAMENTO CELLE (drag & drop)
# =============================================================================

@bp.route('/calendari/<int:cal_id>/scambia', methods=['POST'])
@require_role('admin', 'manager')
def scambia_assegnazioni(cal_id):
    """
    Scambia o sposta lavoratori tra due celle in un'unica transazione history.

    Body JSON:
        src_turno_id (int), src_giorno (int)
        tgt_turno_id (int), tgt_giorno (int)

    Se la cella target è vuota → sposta (src svuotato, tgt riempito).
    Se la cella target ha un utente → swap.
    """
    cal = ottieni_calendario_aperto(cal_id)

    dati = request.get_json(silent=True) or {}
    src_turno = dati.get('src_turno_id')
    src_giorno = dati.get('src_giorno')
    tgt_turno = dati.get('tgt_turno_id')
    tgt_giorno = dati.get('tgt_giorno')

    if not all([src_turno, src_giorno, tgt_turno, tgt_giorno]):
        return jsonify({'ok': False, 'errore': 'Parametri mancanti.'}), 400

    me = get_current_user()

    # Check accesso manager su entrambi i turni (usa snapshot)
    if me['role'] != 'admin':
        _snap = carica_config_snapshot(cal_id)
        for tid in (src_turno, tgt_turno):
            ct = query_one("SELECT local_id FROM calendario_turni WHERE id=?", (tid,))
            if ct:
                _pt_id = int(ct['local_id'])
                if (_snap and not snap_manager_puo_turno(_snap, me['id'], _pt_id)) or \
                   (not _snap and not manager_puo_turno(me['id'], _pt_id)):
                    return jsonify({'ok': False, 'errore': 'Non hai accesso a questo turno.'}), 403

    # Leggi stato precedente di entrambe le celle
    src_row = query_one(
        "SELECT * FROM assegnazioni_turni WHERE calendario_id=? AND turno_id=? AND giorno=?",
        (cal_id, src_turno, src_giorno)
    )
    tgt_row = query_one(
        "SELECT * FROM assegnazioni_turni WHERE calendario_id=? AND turno_id=? AND giorno=?",
        (cal_id, tgt_turno, tgt_giorno)
    )

    src_user = src_row['user_id'] if src_row else None
    tgt_user = tgt_row['user_id'] if tgt_row else None

    if not src_user:
        return jsonify({'ok': False, 'errore': 'Cella sorgente vuota.'}), 400

    # Snapshot precedente per history
    src_prev = dict(src_row) if src_row else None
    tgt_prev = dict(tgt_row) if tgt_row else None

    # --- Applica: metti src_user nella cella target ---
    execute_write(
        """
        INSERT INTO assegnazioni_turni
            (calendario_id, turno_id, giorno, user_id, conflitto, conflitti,
             updated_at, updated_by)
        VALUES (?,?,?,?,?,?,datetime('now'),?)
        ON CONFLICT(calendario_id, turno_id, giorno) DO UPDATE SET
            user_id=excluded.user_id, conflitto=excluded.conflitto,
            conflitti=excluded.conflitti,
            updated_at=excluded.updated_at, updated_by=excluded.updated_by
        """,
        (cal_id, tgt_turno, tgt_giorno, src_user, 'free', '[]', me['id'])
    )

    # --- Applica: cella sorgente → tgt_user (swap) o null (move) ---
    if tgt_user:
        execute_write(
            """
            INSERT INTO assegnazioni_turni
                (calendario_id, turno_id, giorno, user_id, conflitto, conflitti,
                 updated_at, updated_by)
            VALUES (?,?,?,?,?,?,datetime('now'),?)
            ON CONFLICT(calendario_id, turno_id, giorno) DO UPDATE SET
                user_id=excluded.user_id, conflitto=excluded.conflitto,
                conflitti=excluded.conflitti,
                updated_at=excluded.updated_at, updated_by=excluded.updated_by
            """,
            (cal_id, src_turno, src_giorno, tgt_user, 'free', '[]', me['id'])
        )
    else:
        execute_write(
            """
            INSERT INTO assegnazioni_turni
                (calendario_id, turno_id, giorno, user_id, conflitto, conflitti,
                 updated_at, updated_by)
            VALUES (?,?,?,?,?,?,datetime('now'),?)
            ON CONFLICT(calendario_id, turno_id, giorno) DO UPDATE SET
                user_id=NULL, conflitto='empty', conflitti='[]',
                updated_at=excluded.updated_at, updated_by=excluded.updated_by
            """,
            (cal_id, src_turno, src_giorno, None, 'empty', '[]', me['id'])
        )

    # Leggi stato nuovo di entrambe le celle
    src_new = query_one(
        "SELECT * FROM assegnazioni_turni WHERE calendario_id=? AND turno_id=? AND giorno=?",
        (cal_id, src_turno, src_giorno)
    )
    tgt_new = query_one(
        "SELECT * FROM assegnazioni_turni WHERE calendario_id=? AND turno_id=? AND giorno=?",
        (cal_id, tgt_turno, tgt_giorno)
    )

    # Registra come singolo step compound nella history
    dati_prec = [
        {'tabella': 'assegnazioni_turni', 'record_id': src_new['id'],
         'dati': src_prev},
        {'tabella': 'assegnazioni_turni', 'record_id': tgt_new['id'],
         'dati': tgt_prev},
    ]
    dati_nuovi = [
        {'tabella': 'assegnazioni_turni', 'record_id': src_new['id'],
         'dati': dict(src_new)},
        {'tabella': 'assegnazioni_turni', 'record_id': tgt_new['id'],
         'dati': dict(tgt_new)},
    ]
    aggiungi_step(
        cal_id, 'swap', 0,
        dati_prec, dati_nuovi, me['id']
    )

    # Ricalcola conflitti
    vicini = _ricalcola_tutti_conflitti(cal_id)

    return jsonify({
        'ok': True,
        'src': {'turno_id': src_turno, 'giorno': src_giorno,
                'user_id': src_new['user_id'],
                'conflitti': json.loads(src_new.get('conflitti', '[]'))},
        'tgt': {'turno_id': tgt_turno, 'giorno': tgt_giorno,
                'user_id': tgt_new['user_id'],
                'conflitti': json.loads(tgt_new.get('conflitti', '[]'))},
        'vicini': vicini,
    }), 200


# =============================================================================
# LAVORATORI DISPONIBILI
# =============================================================================

@bp.route('/calendari/<int:cal_id>/disponibili', methods=['GET'])
@require_role('admin', 'manager')
def lavoratori_disponibili(cal_id):
    """
    Restituisce la lista dei lavoratori disponibili per un dato turno e giorno.

    Query params:
        turno_id (int): ID del turno da assegnare.
        giorno (int): giorno del mese (1-31).
        ignora_notte (bool): se 'true', include anche lavoratori con conflitto notte.

    Returns:
        200: { ok: true, disponibili: [...] }
        400: { ok: false, errore: str }
    """
    turno_id = request.args.get('turno_id', type=int)
    giorno   = request.args.get('giorno', type=int)
    # ignora_notte mantenuto per retrocompatibilità ma ignorato nel nuovo sistema
    ignora_notte = request.args.get('ignora_notte', 'false').lower() == 'true'

    if not turno_id or not giorno:
        return jsonify({'ok': False, 'errore': 'turno_id e giorno sono obbligatori.'}), 400

    try:
        disponibili = get_disponibili(cal_id, turno_id, giorno, ignora_notte)
    except ValueError as e:
        return jsonify({'ok': False, 'errore': str(e)}), 400

    return jsonify({'ok': True, 'disponibili': disponibili}), 200


# =============================================================================
# DESIDERATA ORIGINALI
# =============================================================================

@bp.route('/calendari/<int:cal_id>/desiderata', methods=['GET'])
@require_role('admin', 'manager')
def lista_desiderata(cal_id):
    """
    Restituisce tutti i desiderata originali inseriti dai lavoratori Basic
    per un calendario, arricchiti con sigla utente e tipo richiesta.

    Args:
        cal_id (int): ID del calendario.

    Returns:
        200: { ok: true, desiderata: [...] }
        404: { ok: false, errore: str }
    """
    cal = query_one("SELECT id FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    des = query_all(
        """
        SELECT d.id, d.user_id, u.sigla, d.giorno,
               d.tipo_richiesta_id, tr.sigla AS req_sigla,
               tr.tipo AS req_tipo, d.note, d.updated_at
        FROM desiderata d
        JOIN users u ON d.user_id = u.id
        LEFT JOIN tipi_richiesta tr ON d.tipo_richiesta_id = tr.id
        WHERE d.calendario_id = ?
        ORDER BY u.sigla, d.giorno
        """,
        (cal_id,)
    )
    return jsonify({
        'ok': True,
        'desiderata': _arricchisci_con_tipo_richiesta(des, cal_id),
    }), 200


# =============================================================================
# WORKING DESIDERATA
# =============================================================================

@bp.route('/calendari/<int:cal_id>/working-desiderata', methods=['GET'])
@require_role('admin', 'manager')
def lista_working_desiderata(cal_id):
    """
    Restituisce tutti i working_desiderata del calendario con dati arricchiti.

    Returns:
        200: { ok: true, working_desiderata: [...] }
    """
    wd = query_all(
        """
        SELECT wd.id, wd.user_id, u.sigla, wd.giorno,
               wd.tipo_richiesta_id, tr.sigla AS req_sigla,
               tr.tipo AS req_tipo, wd.note, wd.updated_at
        FROM working_desiderata wd
        JOIN users u ON wd.user_id = u.id
        LEFT JOIN tipi_richiesta tr ON wd.tipo_richiesta_id = tr.id
        WHERE wd.calendario_id=?
        ORDER BY u.sigla, wd.giorno
        """,
        (cal_id,)
    )
    return jsonify({
        'ok': True,
        'working_desiderata': _arricchisci_con_tipo_richiesta(wd, cal_id),
    }), 200


@bp.route('/calendari/<int:cal_id>/working-desiderata', methods=['PUT'])
@require_role('admin', 'manager')
def aggiorna_working_desiderata(cal_id):
    """
    Aggiorna o rimuove un working_desiderata (modifica tipo richiesta o note).

    Il calendario deve avere i desiderata già congelati.
    La modifica viene registrata nella history per consentire undo/redo.

    Body JSON:
        user_id (int): ID del lavoratore.
        giorno (int): giorno del mese (1-31).
        tipo_richiesta_id (int|null): nuovo tipo richiesta, null per rimuovere il record.
        note (str|null): note opzionali.

    Returns:
        200: { ok: true, messaggio: str }
        400: { ok: false, errore: str }
        404: { ok: false, errore: str }
    """
    cal = query_one("SELECT id, desiderata_congelati FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404
    if not cal['desiderata_congelati']:
        return jsonify({'ok': False, 'errore': 'I desiderata non sono ancora congelati.'}), 400

    dati    = request.get_json(silent=True) or {}
    user_id = dati.get('user_id')
    giorno  = dati.get('giorno')
    tipo_id = dati.get('tipo_richiesta_id')
    note    = dati.get('note')

    if not user_id or not giorno:
        return jsonify({'ok': False, 'errore': 'user_id e giorno sono obbligatori.'}), 400

    me = get_current_user()
    precedente = query_one(
        "SELECT * FROM working_desiderata WHERE calendario_id=? AND user_id=? AND giorno=?",
        (cal_id, user_id, giorno)
    )

    if tipo_id is None:
        if precedente:
            execute_write(
                "DELETE FROM working_desiderata WHERE calendario_id=? AND user_id=? AND giorno=?",
                (cal_id, user_id, giorno)
            )
            wd_aggiungi_step(
                cal_id, 'working_desiderata', precedente['id'],
                dict(precedente), {}, me['id']
            )
        # Ricalcola conflitti assegnazioni per questo utente/giorno
        vicini = _ricalcola_conflitti_vicini(cal_id, user_id, giorno)
        wd_hist = wd_get_info_history(cal_id)
        broadcast_desiderata_changed(
            cal_id, user_id, giorno, None, 'working_desiderata', me['id']
        )
        return jsonify({'ok': True, 'messaggio': 'Working desiderata rimosso.', 'vicini': vicini, 'wd_history': wd_hist}), 200

    execute_write(
        """
        INSERT INTO working_desiderata
            (calendario_id, user_id, giorno, tipo_richiesta_id, note,
             updated_at, updated_by)
        VALUES (?,?,?,?,?,datetime('now'),?)
        ON CONFLICT(calendario_id, user_id, giorno) DO UPDATE SET
            tipo_richiesta_id = excluded.tipo_richiesta_id,
            note              = excluded.note,
            updated_at        = excluded.updated_at,
            updated_by        = excluded.updated_by
        """,
        (cal_id, user_id, giorno, tipo_id, note, me['id'])
    )

    nuova = query_one(
        "SELECT * FROM working_desiderata WHERE calendario_id=? AND user_id=? AND giorno=?",
        (cal_id, user_id, giorno)
    )
    wd_aggiungi_step(
        cal_id, 'working_desiderata', nuova['id'],
        dict(precedente) if precedente else None,
        dict(nuova), me['id']
    )

    # Ricalcola conflitti assegnazioni per questo utente/giorno
    vicini = _ricalcola_conflitti_vicini(cal_id, user_id, giorno)
    wd_hist = wd_get_info_history(cal_id)

    tr = query_one("SELECT sigla, tipo FROM tipi_richiesta WHERE id=?", (tipo_id,))
    entry = {
        'tipo_richiesta_id': tipo_id,
        'req_sigla': tr['sigla'] if tr else '',
        'req_tipo':  tr['tipo']  if tr else '',
    }
    broadcast_desiderata_changed(
        cal_id, user_id, giorno, entry, 'working_desiderata', me['id']
    )

    return jsonify({'ok': True, 'messaggio': 'Working desiderata aggiornato.', 'vicini': vicini, 'wd_history': wd_hist}), 200


@bp.route('/calendari/<int:cal_id>/working-desiderata/svuota-batch', methods=['POST'])
@require_role('admin', 'manager')
def svuota_batch_wd(cal_id):
    """Rimuove più working_desiderata in batch (singolo step history).

    Body: { celle: [{user_id, giorno}, ...] }
    """
    cal = query_one("SELECT id, desiderata_congelati FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404
    if not cal['desiderata_congelati']:
        return jsonify({'ok': False, 'errore': 'I desiderata non sono ancora congelati.'}), 400

    me = get_current_user()
    dati = request.get_json(silent=True) or {}
    celle = dati.get('celle', [])
    if not celle:
        return jsonify({'ok': True, 'svuotate': 0}), 200

    dati_prec = []
    dati_nuovi = []
    users_affected = set()

    for c in celle:
        user_id = c.get('user_id')
        giorno = c.get('giorno')
        if not user_id or not giorno:
            continue

        row = query_one(
            "SELECT * FROM working_desiderata WHERE calendario_id=? AND user_id=? AND giorno=?",
            (cal_id, user_id, giorno)
        )
        if not row:
            continue

        dati_prec.append({
            'tabella': 'working_desiderata',
            'record_id': row['id'],
            'dati': dict(row),
        })

        execute_write(
            "DELETE FROM working_desiderata WHERE calendario_id=? AND user_id=? AND giorno=?",
            (cal_id, user_id, giorno)
        )
        dati_nuovi.append({
            'tabella': 'working_desiderata',
            'record_id': row['id'],
            'dati': None,
            'calendario_id': cal_id,
            'user_id': user_id,
            'giorno': giorno,
        })

        users_affected.add(user_id)

    if not dati_prec:
        return jsonify({'ok': True, 'svuotate': 0}), 200

    # Singolo step wd_history per tutto il batch
    wd_aggiungi_step(cal_id, 'azzera_wd', 0, dati_prec, dati_nuovi, me['id'])

    # Ricalcola conflitti per utenti coinvolti
    giorni_affected = {c.get('giorno') for c in celle if c.get('giorno')}
    for uid in users_affected:
        for g in giorni_affected:
            _ricalcola_conflitti_vicini(cal_id, uid, g)

    # Broadcast ogni cella cancellata per sync real-time altri client
    for item in dati_nuovi:
        broadcast_desiderata_changed(
            cal_id, item['user_id'], item['giorno'], None,
            'working_desiderata', me['id']
        )

    wd_hist = wd_get_info_history(cal_id)
    return jsonify({'ok': True, 'svuotate': len(dati_prec), 'wd_history': wd_hist}), 200


@bp.route('/calendari/<int:cal_id>/working-desiderata/salva-batch', methods=['POST'])
@require_role('admin', 'manager')
def salva_batch_wd(cal_id):
    """Salva più working_desiderata in batch — singola transazione + singolo step history.

    Usato per incolla celle WD dalla clipboard.
    Body: { celle: [{user_id, giorno, tipo_richiesta_id}] }
    Returns: { ok, salvate, wd_history }
    """
    cal = query_one("SELECT id, desiderata_congelati FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404
    if not cal['desiderata_congelati']:
        return jsonify({'ok': False, 'errore': 'I desiderata non sono ancora congelati.'}), 400

    me = get_current_user()
    dati = request.get_json(silent=True) or {}
    celle = dati.get('celle', [])

    if not celle:
        return jsonify({'ok': True, 'salvate': 0}), 200

    dati_prec = []
    dati_nuovi = []
    users_affected = set()
    giorni_affected = set()

    for c in celle:
        user_id = c.get('user_id')
        giorno = c.get('giorno')
        tipo_id = c.get('tipo_richiesta_id')

        if not user_id or not giorno:
            continue

        precedente = query_one(
            "SELECT * FROM working_desiderata WHERE calendario_id=? AND user_id=? AND giorno=?",
            (cal_id, user_id, giorno)
        )

        if tipo_id is None:
            if not precedente:
                continue
            execute_write(
                "DELETE FROM working_desiderata WHERE calendario_id=? AND user_id=? AND giorno=?",
                (cal_id, user_id, giorno)
            )
            dati_prec.append({
                'tabella': 'working_desiderata',
                'record_id': precedente['id'],
                'dati': dict(precedente),
            })
            dati_nuovi.append({
                'tabella': 'working_desiderata',
                'record_id': precedente['id'],
                'dati': None,
                'calendario_id': cal_id,
                'user_id': user_id,
                'giorno': giorno,
            })
        else:
            execute_write(
                """
                INSERT INTO working_desiderata
                    (calendario_id, user_id, giorno, tipo_richiesta_id, note, updated_at, updated_by)
                VALUES (?,?,?,?,NULL,datetime('now'),?)
                ON CONFLICT(calendario_id, user_id, giorno) DO UPDATE SET
                    tipo_richiesta_id = excluded.tipo_richiesta_id,
                    note              = excluded.note,
                    updated_at        = excluded.updated_at,
                    updated_by        = excluded.updated_by
                """,
                (cal_id, user_id, giorno, tipo_id, me['id'])
            )
            nuova = query_one(
                "SELECT * FROM working_desiderata WHERE calendario_id=? AND user_id=? AND giorno=?",
                (cal_id, user_id, giorno)
            )
            dati_prec.append({
                'tabella': 'working_desiderata',
                'record_id': nuova['id'],
                'dati': dict(precedente) if precedente else None,
                'calendario_id': cal_id,
                'user_id': user_id,
                'giorno': giorno,
            })
            dati_nuovi.append({
                'tabella': 'working_desiderata',
                'record_id': nuova['id'],
                'dati': dict(nuova),
            })

        users_affected.add(user_id)
        giorni_affected.add(giorno)

    if not dati_prec:
        return jsonify({'ok': True, 'salvate': 0}), 200

    wd_aggiungi_step(cal_id, 'incolla_wd', 0, dati_prec, dati_nuovi, me['id'])

    for uid in users_affected:
        for g in giorni_affected:
            _ricalcola_conflitti_vicini(cal_id, uid, g)

    # Broadcast ogni cella inserita/modificata per sync real-time altri client
    for item in dati_nuovi:
        dati_rec = item.get('dati')
        if dati_rec is None:
            broadcast_desiderata_changed(
                cal_id, item.get('user_id'), item.get('giorno'), None,
                'working_desiderata', me['id']
            )
        else:
            tr = query_one(
                "SELECT sigla, tipo FROM tipi_richiesta WHERE id=?",
                (dati_rec.get('tipo_richiesta_id'),)
            )
            entry = {
                'tipo_richiesta_id': dati_rec.get('tipo_richiesta_id'),
                'req_sigla': tr['sigla'] if tr else '',
                'req_tipo':  tr['tipo']  if tr else '',
            }
            broadcast_desiderata_changed(
                cal_id, dati_rec['user_id'], dati_rec['giorno'],
                entry, 'working_desiderata', me['id']
            )

    wd_hist = wd_get_info_history(cal_id)
    return jsonify({
        'ok': True,
        'salvate': len(dati_prec),
        'wd_history': wd_hist,
    }), 200


@bp.route('/calendari/<int:cal_id>/wd-history', methods=['GET'])
@require_role('admin', 'manager')
def get_wd_history(cal_id):
    """Restituisce lo stato della history WD per il calendario."""
    return jsonify({'ok': True, 'wd_history': wd_get_info_history(cal_id)}), 200


@bp.route('/calendari/<int:cal_id>/wd-undo', methods=['POST'])
@require_role('admin', 'manager')
def wd_undo_endpoint(cal_id):
    """Annulla l'ultima modifica ai working desiderata."""
    ottieni_calendario_aperto(cal_id)

    me = get_current_user()
    r = wd_undo(cal_id, me['id'])
    if not r['ok']:
        return jsonify(r), 400
    r['wd_history'] = wd_get_info_history(cal_id)
    return jsonify(r), 200


@bp.route('/calendari/<int:cal_id>/wd-redo', methods=['POST'])
@require_role('admin', 'manager')
def wd_redo_endpoint(cal_id):
    """Ripete l'ultima modifica annullata ai working desiderata."""
    ottieni_calendario_aperto(cal_id)

    me = get_current_user()
    r = wd_redo(cal_id, me['id'])
    if not r['ok']:
        return jsonify(r), 400
    r['wd_history'] = wd_get_info_history(cal_id)
    return jsonify(r), 200


@bp.route('/calendari/<int:cal_id>/working-desiderata/ricarica', methods=['POST'])
@require_role('admin', 'manager')
def ricarica_desiderata_originali(cal_id):
    """Ricarica i desiderata originali nei working_desiderata (batch undoable).

    Cancella tutti i WD esistenti e li ricopia dai desiderata originali.
    L'operazione e' registrata come singolo step nella wd_history.
    """
    cal = query_one("SELECT id, desiderata_congelati FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404
    if not cal['desiderata_congelati']:
        return jsonify({'ok': False, 'errore': 'I desiderata non sono ancora congelati.'}), 400

    me = get_current_user()

    # Snapshot WD attuali (per undo)
    wd_attuali = query_all(
        "SELECT * FROM working_desiderata WHERE calendario_id=?", (cal_id,)
    )
    dati_prec = [{
        'tabella': 'working_desiderata',
        'record_id': r['id'],
        'dati': dict(r),
    } for r in wd_attuali]

    # Cancella tutti i WD
    execute_write("DELETE FROM working_desiderata WHERE calendario_id=?", (cal_id,))

    # Ricopia da desiderata originali
    execute_write("""
        INSERT INTO working_desiderata
            (calendario_id, user_id, giorno, tipo_richiesta_id, note, updated_at, updated_by)
        SELECT calendario_id, user_id, giorno, tipo_richiesta_id, note, datetime('now'), ?
        FROM desiderata
        WHERE calendario_id = ?
    """, (me['id'], cal_id))

    # Snapshot nuovi WD (per redo)
    wd_nuovi = query_all(
        "SELECT * FROM working_desiderata WHERE calendario_id=?", (cal_id,)
    )
    dati_nuovi = [{
        'tabella': 'working_desiderata',
        'record_id': r['id'],
        'dati': dict(r),
    } for r in wd_nuovi]

    wd_aggiungi_step(cal_id, 'ricarica_wd', 0, dati_prec, dati_nuovi, me['id'])

    wd_hist = wd_get_info_history(cal_id)
    return jsonify({
        'ok': True,
        'messaggio': f'Ricaricati {len(wd_nuovi)} desiderata originali.',
        'wd_history': wd_hist,
    }), 200


# =============================================================================
# ORE MENSILI
# =============================================================================

@bp.route('/calendari/<int:cal_id>/ore', methods=['GET'])
@require_role('admin', 'manager')
def ore_mensili(cal_id):
    """
    Calcola e restituisce il riepilogo ore mensile per tutti i lavoratori.

    Args:
        cal_id (int): ID del calendario.

    Returns:
        200: { ok: true, ore: [...] }
        404: { ok: false, errore: str }
    """
    cal = query_one("SELECT id FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    ore = calcola_ore_mensili(cal_id)
    return jsonify({'ok': True, 'ore': ore}), 200


# =============================================================================
# FORMATTAZIONE CALENDARIO / GRUPPI
# =============================================================================

@bp.route('/calendari/<int:cal_id>/style', methods=['PUT'])
@require_role('admin', 'manager')
def aggiorna_style_calendario(cal_id):
    """
    Aggiorna lo style del calendario (layout generale: colTurnoWidth ecc.).

    Body JSON:
        style (dict): proprietà CSS + custom properties.

    Returns:
        200: { ok: true }
        404: { ok: false, errore: str }
    """
    cal = query_one("SELECT id FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    style = json.dumps(dati.get('style', {}))
    execute_write("UPDATE calendari SET style=? WHERE id=?", (style, cal_id))
    return jsonify({'ok': True}), 200


@bp.route('/calendari/<int:cal_id>/formato-gruppo', methods=['PUT'])
@require_role('admin', 'manager')
def aggiorna_formato_gruppo(cal_id):
    """
    Aggiorna lo style di uno o più gruppi nello snapshot calendario_turni.
    Registra la modifica nello style_history per undo.

    Body JSON:
        gruppo_sigla (str): sigla del gruppo da aggiornare.
        gruppo_ordine (int): ordine del gruppo.
        style (dict): proprietà CSS + custom properties.
        applica_tutti (bool): se true, applica a tutti i gruppi del calendario.
        style_before (dict|list): stile precedente (per history). Se applica_tutti,
            lista di {gruppo_sigla, gruppo_ordine, style_before}.

    Returns:
        200: { ok: true, undo_count: int }
        404: { ok: false, errore: str }
    """
    from app.services.style_history import push_style_history, count_style_history

    cal = query_one("SELECT id FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    style = dati.get('style', {})
    style_json = json.dumps(style)
    applica_tutti = dati.get('applica_tutti', False)

    history_items = []

    if applica_tutti:
        # Leggi stili correnti di tutti i gruppi per history
        before_list = dati.get('style_before', [])
        for b in before_list:
            history_items.append({
                'tipo': 'gruppo', 'campo': 'style',
                'sigla': b['gruppo_sigla'], 'ordine': b['gruppo_ordine'],
                'style_before': b['style_before'], 'style_after': style
            })
        execute_write(
            "UPDATE calendario_turni SET style=? WHERE calendario_id=?",
            (style_json, cal_id)
        )
    else:
        gruppo_sigla = dati.get('gruppo_sigla', '')
        gruppo_ordine = dati.get('gruppo_ordine', 0)
        style_before = dati.get('style_before', {})
        history_items.append({
            'tipo': 'gruppo', 'campo': 'style',
            'sigla': gruppo_sigla, 'ordine': gruppo_ordine,
            'style_before': style_before, 'style_after': style
        })
        execute_write(
            "UPDATE calendario_turni SET style=? "
            "WHERE calendario_id=? AND gruppo_sigla=? AND gruppo_ordine=?",
            (style_json, cal_id, gruppo_sigla, gruppo_ordine)
        )

    undo_count = push_style_history('calendario', cal_id, history_items)
    return jsonify({'ok': True, 'undo_count': undo_count}), 200


@bp.route('/calendari/<int:cal_id>/formato-sovragruppo', methods=['PUT'])
@require_role('admin', 'manager')
def aggiorna_formato_sovragruppo(cal_id):
    """
    Aggiorna lo style di un sovragruppo nello snapshot calendario_turni.
    Registra la modifica nello style_history per undo.

    Body JSON:
        sg_sigla (str): sigla del sovragruppo.
        style (dict): proprietà CSS + custom properties.
        style_before (dict): stile precedente (per history).

    Returns:
        200: { ok: true, undo_count: int }
        404: { ok: false, errore: str }
    """
    from app.services.style_history import push_style_history, count_style_history

    cal = query_one("SELECT id FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    style = dati.get('style', {})
    style_json = json.dumps(style)
    sg_sigla = dati.get('sg_sigla', '')
    style_before = dati.get('style_before', {})

    execute_write(
        "UPDATE calendario_turni SET sg_style=? "
        "WHERE calendario_id=? AND sg_sigla=?",
        (style_json, cal_id, sg_sigla)
    )

    history_items = [{
        'tipo': 'sovragruppo', 'campo': 'sg_style',
        'sigla': sg_sigla,
        'style_before': style_before, 'style_after': style
    }]
    undo_count = push_style_history('calendario', cal_id, history_items)
    return jsonify({'ok': True, 'undo_count': undo_count}), 200


@bp.route('/calendari/<int:cal_id>/formato-batch', methods=['PUT'])
@require_role('admin', 'manager')
def aggiorna_formato_batch(cal_id):
    """
    Applica più modifiche di stile in un'unica operazione (un solo push history).

    Body JSON:
        items (list): [{tipo, sigla, ordine?, campo, style, style_before}, ...]
            tipo: 'sovragruppo' | 'gruppo'
            campo: 'sg_style' | 'style'

    Returns:
        200: { ok: true, undo_count: int }
        404: { ok: false, errore: str }
    """
    from app.services.style_history import push_style_history

    cal = query_one("SELECT id FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    items = dati.get('items', [])
    history_items = []

    for item in items:
        campo = item.get('campo', 'style')
        style_json = json.dumps(item.get('style', {}))
        style_before = item.get('style_before', {})
        style_after = item.get('style', {})

        if campo == 'sg_style':
            execute_write(
                "UPDATE calendario_turni SET sg_style=? "
                "WHERE calendario_id=? AND sg_sigla=?",
                (style_json, cal_id, item['sigla'])
            )
            history_items.append({
                'tipo': 'sovragruppo', 'campo': 'sg_style',
                'sigla': item['sigla'],
                'style_before': style_before, 'style_after': style_after
            })
        elif campo == 'style':
            execute_write(
                "UPDATE calendario_turni SET style=? "
                "WHERE calendario_id=? AND gruppo_sigla=? AND gruppo_ordine=?",
                (style_json, cal_id, item['sigla'], item.get('ordine', 0))
            )
            history_items.append({
                'tipo': 'gruppo', 'campo': 'style',
                'sigla': item['sigla'], 'ordine': item.get('ordine', 0),
                'style_before': style_before, 'style_after': style_after
            })

    undo_count = push_style_history('calendario', cal_id, history_items) if history_items else 0
    return jsonify({'ok': True, 'undo_count': undo_count}), 200


@bp.route('/calendari/<int:cal_id>/style-undo', methods=['POST'])
@require_role('admin', 'manager')
def undo_style_calendario(cal_id):
    """
    Annulla l'ultima operazione di formattazione sul calendario.

    Returns:
        200: { ok: true, undo_count: int, items: [...] }
        404: { ok: false, errore: str }
    """
    from app.services.style_history import pop_style_history, count_style_history

    ottieni_calendario_aperto(cal_id)

    items = pop_style_history('calendario', cal_id)
    if items is None:
        return jsonify({'ok': False, 'errore': 'Nessuna operazione da annullare.'}), 404

    for item in items:
        campo = item.get('campo', 'style')
        style_before = json.dumps(item.get('style_before', {}))

        if campo == 'sg_style':
            execute_write(
                "UPDATE calendario_turni SET sg_style=? "
                "WHERE calendario_id=? AND sg_sigla=?",
                (style_before, cal_id, item['sigla'])
            )
        elif campo == 'style':
            if 'ordine' in item:
                execute_write(
                    "UPDATE calendario_turni SET style=? "
                    "WHERE calendario_id=? AND gruppo_sigla=? AND gruppo_ordine=?",
                    (style_before, cal_id, item['sigla'], item['ordine'])
                )
            else:
                execute_write(
                    "UPDATE calendario_turni SET style=? "
                    "WHERE calendario_id=? AND gruppo_sigla=?",
                    (style_before, cal_id, item['sigla'])
                )

    undo_count = count_style_history('calendario', cal_id)
    return jsonify({'ok': True, 'undo_count': undo_count, 'items': items}), 200


# =============================================================================
# HISTORY — UNDO / REDO
# =============================================================================

@bp.route('/calendari/<int:cal_id>/history', methods=['GET'])
@require_role('admin', 'manager')
def info_history(cal_id):
    """
    Restituisce lo stato corrente della history per il calendario.

    Returns:
        200: { ok: true, history: { current_step, max_step, can_undo, can_redo, total_steps } }
    """
    info = get_info_history(cal_id)
    return jsonify({'ok': True, 'history': info}), 200


@bp.route('/calendari/<int:cal_id>/undo', methods=['POST'])
@require_role('admin', 'manager')
def undo_calendario(cal_id):
    """
    Annulla l'ultima modifica al calendario.

    Returns:
        200: { ok, messaggio, tabella, dati_applicati, history }
        400: { ok: false, errore: str }
    """
    ottieni_calendario_aperto(cal_id)

    me = get_current_user()
    risultato = undo(cal_id, me['id'])
    if risultato['ok']:
        risultato['history'] = get_info_history(cal_id)
        broadcast_undo_redo(
            cal_id, risultato.get('tabella'),
            risultato.get('dati_applicati'), risultato['history'], me['id']
        )
    return jsonify(risultato), 200 if risultato['ok'] else 400


@bp.route('/calendari/<int:cal_id>/redo', methods=['POST'])
@require_role('admin', 'manager')
def redo_calendario(cal_id):
    """
    Ripete l'ultima operazione annullata nel calendario.

    Returns:
        200: { ok, messaggio, tabella, dati_applicati, history }
        400: { ok: false, errore: str }
    """
    ottieni_calendario_aperto(cal_id)

    me = get_current_user()
    risultato = redo(cal_id, me['id'])
    if risultato['ok']:
        risultato['history'] = get_info_history(cal_id)
        broadcast_undo_redo(
            cal_id, risultato.get('tabella'),
            risultato.get('dati_applicati'), risultato['history'], me['id']
        )
    return jsonify(risultato), 200 if risultato['ok'] else 400


# =============================================================================
# SOLVER AUTOMATICO
# =============================================================================

@bp.route('/calendari/<int:cal_id>/solver', methods=['POST'])
@require_role('admin', 'manager')
def lancia_solver(cal_id):
    """
    Esegue il solver greedy per auto-riempimento turni.

    Body JSON:
        solo_vuote (bool): se true, riempie solo celle vuote (default true).
        solo_indispensabili (bool): se true, solo turni indispensabili (default false).
        dry_run (bool): se true, non scrive, restituisce solo la proposta (default false).
        multi_start (int): se > 0, esegue N run randomizzati e scrive il migliore (default 0).
        top_k (int): randomizzazione candidato — seleziona random tra i migliori k (default 1).

    Returns:
        200: { ok, celle_totali, celle_riempite, celle_fallite,
               indispensabili_scoperti, esecuzione_id, durata_ms }
        400/404: errore
    """
    cal = ottieni_calendario_aperto(cal_id, "id, stato, tipo")
    if cal.get('tipo') == 'effettivo':
        return jsonify({'ok': False, 'errore': 'Solver non disponibile su calendario effettivo.'}), 400

    # NB: regole_snapshot e config_snapshot NON vengono rigenerati —
    # restano quelli del calendario (editabili dal manager nella modale solver)

    dati = request.get_json(silent=True) or {}
    me = get_current_user()

    # Accesso manager: costruisci set completi (usa snapshot se disponibile)
    turni_accessibili = None
    utenti_accessibili = None
    if me['role'] != 'admin':
        _snap = carica_config_snapshot(cal_id)
        all_turni = query_all(
            "SELECT local_id FROM calendario_turni WHERE calendario_id=?",
            (cal_id,)
        )
        if _snap:
            turni_accessibili = {
                int(t['local_id']) for t in all_turni
                if snap_manager_puo_turno(_snap, me['id'], int(t['local_id']))
            }
        else:
            turni_accessibili = {
                int(t['local_id']) for t in all_turni
                if manager_puo_turno(me['id'], int(t['local_id']))
            }
        all_utenti = query_all(
            "SELECT id FROM users WHERE is_active=1"
        )
        if _snap:
            utenti_accessibili = {
                u['id'] for u in all_utenti
                if snap_manager_puo_utente(_snap, me['id'], u['id'])
            }
        else:
            utenti_accessibili = {
                u['id'] for u in all_utenti
                if manager_puo_utente(me['id'], u['id'])
            }

    multi_start = int(dati.get('multi_start', 0))
    top_k = int(dati.get('top_k', 1))
    criteri_ordinamento = dati.get('criteri_ordinamento')
    turni_ids = dati.get('turni_ids')  # lista di local_id selezionati (opzionale)
    fonte_desiderata = dati.get('fonte_desiderata', 'working')
    if fonte_desiderata not in ('working', 'originali'):
        fonte_desiderata = 'working'

    if multi_start > 0:
        from app.services.solver import esegui_solver_multistart
        risultato = esegui_solver_multistart(
            calendario_id=cal_id,
            user_id_chiamante=me['id'],
            n_runs=multi_start,
            top_k=max(top_k, 2),  # multi-start richiede almeno top_k=2
            solo_vuote=dati.get('solo_vuote', True),
            solo_indispensabili=dati.get('solo_indispensabili', False),
            escludi_regole_ids=dati.get('escludi_regole_ids'),
            turni_accessibili=turni_accessibili,
            utenti_accessibili=utenti_accessibili,
            criteri_ordinamento=criteri_ordinamento,
            turni_ids=turni_ids,
            fonte_desiderata=fonte_desiderata,
        )
    else:
        risultato = esegui_solver(
            calendario_id=cal_id,
            user_id_chiamante=me['id'],
            solo_vuote=dati.get('solo_vuote', True),
            solo_indispensabili=dati.get('solo_indispensabili', False),
            dry_run=dati.get('dry_run', False),
            escludi_regole_ids=dati.get('escludi_regole_ids'),
            turni_accessibili=turni_accessibili,
            utenti_accessibili=utenti_accessibili,
            top_k=top_k,
            criteri_ordinamento=criteri_ordinamento,
            turni_ids=turni_ids,
            fonte_desiderata=fonte_desiderata,
        )

    # Se non dry_run, ricalcola tutti i conflitti e broadcast
    if not dati.get('dry_run', False) and risultato.get('celle_riempite', 0) > 0:
        _ricalcola_tutti_conflitti(cal_id)
        broadcast_solver(cal_id, risultato, me['id'])

    return jsonify(risultato), 200


@bp.route('/calendari/<int:cal_id>/solver-log', methods=['GET'])
@require_role('admin', 'manager')
def solver_log(cal_id):
    """
    Restituisce il log delle esecuzioni del solver per un calendario.

    Returns:
        200: { ok, esecuzioni: [...] }
    """
    rows = query_all(
        "SELECT id, stato, celle_totali, celle_riempite, celle_fallite, "
        "durata_ms, created_by, created_at "
        "FROM solver_esecuzioni WHERE calendario_id=? ORDER BY id DESC LIMIT 20",
        (cal_id,)
    )
    return jsonify({'ok': True, 'esecuzioni': [dict(r) for r in rows]}), 200


# =============================================================================
# ESCLUSIONI MANUALI
# =============================================================================

@bp.route('/calendari/<int:cal_id>/esclusioni-manuali', methods=['GET'])
@require_role('admin', 'manager')
def get_esclusioni_manuali(cal_id):
    """
    Restituisce le esclusioni manuali del calendario.

    Returns:
        200: { ok, esclusioni: [...] }
    """
    cal = query_one(
        "SELECT id, esclusioni_manuali FROM calendari WHERE id=?", (cal_id,)
    )
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    try:
        esclusioni = json.loads(cal['esclusioni_manuali'] or '[]')
    except (json.JSONDecodeError, TypeError):
        esclusioni = []

    return jsonify({'ok': True, 'esclusioni': esclusioni}), 200


@bp.route('/calendari/<int:cal_id>/esclusioni-manuali', methods=['PUT'])
@require_role('admin', 'manager')
def put_esclusioni_manuali(cal_id):
    """
    Salva le esclusioni manuali del calendario.

    Body JSON:
        esclusioni (list): lista di esclusioni, ciascuna con:
            - tipo: 'giorno' | 'intervallo' | 'giorno_settimana'
            - user_id: int
            - giorno (per tipo=giorno): int
            - giorno_da, giorno_a (per tipo=intervallo): int
            - giorni_settimana (per tipo=giorno_settimana): list[int] (0=lun..6=dom)
            - motivo (opzionale): str

    Returns:
        200: { ok }
        400/404: errore
    """
    cal = ottieni_calendario_aperto(cal_id, "id, stato, tipo")
    if cal.get('tipo') == 'effettivo':
        return jsonify({'ok': False, 'errore': 'Esclusioni non modificabili su calendario effettivo.'}), 400

    dati = request.get_json(silent=True) or {}
    esclusioni = dati.get('esclusioni', [])

    if not isinstance(esclusioni, list):
        return jsonify({'ok': False, 'errore': 'esclusioni deve essere una lista.'}), 400

    # Validazione formato
    me = get_current_user()
    tipi_validi = {'giorno', 'intervallo', 'giorno_settimana'}
    for esc in esclusioni:
        if not isinstance(esc, dict):
            return jsonify({'ok': False, 'errore': 'Ogni esclusione deve essere un oggetto.'}), 400
        tipo = esc.get('tipo')
        if tipo not in tipi_validi:
            return jsonify({'ok': False, 'errore': f'Tipo esclusione non valido: {tipo}'}), 400
        uid = esc.get('user_id')
        if uid is None:
            return jsonify({'ok': False, 'errore': 'user_id obbligatorio.'}), 400
        # Manager non-admin: puo' escludere solo utenti accessibili
        if me['role'] != 'admin' and not manager_puo_utente(me['id'], uid):
            return jsonify({'ok': False, 'errore': f'Utente {uid} non accessibile.'}), 403

    execute_write(
        "UPDATE calendari SET esclusioni_manuali=? WHERE id=?",
        (json.dumps(esclusioni, ensure_ascii=False), cal_id)
    )

    return jsonify({'ok': True}), 200


# =============================================================================
# CELLE BLOCCATE
# =============================================================================

@bp.route('/calendari/<int:cal_id>/celle-bloccate', methods=['GET'])
@require_role('admin', 'manager')
def get_celle_bloccate(cal_id):
    """
    Restituisce le celle bloccate del calendario.

    Returns:
        200: { ok, celle: [...] }
    """
    cal = query_one(
        "SELECT id, celle_bloccate FROM calendari WHERE id=?", (cal_id,)
    )
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    try:
        celle = json.loads(cal['celle_bloccate'] or '[]')
    except (json.JSONDecodeError, TypeError):
        celle = []

    return jsonify({'ok': True, 'celle': celle}), 200


@bp.route('/calendari/<int:cal_id>/celle-bloccate', methods=['PUT'])
@require_role('admin', 'manager')
def put_celle_bloccate(cal_id):
    """
    Salva le celle bloccate del calendario.

    Body JSON:
        celle (list): lista di {turno_id: int, giorno: int}

    Returns:
        200: { ok }
        400/404: errore
    """
    cal = ottieni_calendario_aperto(cal_id, "id, stato, tipo")
    if cal.get('tipo') == 'effettivo':
        return jsonify({'ok': False, 'errore': 'Celle bloccate non modificabili su calendario effettivo.'}), 400

    dati = request.get_json(silent=True) or {}
    celle = dati.get('celle', [])

    if not isinstance(celle, list):
        return jsonify({'ok': False, 'errore': 'celle deve essere una lista.'}), 400

    me = get_current_user()
    for c in celle:
        if not isinstance(c, dict) or 'turno_id' not in c or 'giorno' not in c:
            return jsonify({'ok': False, 'errore': 'Ogni cella deve avere turno_id e giorno.'}), 400
        # Manager non-admin: puo' bloccare solo turni accessibili
        if me['role'] != 'admin' and not manager_puo_turno(me['id'], c['turno_id']):
            return jsonify({'ok': False, 'errore': f'Turno {c["turno_id"]} non accessibile.'}), 403

    execute_write(
        "UPDATE calendari SET celle_bloccate=? WHERE id=?",
        (json.dumps(celle, ensure_ascii=False), cal_id)
    )

    return jsonify({'ok': True}), 200


# =============================================================================
# REGOLE SNAPSHOT (per-calendario)
# =============================================================================

@bp.route('/calendari/<int:cal_id>/regole-snapshot', methods=['PUT'])
@require_role('admin', 'manager')
def aggiorna_regole_snapshot(cal_id):
    """
    Aggiorna lo snapshot regole conflitto di un calendario.
    Il manager puo' modificare le regole del proprio calendario
    senza toccare la configurazione globale.
    Feature: regole snapshot editabili per calendario
    """
    cal = ottieni_calendario_aperto(cal_id)

    dati = request.get_json(silent=True) or {}
    regole = dati.get('regole', [])

    # Validazione minima: ogni regola deve avere almeno id e nome
    for r in regole:
        if not isinstance(r, dict):
            return jsonify({
                'ok': False, 'errore': 'Formato regole non valido.'
            }), 400

    execute_write(
        "UPDATE calendari SET regole_snapshot=? WHERE id=?",
        (json.dumps(regole, ensure_ascii=False), cal_id)
    )

    return jsonify({'ok': True, 'regole': regole}), 200


@bp.route('/calendari/<int:cal_id>/config-snapshot', methods=['PUT'])
@require_role('admin', 'manager')
def aggiorna_config_snapshot(cal_id):
    """
    Aggiorna il config_snapshot (vincoli, accesso, esclusioni, ecc.)
    di un calendario. Il manager puo' modificare i vincoli del
    proprio calendario senza toccare la configurazione globale.
    Feature: config snapshot editabile per calendario
    """
    cal = ottieni_calendario_aperto(cal_id)

    dati = request.get_json(silent=True) or {}
    config = dati.get('config', {})

    if not isinstance(config, dict):
        return jsonify({
            'ok': False, 'errore': 'Formato config non valido.'
        }), 400

    execute_write(
        "UPDATE calendari SET config_snapshot=? WHERE id=?",
        (json.dumps(config, ensure_ascii=False), cal_id)
    )

    return jsonify({'ok': True, 'config': config}), 200


@bp.route('/calendari/<int:cal_id>/appearance-snapshot', methods=['PUT'])
@require_role('admin', 'manager')
def aggiorna_appearance_snapshot(cal_id):
    """
    Aggiorna l'appearance_snapshot di un calendario.
    Permette al manager di personalizzare l'aspetto della griglia
    (colori festivi, superfestivi, bordi) senza creare un nuovo calendario.
    Feature: appearance snapshot editabile per calendario
    """
    cal = ottieni_calendario_aperto(cal_id)

    dati = request.get_json(silent=True) or {}
    appearance = dati.get('appearance', {})

    if not isinstance(appearance, dict):
        return jsonify({'ok': False, 'errore': 'Formato appearance non valido.'}), 400

    from app.services.config_snapshot import APPEARANCE_DEFAULT
    merged = {**APPEARANCE_DEFAULT, **appearance}

    execute_write(
        "UPDATE calendari SET appearance_snapshot=? WHERE id=?",
        (json.dumps(merged, ensure_ascii=False), cal_id)
    )

    return jsonify({'ok': True, 'appearance': merged}), 200


# =============================================================================
# OPTIMIZER
# =============================================================================

@bp.route('/calendari/<int:cal_id>/ottimizza', methods=['POST'])
@require_role('admin', 'manager')
def lancia_optimizer(cal_id):
    """
    Esegue l'ottimizzazione swap-based per bilanciare le assegnazioni.

    Body JSON:
        preset_id (int): ID del preset da preset_ottimizzazione
        max_iterazioni (int): max iterazioni (default 1000)
        preview (bool): se true, non scrive su DB (default false)
        temperatura_iniziale (float): temperatura SA (0.0 = HC puro, >0 = SA)
        raffreddamento (float): fattore cooling SA (default 0.995)
        temperatura_minima (float): soglia sotto cui T→0 (default 0.0001)

    Returns:
        200: { ok, swap_count, costo_iniziale, costo_finale, delta_pct, durata_ms }
    """
    from app.services.optimizer import esegui_ottimizzazione

    cal = ottieni_calendario_aperto(cal_id, "id, stato, tipo")
    if cal.get('tipo') == 'effettivo':
        return jsonify({'ok': False, 'errore': 'Ottimizzazione non disponibile su calendario effettivo.'}), 400

    # NB: regole_snapshot e config_snapshot NON vengono rigenerati —
    # restano quelli del calendario (editabili dal manager nella modale solver)

    dati = request.get_json(silent=True) or {}
    me = get_current_user()

    # Accesso manager
    turni_accessibili = None
    utenti_accessibili = None
    if me['role'] != 'admin':
        _snap = carica_config_snapshot(cal_id)
        all_turni = query_all(
            "SELECT local_id FROM calendario_turni WHERE calendario_id=?",
            (cal_id,)
        )
        if _snap:
            turni_accessibili = {
                int(t['local_id']) for t in all_turni
                if snap_manager_puo_turno(_snap, me['id'], int(t['local_id']))
            }
        else:
            turni_accessibili = {
                int(t['local_id']) for t in all_turni
                if manager_puo_turno(me['id'], int(t['local_id']))
            }
        all_utenti = query_all("SELECT id FROM users WHERE is_active=1")
        if _snap:
            utenti_accessibili = {
                u['id'] for u in all_utenti
                if snap_manager_puo_utente(_snap, me['id'], u['id'])
            }
        else:
            utenti_accessibili = {
                u['id'] for u in all_utenti
                if manager_puo_utente(me['id'], u['id'])
            }

    turni_ids = dati.get('turni_ids')  # lista di local_id selezionati (opzionale)

    risultato = esegui_ottimizzazione(
        calendario_id=cal_id,
        user_id_chiamante=me['id'],
        preset_id=dati.get('preset_id'),
        max_iterazioni=dati.get('max_iterazioni', 1000),
        preview=dati.get('preview', False),
        turni_accessibili=turni_accessibili,
        utenti_accessibili=utenti_accessibili,
        temperatura_iniziale=float(dati.get('temperatura_iniziale', 0.0)),
        raffreddamento=float(dati.get('raffreddamento', 0.995)),
        temperatura_minima=float(dati.get('temperatura_minima', 0.0001)),
        filtro_turni_ids=turni_ids,
    )

    # Broadcast via WebSocket se non preview e swap effettuati
    if not dati.get('preview', False) and risultato.get('swap_count', 0) > 0:
        from app.services.websocket import broadcast_solver
        broadcast_solver(cal_id, {
            'tipo': 'optimizer',
            'swap_count': risultato.get('swap_count', 0),
            'delta_pct': risultato.get('delta_pct', 0),
        }, me['id'])

    return jsonify(risultato), 200


# =============================================================================
# CONTEGGI CONTEXT MENU (configurazione conteggi visibili)
# =============================================================================

@bp.route('/conteggi-config', methods=['GET'])
@require_role('admin', 'manager')
def get_conteggi_config():
    """Restituisce la configurazione dei conteggi context menu."""
    row = query_one(
        "SELECT valore FROM config WHERE chiave = 'conteggi_context'"
    )
    conteggi = json.loads(row['valore']) if row else []
    return jsonify({'ok': True, 'conteggi': conteggi}), 200


@bp.route('/conteggi-config', methods=['PUT'])
@require_role('admin', 'manager')
def salva_conteggi_config():
    """Salva la configurazione dei conteggi context menu."""
    dati = request.get_json(silent=True) or {}
    conteggi = dati.get('conteggi', [])
    execute_write(
        "INSERT INTO config (chiave, valore, descrizione) VALUES (?,?,?) "
        "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore",
        ('conteggi_context', json.dumps(conteggi),
         'Conteggi visibili nel context menu lavoratore (JSON)')
    )
    return jsonify({'ok': True, 'messaggio': 'Conteggi aggiornati.'}), 200


# ---------------------------------------------------------------------------
# Posti Fissi — CRUD + applicazione
# ---------------------------------------------------------------------------

@bp.route('/posti-fissi/<int:preset_id>', methods=['GET'])
@require_role('admin', 'manager')
def get_posti_fissi(preset_id):
    """Lista posti fissi per un preset, filtrata per manager corrente."""
    me = get_current_user()
    rows = query_all(
        """SELECT pf.*, pt.sigla AS turno_sigla, pt.nome AS turno_nome
           FROM posti_fissi pf
           JOIN preset_turni pt ON pf.preset_turno_id = pt.id
           WHERE pf.preset_id = ? AND pf.manager_id = ?
           ORDER BY pf.giorno_settimana, pt.sigla""",
        (preset_id, me['id'])
    )
    result = []
    for r in rows:
        utenti = query_all(
            """SELECT pfu.user_id, pfu.ordine, u.sigla
               FROM posti_fissi_utenti pfu
               JOIN users u ON pfu.user_id = u.id
               WHERE pfu.posto_fisso_id = ?
               ORDER BY pfu.ordine""",
            (r['id'],)
        )
        result.append({
            **dict(r),
            'utenti': [dict(u) for u in utenti],
        })
    return jsonify({'ok': True, 'posti_fissi': result}), 200


@bp.route('/posti-fissi/<int:preset_id>', methods=['POST'])
@require_role('admin', 'manager')
def crea_posto_fisso(preset_id):
    """Crea un posto fisso. Body: { preset_turno_id, giorno_settimana, nome?, utenti: [user_id,...] }"""
    dati = request.get_json(silent=True) or {}
    pt_id = int(dati['preset_turno_id']) if dati.get('preset_turno_id') is not None else None
    giorno_sett = int(dati['giorno_settimana']) if dati.get('giorno_settimana') is not None else None
    nome = dati.get('nome', '')
    utenti_ids = dati.get('utenti', [])
    me = get_current_user()

    if pt_id is None or giorno_sett is None:
        return jsonify({'ok': False, 'errore': 'preset_turno_id e giorno_settimana obbligatori.'}), 400

    # Verifica che il turno appartenga al preset
    pt = query_one(
        """SELECT pt.id FROM preset_turni pt
           JOIN gruppi g ON pt.gruppo_id = g.id
           JOIN sovragruppi sg ON g.sovragruppo_id = sg.id
           WHERE pt.id = ? AND sg.preset_id = ?""",
        (pt_id, preset_id)
    )
    if not pt:
        return jsonify({'ok': False, 'errore': 'Turno non appartenente al preset.'}), 400

    # Verifica accesso turno per manager non-admin
    if me['role'] != 'admin' and not manager_puo_turno(me['id'], pt_id):
        return jsonify({'ok': False, 'errore': 'Non hai accesso a questo turno.'}), 403

    try:
        execute_write(
            """INSERT INTO posti_fissi (preset_id, manager_id, nome, preset_turno_id, giorno_settimana, created_by)
               VALUES (?,?,?,?,?,?)""",
            (preset_id, me['id'], nome, pt_id, giorno_sett, me['id'])
        )
    except Exception as e:
        if 'UNIQUE' in str(e):
            return jsonify({'ok': False, 'errore': 'Posto fisso già esistente per questo turno/giorno.'}), 409
        raise

    pf = query_one(
        "SELECT id FROM posti_fissi WHERE preset_id=? AND preset_turno_id=? AND giorno_settimana=? AND manager_id=?",
        (preset_id, pt_id, giorno_sett, me['id'])
    )

    # Inserisci utenti
    for i, uid in enumerate(utenti_ids):
        execute_write(
            "INSERT OR IGNORE INTO posti_fissi_utenti (posto_fisso_id, user_id, ordine) VALUES (?,?,?)",
            (pf['id'], uid, i)
        )

    return jsonify({'ok': True, 'id': pf['id']}), 201


@bp.route('/posti-fissi/item/<int:pf_id>', methods=['PUT'])
@require_role('admin', 'manager')
def aggiorna_posto_fisso(pf_id):
    """Aggiorna un posto fisso. Body: { nome?, is_active?, utenti?: [user_id,...] }"""
    dati = request.get_json(silent=True) or {}

    me = get_current_user()
    pf = query_one("SELECT * FROM posti_fissi WHERE id=?", (pf_id,))
    if not pf:
        return jsonify({'ok': False, 'errore': 'Posto fisso non trovato.'}), 404
    if pf['manager_id'] != me['id'] and me['role'] != 'admin':
        return jsonify({'ok': False, 'errore': 'Non hai accesso a questo posto fisso.'}), 403

    if 'nome' in dati:
        execute_write("UPDATE posti_fissi SET nome=? WHERE id=?", (dati['nome'], pf_id))
    if 'is_active' in dati:
        execute_write("UPDATE posti_fissi SET is_active=? WHERE id=?", (int(dati['is_active']), pf_id))
    if 'preset_turno_id' in dati:
        execute_write("UPDATE posti_fissi SET preset_turno_id=? WHERE id=?", (dati['preset_turno_id'], pf_id))
    if 'giorno_settimana' in dati:
        execute_write("UPDATE posti_fissi SET giorno_settimana=? WHERE id=?", (int(dati['giorno_settimana']), pf_id))

    if 'utenti' in dati:
        execute_write("DELETE FROM posti_fissi_utenti WHERE posto_fisso_id=?", (pf_id,))
        for i, uid in enumerate(dati['utenti']):
            execute_write(
                "INSERT INTO posti_fissi_utenti (posto_fisso_id, user_id, ordine) VALUES (?,?,?)",
                (pf_id, uid, i)
            )

    return jsonify({'ok': True}), 200


@bp.route('/posti-fissi/item/<int:pf_id>', methods=['DELETE'])
@require_role('admin', 'manager')
def elimina_posto_fisso(pf_id):
    """Elimina un posto fisso."""
    me = get_current_user()
    pf = query_one("SELECT * FROM posti_fissi WHERE id=?", (pf_id,))
    if not pf:
        return jsonify({'ok': False, 'errore': 'Posto fisso non trovato.'}), 404
    if pf['manager_id'] != me['id'] and me['role'] != 'admin':
        return jsonify({'ok': False, 'errore': 'Non hai accesso a questo posto fisso.'}), 403
    execute_write("DELETE FROM posti_fissi WHERE id=?", (pf_id,))
    return jsonify({'ok': True}), 200


@bp.route('/calendari/<int:cal_id>/azzera', methods=['POST'])
@require_role('admin', 'manager')
def azzera_assegnazioni(cal_id):
    """Azzera assegnazioni (annullabile). Body: { turni_ids?: [int] } — se omesso azzera tutto."""
    cal = ottieni_calendario_aperto(cal_id, "id, mese, anno, stato, tipo")
    if cal.get('tipo') == 'effettivo':
        return jsonify({'ok': False, 'errore': 'Azzera non disponibile su calendario effettivo.'}), 400

    me = get_current_user()
    dati = request.get_json(silent=True) or {}
    turni_ids = dati.get('turni_ids')  # None = tutti

    # Verifica accesso turni per manager non-admin
    if me['role'] != 'admin' and turni_ids:
        # Mappa calendario_turni.id → local_id (preset_turno_id)
        ct_rows = query_all(
            "SELECT id, local_id FROM calendario_turni WHERE calendario_id=?",
            (cal_id,)
        )
        ct_to_local = {r['id']: r['local_id'] for r in ct_rows}
        config_snap = carica_config_snapshot(cal_id)
        for tid in turni_ids:
            local = ct_to_local.get(tid)
            if local is None:
                continue
            if config_snap:
                ok = snap_manager_puo_turno(config_snap, me['id'], local)
            else:
                ok = manager_puo_turno(me['id'], local)
            if not ok:
                return jsonify({'ok': False, 'errore': 'Non hai accesso a uno o più turni selezionati.'}), 403

    # Seleziona assegnazioni da azzerare (solo quelle con user_id assegnato)
    if turni_ids:
        placeholders = ','.join('?' * len(turni_ids))
        rows = query_all(
            f"""SELECT * FROM assegnazioni_turni
                WHERE calendario_id=? AND user_id IS NOT NULL
                AND turno_id IN ({placeholders})""",
            [cal_id] + turni_ids
        )
    else:
        rows = query_all(
            "SELECT * FROM assegnazioni_turni WHERE calendario_id=? AND user_id IS NOT NULL",
            (cal_id,)
        )

    if not rows:
        return jsonify({'ok': True, 'azzerate': 0, 'messaggio': 'Nessuna assegnazione da azzerare.'}), 200

    # History: salva stato precedente
    dati_prec = []
    dati_nuovi = []
    for r in rows:
        dati_prec.append({
            'tabella': 'assegnazioni_turni',
            'record_id': r['id'],
            'dati': dict(r),
        })
        # Azzera: user_id=NULL, conflitto=free, conflitti=[]
        execute_write(
            """UPDATE assegnazioni_turni
               SET user_id=NULL, forza_inserimento=0,
                   conflitto='free', conflitti='[]',
                   updated_at=datetime('now'), updated_by=?
               WHERE id=?""",
            (me['id'], r['id'])
        )
        nuova = query_one("SELECT * FROM assegnazioni_turni WHERE id=?", (r['id'],))
        dati_nuovi.append({
            'tabella': 'assegnazioni_turni',
            'record_id': nuova['id'],
            'dati': dict(nuova),
        })

    aggiungi_step(cal_id, 'azzera', 0, dati_prec, dati_nuovi, me['id'])
    broadcast_solver(cal_id, {'celle_riempite': 0, 'turni_operati': 0, 'saltati': 0}, me['id'])

    return jsonify({
        'ok': True,
        'azzerate': len(rows),
        'messaggio': f'{len(rows)} assegnazioni azzerate.'
    }), 200


@bp.route('/calendari/<int:cal_id>/applica-posti-fissi', methods=['POST'])
@require_role('admin', 'manager')
def applica_posti_fissi(cal_id):
    """
    Applica i posti fissi al calendario.
    Body: { sovrascrivi: false, posti_fissi_ids: null|[ids] }
    """
    import datetime as dt

    dati = request.get_json(silent=True) or {}
    sovrascrivi = dati.get('sovrascrivi', False)
    ignora_festivi = dati.get('ignora_festivi', False)
    ignora_superfestivi = dati.get('ignora_superfestivi', False)
    rispetta_desiderata = dati.get('rispetta_desiderata', False)
    filtro_ids = dati.get('posti_fissi_ids')
    me = get_current_user()

    cal = ottieni_calendario_aperto(cal_id, "*")
    if cal.get('tipo') == 'effettivo':
        return jsonify({'ok': False, 'errore': 'Posti fissi non applicabili su calendario effettivo.'}), 400

    preset_id = cal['preset_id']
    anno = cal['anno']
    mese = cal['mese']

    # Carica posti fissi attivi per il preset (solo del manager corrente)
    if filtro_ids:
        placeholders = ','.join('?' * len(filtro_ids))
        posti = query_all(
            f"""SELECT pf.* FROM posti_fissi pf
                WHERE pf.preset_id=? AND pf.manager_id=? AND pf.is_active=1
                AND pf.id IN ({placeholders})""",
            [preset_id, me['id']] + filtro_ids
        )
    else:
        posti = query_all(
            "SELECT * FROM posti_fissi WHERE preset_id=? AND manager_id=? AND is_active=1",
            (preset_id, me['id'])
        )

    if not posti:
        return jsonify({'ok': True, 'inseriti': 0, 'saltati': 0, 'non_mappati': 0, 'dettaglio': []}), 200

    # Mappa preset_turno_id → calendario_turni.id
    ct_rows = query_all(
        "SELECT id, local_id FROM calendario_turni WHERE calendario_id=?",
        (cal_id,)
    )
    ct_map = {str(r['local_id']): r['id'] for r in ct_rows}

    # Calcola i giorni del mese per ogni giorno della settimana
    import calendar
    primo_giorno = dt.date(anno, mese, 1)
    n_giorni = calendar.monthrange(anno, mese)[1]
    giorni_per_weekday = {}  # weekday → [giorno_numero, ...]
    for g in range(1, n_giorni + 1):
        wd = dt.date(anno, mese, g).weekday()
        giorni_per_weekday.setdefault(wd, []).append(g)

    # Giorni festivi/superfestivi
    giorni_tipo = {}
    if ignora_festivi or ignora_superfestivi:
        gc_rows = query_all(
            "SELECT giorno, tipo FROM giorni_calendario WHERE calendario_id=?",
            (cal_id,)
        )
        giorni_tipo = {r['giorno']: r['tipo'] for r in gc_rows}

    # Working desiderata (per rispetta_desiderata)
    wd_map = {}  # (user_id, giorno) → {req_tipo, req_flag_nome}
    if rispetta_desiderata:
        congelati = cal.get('desiderata_congelati', 0)
        tab = 'working_desiderata' if congelati else 'desiderata'
        wd_rows = query_all(
            f"""SELECT d.user_id, d.giorno, tr.tipo AS req_tipo,
                       ft.nome AS req_flag_nome
                FROM {tab} d
                LEFT JOIN tipi_richiesta tr ON d.tipo_richiesta_id = tr.id
                LEFT JOIN flag_turno ft ON tr.flag_id = ft.id
                WHERE d.calendario_id = ?""",
            (cal_id,)
        )
        for r in wd_rows:
            wd_map[(r['user_id'], r['giorno'])] = {
                'req_tipo': r.get('req_tipo'),
                'req_flag_nome': r.get('req_flag_nome'),
            }

    # Flag per turno calendario (per match desiderata working)
    turno_flag = {}
    if rispetta_desiderata:
        tf_rows = query_all(
            "SELECT id, flag_nome FROM calendario_turni WHERE calendario_id=?",
            (cal_id,)
        )
        turno_flag = {r['id']: r.get('flag_nome', '') for r in tf_rows}

    # Gerarchia dei flag per il confronto desiderata ↔ fascia del turno.
    mappa_flag_wd = carica_mappa_flag() if rispetta_desiderata else {}

    inseriti = 0
    saltati = 0
    non_mappati = 0
    dettaglio = []
    dati_prec_history = []
    dati_nuovi_history = []

    for pf in posti:
        # Mappa preset_turno_id → calendario_turno_id
        ct_id = ct_map.get(str(pf['preset_turno_id']))
        if not ct_id:
            non_mappati += 1
            continue

        # Carica utenti del posto fisso
        utenti_pf = query_all(
            "SELECT user_id FROM posti_fissi_utenti WHERE posto_fisso_id=? ORDER BY ordine",
            (pf['id'],)
        )
        if not utenti_pf:
            continue
        user_ids = [u['user_id'] for u in utenti_pf]

        # Giorni target nel mese
        target_days = giorni_per_weekday.get(pf['giorno_settimana'], [])

        for i, giorno in enumerate(target_days):
            # Salta festivi/superfestivi se richiesto
            tipo_g = giorni_tipo.get(giorno, 'normale')
            if ignora_festivi and tipo_g == 'festivo':
                saltati += 1
                dettaglio.append({
                    'turno_id': ct_id, 'giorno': giorno,
                    'user_id': None, 'stato': 'saltato_festivo',
                })
                continue
            if ignora_superfestivi and tipo_g == 'superfestivo':
                saltati += 1
                dettaglio.append({
                    'turno_id': ct_id, 'giorno': giorno,
                    'user_id': None, 'stato': 'saltato_superfestivo',
                })
                continue

            uid = user_ids[i % len(user_ids)]  # round-robin

            # Rispetta desiderata: salta se assenza o flag mismatch
            if rispetta_desiderata:
                wd = wd_map.get((uid, giorno))
                if wd:
                    if wd['req_tipo'] == 'assenza':
                        # Cerca un altro utente che non abbia assenza
                        trovato = False
                        for j in range(len(user_ids)):
                            alt_uid = user_ids[(i + j) % len(user_ids)]
                            wd_alt = wd_map.get((alt_uid, giorno))
                            if not wd_alt or wd_alt['req_tipo'] != 'assenza':
                                uid = alt_uid
                                trovato = True
                                break
                        if not trovato:
                            saltati += 1
                            dettaglio.append({
                                'turno_id': ct_id, 'giorno': giorno,
                                'user_id': uid, 'stato': 'saltato_desiderata',
                            })
                            continue
                    elif wd['req_tipo'] == 'lavorativo' and wd.get('req_flag_nome'):
                        # L'utente vuole lavorare in una fascia specifica.
                        # La richiesta puo' indicare un concetto ("la notte")
                        # e il turno una sua fascia ("notte"): il confronto
                        # e' di discendenza, non di uguaglianza fra nomi.
                        fascia_turno = turno_flag.get(ct_id, '')
                        if fascia_turno and not discende_da_nome(
                            fascia_turno, wd['req_flag_nome'], mappa_flag_wd
                        ):
                            # Cerca un altro utente compatibile
                            trovato = False
                            for j in range(len(user_ids)):
                                alt_uid = user_ids[(i + j) % len(user_ids)]
                                wd_alt = wd_map.get((alt_uid, giorno))
                                if not wd_alt:
                                    uid = alt_uid
                                    trovato = True
                                    break
                                if wd_alt['req_tipo'] == 'assenza':
                                    continue
                                if wd_alt['req_tipo'] == 'lavorativo':
                                    alt_flag = wd_alt.get('req_flag_nome', '')
                                    if not alt_flag or discende_da_nome(
                                        fascia_turno, alt_flag, mappa_flag_wd
                                    ):
                                        uid = alt_uid
                                        trovato = True
                                        break
                            if not trovato:
                                saltati += 1
                                dettaglio.append({
                                    'turno_id': ct_id, 'giorno': giorno,
                                    'user_id': uid, 'stato': 'saltato_desiderata',
                                })
                                continue

            # Controlla se la cella ha già un'assegnazione
            esistente = query_one(
                "SELECT * FROM assegnazioni_turni WHERE calendario_id=? AND turno_id=? AND giorno=?",
                (cal_id, ct_id, giorno)
            )
            if esistente and esistente['user_id'] is not None and not sovrascrivi:
                saltati += 1
                dettaglio.append({
                    'turno_id': ct_id, 'giorno': giorno,
                    'user_id': uid, 'stato': 'saltato',
                })
                continue

            # Salva stato precedente per history
            dati_prec_history.append({
                'tabella': 'assegnazioni_turni',
                'record_id': esistente['id'] if esistente else None,
                'dati': dict(esistente) if esistente else None,
            })

            # Validazione conflitti
            try:
                val = valida_assegnazione(cal_id, ct_id, uid, giorno, forza_inserimento=False)
                conflitti_json = json.dumps(val.get('conflitti', []))
                conflitto_legacy = 'free' if not val['conflitti'] else 'forced'
            except Exception:
                conflitti_json = '[]'
                conflitto_legacy = 'free'

            execute_write(
                """INSERT INTO assegnazioni_turni
                    (calendario_id, turno_id, giorno, user_id, forza_inserimento,
                     conflitto, conflitti, updated_at, updated_by)
                VALUES (?,?,?,?,0,?,?,datetime('now'),?)
                ON CONFLICT(calendario_id, turno_id, giorno) DO UPDATE SET
                    user_id = excluded.user_id,
                    forza_inserimento = excluded.forza_inserimento,
                    conflitto = excluded.conflitto,
                    conflitti = excluded.conflitti,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by""",
                (cal_id, ct_id, giorno, uid, conflitto_legacy, conflitti_json, me['id'])
            )

            nuova = query_one(
                "SELECT * FROM assegnazioni_turni WHERE calendario_id=? AND turno_id=? AND giorno=?",
                (cal_id, ct_id, giorno)
            )
            dati_nuovi_history.append({
                'tabella': 'assegnazioni_turni',
                'record_id': nuova['id'],
                'dati': dict(nuova),
            })

            inseriti += 1
            dettaglio.append({
                'turno_id': ct_id, 'giorno': giorno,
                'user_id': uid, 'stato': 'inserito',
            })

    # History: singolo step undoable
    if dati_prec_history:
        aggiungi_step(
            cal_id, 'posti_fissi', 0,
            dati_prec_history, dati_nuovi_history,
            me['id']
        )

    # Broadcast via WebSocket
    broadcast_solver(cal_id, {
        'celle_riempite': inseriti,
        'turni_operati': 0,
        'saltati': saltati,
    }, me['id'])

    return jsonify({
        'ok': True,
        'inseriti': inseriti,
        'saltati': saltati,
        'non_mappati': non_mappati,
    }), 200
