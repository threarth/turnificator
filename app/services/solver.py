"""
app/services/solver.py — solver greedy per auto-riempimento turni (v2).

Architettura a 3 fasi:
  Fase 1 — Contesto: costruzione mappe, esclusioni, coefficienti
  Fase 2 — Filtro hard: per ogni cella, esclude candidati non validi
  Fase 3 — Assegnazione: round-robin WD matching → equita' proporzionale

Principi:
  - Desiderata assenza = esclusione HARD (mai assegnato)
  - Esclusioni manuali = esclusione HARD
  - Celle bloccate = non toccate
  - Equita' proporzionale: quote basate su coefficiente disponibilita'
  - Working desiderata: round-robin tra chi ha WD matching per quel giorno
"""

import json
import random
import time

DEBUG_ACTIVE = False

from app.db import query_one, query_all, execute_write
from app.services.validatori import valida_assegnazione, _flag_matcha
from app.services.fasce_orarie import carica_mappa_flag
from app.services.history import aggiungi_step
from app.services.config_snapshot import (
    carica_config_snapshot,
    snap_vincoli_globali, snap_vincoli_utente,
    snap_vincoli_solver, snap_vincoli_solver_utente,
    snap_esclusioni_turno, snap_giorni_esclusi,
    snap_flag_map,
)
from app.services.solver_common import (
    espandi_esclusioni_manuali, espandi_celle_bloccate,
    calcola_coefficienti, calcola_quote,
    calcola_costo_totale,
    arricchisci_giorni_con_dow,
)


# ---------------------------------------------------------------------------
# Caricamento vincoli
# ---------------------------------------------------------------------------

def _carica_vincoli_globali():
    """Carica vincoli globali attivi come dict chiave→int."""
    rows = query_all(
        "SELECT chiave, valore FROM vincoli_globali WHERE is_active = 1"
    )
    vincoli = {}
    for r in rows:
        try:
            vincoli[r['chiave']] = int(r['valore'])
        except (ValueError, TypeError):
            vincoli[r['chiave']] = 0
    return vincoli


def _carica_vincoli_utente(user_id):
    """Carica override vincoli per un utente come dict chiave→int."""
    rows = query_all(
        "SELECT chiave, valore FROM vincoli_utente WHERE user_id = ?",
        (user_id,)
    )
    override = {}
    for r in rows:
        try:
            override[r['chiave']] = int(r['valore'])
        except (ValueError, TypeError):
            override[r['chiave']] = 0
    return override


def _get_vincolo(vincoli_globali, vincoli_utente_cache, user_id, chiave):
    """Restituisce il vincolo effettivo (override utente > globale)."""
    if user_id in vincoli_utente_cache:
        vu = vincoli_utente_cache[user_id]
        if chiave in vu:
            return vu[chiave]
    return vincoli_globali.get(chiave, 0)


def _carica_vincoli_solver():
    """Carica vincoli solver attivi (flag/qualitativo) come lista di dict."""
    rows = query_all(
        "SELECT tipo, ref_id, max_n FROM vincoli_solver WHERE is_active = 1"
    )
    return [dict(r) for r in rows]


def _carica_vincoli_solver_utente_bulk():
    """Carica tutti gli override vincoli solver per-utente.
    Ritorna dict (user_id, tipo, ref_id) → max_n."""
    rows = query_all(
        "SELECT user_id, tipo, ref_id, max_n FROM vincoli_solver_utente"
    )
    cache = {}
    for r in rows:
        cache[(r['user_id'], r['tipo'], r['ref_id'])] = r['max_n']
    return cache


def _get_vincolo_solver(vincoli_solver_list, vs_utente_cache, user_id, tipo, ref_id):
    """Restituisce max_n effettivo per un vincolo solver (override utente > globale).
    Ritorna None se non esiste alcun vincolo (né globale né utente)."""
    chiave_utente = (user_id, tipo, ref_id)
    if chiave_utente in vs_utente_cache:
        return vs_utente_cache[chiave_utente]
    for vs in vincoli_solver_list:
        if vs['tipo'] == tipo and vs['ref_id'] == ref_id:
            return vs['max_n']
    return None


def _get_vincoli_solver_utente_extra(vincoli_solver_list, vs_utente_cache, user_id):
    """Ritorna vincoli solver per-utente che NON hanno un corrispondente globale."""
    global_set = {(vs['tipo'], vs['ref_id']) for vs in vincoli_solver_list}
    extra = []
    for (uid, tipo, ref_id), max_n in vs_utente_cache.items():
        if uid == user_id and (tipo, ref_id) not in global_set:
            extra.append({'tipo': tipo, 'ref_id': ref_id, 'max_n': max_n})
    return extra


def _calcola_antenati_flag(flag_id, flag_map):
    """Risale la gerarchia flag e ritorna il set di ID (incluso se stesso)."""
    antenati = set()
    fid = flag_id
    while fid:
        antenati.add(fid)
        flag_info = flag_map.get(fid)
        fid = flag_info['parent_id'] if flag_info else None
    return antenati


# ---------------------------------------------------------------------------
# Stato lavoratori (running state)
# ---------------------------------------------------------------------------

def _inizializza_stati(calendario_id, giorni_info, turni_info, flag_map,
                       utenti_accessibili=None, escludi_turni_ids=None):
    """
    Costruisce lo stato running di ogni lavoratore attivo
    basato sulle assegnazioni esistenti.
    """
    utenti = query_all(
        "SELECT id, sigla, sovragruppo_id FROM users "
        "WHERE is_active=1 AND escluso_turni=0 AND role IN ('basic','manager','admin') ORDER BY sigla",
        ()
    )

    if utenti_accessibili is not None:
        utenti = [u for u in utenti if u['id'] in utenti_accessibili]

    turno_flag_id = {}
    for t in turni_info:
        turno_flag_id[t['id']] = t.get('flag_id')

    turno_qual_ids = {}
    for t in turni_info:
        tq_raw = t.get('tipi_qualitativi', '[]')
        try:
            tq_list = json.loads(tq_raw) if isinstance(tq_raw, str) else (tq_raw or [])
        except (json.JSONDecodeError, TypeError):
            tq_list = []
        turno_qual_ids[t['id']] = {item['id'] for item in tq_list if isinstance(item, dict) and 'id' in item}

    giorno_tipo = {}
    for g in giorni_info:
        giorno_tipo[g['giorno']] = g.get('tipo', 'normale')

    ass_rows = query_all(
        "SELECT turno_id, giorno, user_id FROM assegnazioni_turni "
        "WHERE calendario_id = ? AND user_id IS NOT NULL",
        (calendario_id,)
    )

    turno_ore = {}
    turno_peso = {}
    for t in turni_info:
        turno_ore[t['id']] = t.get('ore_turno') or 0
        turno_peso[t['id']] = t.get('peso_turno') or 1

    stati = {}
    for u in utenti:
        stati[u['id']] = {
            'sigla': u['sigla'],
            # Serve alla preferenza per la propria struttura.
            'sovragruppo_id': u.get('sovragruppo_id'),
            'turni_per_giorno': {},
            'giorni_lavorati': set(),
            'ore_mese': 0.0,
            'festivi_mese': 0,
            'totale_turni': 0,
            'peso_totale': 0,
            'peso_per_flag': {},
            'conteggio_flag': {},
            'conteggio_qualitativo': {},
        }

    for a in ass_rows:
        if escludi_turni_ids and a['turno_id'] in escludi_turni_ids:
            continue
        uid = a['user_id']
        if uid not in stati:
            continue
        s = stati[uid]
        g = a['giorno']
        s['turni_per_giorno'][g] = s['turni_per_giorno'].get(g, 0) + 1
        s['giorni_lavorati'].add(g)
        s['totale_turni'] += 1
        s['peso_totale'] += turno_peso.get(a['turno_id'], 1)

        fid = turno_flag_id.get(a['turno_id'])
        if fid:
            p_turno = turno_peso.get(a['turno_id'], 1)
            for anc in _calcola_antenati_flag(fid, flag_map):
                s['conteggio_flag'][anc] = s['conteggio_flag'].get(anc, 0) + 1
                s['peso_per_flag'][anc] = s['peso_per_flag'].get(anc, 0) + p_turno

        for tq_id in turno_qual_ids.get(a['turno_id'], set()):
            s['conteggio_qualitativo'][tq_id] = s['conteggio_qualitativo'].get(tq_id, 0) + 1

        s['ore_mese'] += turno_ore.get(a['turno_id'], 0)

        tipo_g = giorno_tipo.get(g, 'normale')
        if tipo_g in ('festivo', 'superfestivo'):
            s['festivi_mese'] += 1

    return stati, utenti


def _calcola_giorni_consecutivi(stato, giorno):
    """Calcola quanti giorni consecutivi ha lavorato l'utente fino a `giorno` incluso."""
    count = 0
    g = giorno
    while g >= 1 and g in stato['giorni_lavorati']:
        count += 1
        g -= 1
    return count


# ---------------------------------------------------------------------------
# Esclusioni utente (flag-based)
# ---------------------------------------------------------------------------

def _carica_esclusioni_turno(preset_id):
    """
    Esclusioni per turno di un preset, lette dal vivo.

    Serve ai calendari nati prima dello snapshot completo: senza questo, i
    divieti su singoli turni sparivano in silenzio, che e' peggio di non
    averli — l'amministratore li vede configurati e il solver li ignora.

    Args:
        preset_id (int|None): struttura turni del calendario.

    Returns:
        dict: {user_id → [{tipo, target_id, eccezioni}]}, vuoto senza preset.
    """
    if not preset_id:
        return {}

    righe = query_all(
        "SELECT user_id, tipo, target_id, eccezioni "
        "FROM preset_esclusioni_turno_per_utente WHERE preset_id = ?",
        (preset_id,)
    )

    per_utente = {}
    for r in righe:
        per_utente.setdefault(r['user_id'], []).append(dict(r))

    return per_utente


def _vantaggio_struttura(stato, sg_turno, peso):
    """
    Quanto conviene mettere questa persona in questo turno, per struttura.

    Il punteggio di scelta e' un rapporto in cui vince il piu' basso: uno
    sconto avvicina il candidato all'assegnazione. Chi lavora nella propria
    struttura lo riceve; chi non ne ha una non e' ne' favorito ne' penalizzato.

    Con peso zero — il default — la struttura non conta e il solver assegna
    indifferentemente, che e' come si e' sempre comportato.

    Args:
        stato (dict): stato del candidato, con `sovragruppo_id`.
        sg_turno (int|None): struttura del turno da coprire.
        peso (float): quanto vale la preferenza, in turni di vantaggio.

    Returns:
        float: lo sconto da sottrarre al punteggio, 0 se non si applica.
    """
    if not peso or sg_turno is None:
        return 0.0

    return peso if stato.get('sovragruppo_id') == sg_turno else 0.0


def _carica_giorni_esclusi():
    """Carica tutti i giorni esclusi come dict user_id → list di day-of-week."""
    rows = query_all(
        "SELECT id, giorni_esclusi FROM users "
        "WHERE is_active=1 AND giorni_esclusi != '[]'"
    )
    cache = {}
    for r in rows:
        try:
            giorni = json.loads(r['giorni_esclusi'] or '[]')
        except (json.JSONDecodeError, TypeError):
            giorni = []
        if giorni:
            cache[r['id']] = giorni
    return cache


def _espandi_giorni_esclusi(giorni_esclusi_cache, giorni_info, indisponibilita):
    """Espande i giorni esclusi (dow fissi) nella mappa indisponibilita."""
    if not giorni_esclusi_cache:
        return
    for gi in giorni_info:
        dow = gi.get('dow')
        if dow is None:
            continue
        giorno = gi['giorno']
        for uid, giorni in giorni_esclusi_cache.items():
            if dow in giorni:
                indisponibilita.setdefault(giorno, set()).add(uid)


# ---------------------------------------------------------------------------
# Working desiderata bulk
# ---------------------------------------------------------------------------

def _carica_working_desiderata_bulk(calendario_id):
    """Carica tutti i working desiderata come dict (user_id, giorno) → {tipo, flag_nome, flag_id}."""
    rows = query_all(
        """
        SELECT wd.user_id, wd.giorno, tr.tipo AS req_tipo,
               ft.nome AS req_flag_nome, ft.id AS req_flag_id
        FROM working_desiderata wd
        LEFT JOIN tipi_richiesta tr ON wd.tipo_richiesta_id = tr.id
        LEFT JOIN flag_turno ft ON tr.flag_id = ft.id
        WHERE wd.calendario_id = ?
        """,
        (calendario_id,)
    )
    wd_map = {}
    for r in rows:
        wd_map[(r['user_id'], r['giorno'])] = {
            'req_tipo': r['req_tipo'],
            'req_flag_nome': r.get('req_flag_nome'),
            'req_flag_id': r.get('req_flag_id'),
        }
    return wd_map


def _carica_desiderata_originali_bulk(calendario_id):
    """Carica i desiderata originali come dict (user_id, giorno) → {tipo, flag_nome, flag_id}."""
    rows = query_all(
        """
        SELECT d.user_id, d.giorno, tr.tipo AS req_tipo,
               ft.nome AS req_flag_nome, ft.id AS req_flag_id
        FROM desiderata d
        LEFT JOIN tipi_richiesta tr ON d.tipo_richiesta_id = tr.id
        LEFT JOIN flag_turno ft ON tr.flag_id = ft.id
        WHERE d.calendario_id = ?
        """,
        (calendario_id,)
    )
    des_map = {}
    for r in rows:
        des_map[(r['user_id'], r['giorno'])] = {
            'req_tipo': r['req_tipo'],
            'req_flag_nome': r.get('req_flag_nome'),
            'req_flag_id': r.get('req_flag_id'),
        }
    return des_map


# ---------------------------------------------------------------------------
# Costruzione contesto (Fase 1) — separata per riuso in multi-start
# ---------------------------------------------------------------------------

def _costruisci_contesto(calendario_id, solo_vuote=True, solo_indispensabili=False,
                         escludi_regole_ids=None,
                         turni_accessibili=None, utenti_accessibili=None,
                         criteri_ordinamento=None, turni_ids=None,
                         fonte_desiderata='working'):
    """
    Fase 1 del solver: costruisce tutto il contesto necessario per l'assegnazione.
    Caricato UNA SOLA VOLTA, riusabile per N run in multi-start.

    Returns:
        dict con tutte le strutture dati necessarie, oppure dict con 'errore'.
    """
    cal = query_one(
        "SELECT mese, anno, preset_id, esclusioni_manuali, celle_bloccate, "
        "desiderata_congelati, regole_snapshot FROM calendari WHERE id=?",
        (calendario_id,)
    )
    if not cal:
        return {'errore': 'Calendario non trovato.'}

    # Turni
    filtro_priorita = "AND ct.priorita_solver != 'manuale'"
    if solo_indispensabili:
        filtro_priorita = "AND ct.priorita_solver = 'indispensabile'"

    turni_info = query_all(
        f"""
        SELECT ct.id, ct.local_id, ct.sigla, ct.flag_nome, ct.flag_id,
               ct.priorita_solver, ct.peso_priorita_solver, ct.peso_turno, ct.ordine,
               ct.ore_turno, ct.tipi_qualitativi,
               ct.apri_festivi, ct.apri_superfestivi, ct.aperture_straordinarie,
               ct.gruppo_id, ct.sg_id, ct.is_disabled
        FROM calendario_turni ct
        WHERE ct.calendario_id = ? {filtro_priorita}
        ORDER BY ct.ordine
        """,
        (calendario_id,)
    )
    # Escludi turni disattivati (is_disabled=1 o is_hidden=1 → is_disabled=1)
    turni_info = [t for t in turni_info if not t.get('is_disabled', 0)]
    turni_totali = len(turni_info)

    if turni_accessibili is not None:
        turni_info = [t for t in turni_info if int(t['local_id']) in turni_accessibili]

    turni_info_tutti = list(turni_info)

    if turni_ids is not None:
        turni_ids_set = {int(x) for x in turni_ids}
        turni_info = [t for t in turni_info if int(t['local_id']) in turni_ids_set]

    # Giorni
    giorni_info = query_all(
        "SELECT giorno, is_lavorativo, ore_lavorative, tipo "
        "FROM giorni_calendario WHERE calendario_id = ? ORDER BY giorno",
        (calendario_id,)
    )
    arricchisci_giorni_con_dow(giorni_info, cal['mese'], cal['anno'])
    giorno_tipo = {g['giorno']: g.get('tipo', 'normale') for g in giorni_info}

    # Esclusioni manuali e celle bloccate
    indisponibilita_manuali = espandi_esclusioni_manuali(
        cal.get('esclusioni_manuali', '[]'), giorni_info
    )
    celle_bloccate = espandi_celle_bloccate(cal.get('celle_bloccate', '[]'))

    # Assegnazioni esistenti
    ass_esistenti = set()
    if solo_vuote:
        rows = query_all(
            "SELECT turno_id, giorno FROM assegnazioni_turni "
            "WHERE calendario_id = ? AND user_id IS NOT NULL",
            (calendario_id,)
        )
        ass_esistenti = {(r['turno_id'], r['giorno']) for r in rows}

    turni_ids_processati = {t['id'] for t in turni_info}

    # Aperture straordinarie
    turno_aperture = {}
    for t in turni_info:
        ap_raw = t.get('aperture_straordinarie', '[]')
        try:
            ap = json.loads(ap_raw) if isinstance(ap_raw, str) else (ap_raw or [])
        except (json.JSONDecodeError, TypeError):
            ap = []
        turno_aperture[t['id']] = set(ap)

    # Mappa turno_id → flag_nome (per conflict check in-memory)
    turno_flag_nome = {}
    turno_flag_id_map = {}
    for t in turni_info_tutti:
        turno_flag_nome[t['id']] = t.get('flag_nome', '')
        turno_flag_id_map[t['id']] = t.get('flag_id')
    # Includi anche turni non filtrati (servono per le assegnazioni esistenti)
    all_turni = query_all(
        "SELECT id, flag_nome, flag_id FROM calendario_turni WHERE calendario_id=?",
        (calendario_id,)
    )
    for t in all_turni:
        turno_flag_nome.setdefault(t['id'], t.get('flag_nome', ''))
        turno_flag_id_map.setdefault(t['id'], t.get('flag_id'))

    # Costruisci lista celle da riempire
    celle = []
    for t in turni_info:
        for g in giorni_info:
            chiave = (t['id'], g['giorno'])
            if chiave in celle_bloccate:
                continue
            if solo_vuote and chiave in ass_esistenti:
                continue

            tipo_g = g.get('tipo', 'normale')
            if g['giorno'] not in turno_aperture.get(t['id'], set()):
                if tipo_g == 'festivo' and not t.get('apri_festivi'):
                    continue
                if tipo_g == 'superfestivo' and not t.get('apri_superfestivi'):
                    continue

            tq_raw = t.get('tipi_qualitativi', '[]')
            try:
                tq_list = json.loads(tq_raw) if isinstance(tq_raw, str) else (tq_raw or [])
            except (json.JSONDecodeError, TypeError):
                tq_list = []
            tq_ids = {item['id'] for item in tq_list if isinstance(item, dict) and 'id' in item}

            celle.append({
                'turno_id': t['id'],
                'local_id': t['local_id'],
                'gruppo_id': t.get('gruppo_id'),
                'sg_id': t.get('sg_id'),
                'turno_sigla': t['sigla'],
                'giorno': g['giorno'],
                'tipo_giorno': tipo_g,
                'priorita_solver': t['priorita_solver'],
                'peso_priorita_solver': t['peso_priorita_solver'],
                'peso_turno': t.get('peso_turno') or 1,
                'flag_nome': t.get('flag_nome', ''),
                'flag_id': t.get('flag_id'),
                'ore_turno': t.get('ore_turno') or 0,
                'ordine': t['ordine'],
                'tipi_qualitativo_ids': tq_ids,
            })

    # Ordinamento celle
    _criteri = criteri_ordinamento or []

    def sort_key(c):
        prio = 0 if c['priorita_solver'] == 'indispensabile' else 1
        custom = []
        for cr in _criteri:
            if cr.get('tipo') == 'flag':
                custom.append(0 if c.get('flag_nome') == cr.get('flag_nome') else 1)
            elif cr.get('tipo') == 'tipo_giorno':
                valori = cr.get('valori', [])
                custom.append(0 if c.get('tipo_giorno') in valori else 1)
        return (prio, *custom, -c['peso_priorita_solver'], c['giorno'], c['ordine'])
    celle.sort(key=sort_key)

    # Config snapshot o live
    config_snap = carica_config_snapshot(calendario_id)

    if config_snap:
        vincoli_g = snap_vincoli_globali(config_snap)
        flag_map = snap_flag_map(config_snap)
        vincoli_utente_cache = snap_vincoli_utente(config_snap)
        vincoli_solver_list = snap_vincoli_solver(config_snap)
        vs_utente_cache = snap_vincoli_solver_utente(config_snap)
        esclusioni_turno_cache = snap_esclusioni_turno(config_snap)
        giorni_esclusi_cache = snap_giorni_esclusi(config_snap)
    else:
        vincoli_g = _carica_vincoli_globali()
        flag_map = carica_mappa_flag()
        vincoli_utente_cache = {}
        for u_temp in query_all(
            "SELECT id FROM users WHERE is_active=1 AND escluso_turni=0 AND role IN ('basic','manager','admin')"
        ):
            vu = _carica_vincoli_utente(u_temp['id'])
            if vu:
                vincoli_utente_cache[u_temp['id']] = vu
        vincoli_solver_list = _carica_vincoli_solver()
        vs_utente_cache = _carica_vincoli_solver_utente_bulk()
        esclusioni_turno_cache = _carica_esclusioni_turno(cal.get('preset_id'))
        giorni_esclusi_cache = _carica_giorni_esclusi()

    escludi_per_stato = turni_ids_processati if not solo_vuote else None
    stati, utenti = _inizializza_stati(calendario_id, giorni_info, turni_info_tutti, flag_map,
                                       utenti_accessibili=utenti_accessibili,
                                       escludi_turni_ids=escludi_per_stato)

    # Desiderata
    if fonte_desiderata == 'originali':
        wd_map = _carica_desiderata_originali_bulk(calendario_id)
    else:
        wd_map = _carica_working_desiderata_bulk(calendario_id)

    # Indisponibilita' combinata
    indisponibilita = {}
    for g, uids in indisponibilita_manuali.items():
        indisponibilita.setdefault(g, set()).update(uids)
    for (uid, g), wd in wd_map.items():
        if wd.get('req_tipo') == 'assenza':
            indisponibilita.setdefault(g, set()).add(uid)
    # Giorni esclusi (giorno della settimana fisso per utente)
    _espandi_giorni_esclusi(giorni_esclusi_cache, giorni_info, indisponibilita)

    # Coefficienti e quote
    giorni_lavorativi = sum(1 for g in giorni_info if g.get('is_lavorativo'))
    turni_dovuti = giorni_lavorativi
    coefficienti = calcola_coefficienti(
        [u['id'] for u in utenti], giorni_lavorativi, indisponibilita, wd_map
    )

    # Regole conflitto (per validazione in-memory)
    regole_snapshot_raw = cal.get('regole_snapshot', '[]')
    try:
        regole_conflitto = json.loads(regole_snapshot_raw) if regole_snapshot_raw else []
    except (json.JSONDecodeError, TypeError):
        regole_conflitto = []
    if not regole_conflitto:
        from app.services.validatori import _get_regole_attive_db
        regole_conflitto = [dict(r) for r in _get_regole_attive_db()]

    # Assegnazioni esistenti in DB per utente/giorno (per conflitto in-memory)
    # Mappa: (user_id, giorno) → [ { turno_id, flag_nome } ]
    ass_db_rows = query_all(
        "SELECT at.turno_id, at.giorno, at.user_id "
        "FROM assegnazioni_turni at "
        "WHERE at.calendario_id = ? AND at.user_id IS NOT NULL",
        (calendario_id,)
    )
    ass_per_utente_giorno = {}
    for r in ass_db_rows:
        key = (r['user_id'], r['giorno'])
        ass_per_utente_giorno.setdefault(key, []).append({
            'turno_id': r['turno_id'],
            'flag_nome': turno_flag_nome.get(r['turno_id'], ''),
        })

    # Desiderata ref per conflitto in-memory (WD se congelati, originali altrimenti)
    congelati = bool(cal.get('desiderata_congelati'))
    if congelati:
        des_ref_map = _carica_working_desiderata_bulk(calendario_id)
    else:
        des_ref_map = _carica_desiderata_originali_bulk(calendario_id)

    return {
        'cal': cal,
        'celle': celle,
        'celle_bloccate': celle_bloccate,
        'stati': stati,
        'utenti': utenti,
        'turni_info': turni_info,
        'turni_info_tutti': turni_info_tutti,
        'turni_totali': turni_totali,
        'turni_ids_processati': turni_ids_processati,
        'giorni_info': giorni_info,
        'giorno_tipo': giorno_tipo,
        'indisponibilita': indisponibilita,
        'vincoli_g': vincoli_g,
        'vincoli_utente_cache': vincoli_utente_cache,
        'vincoli_solver_list': vincoli_solver_list,
        'vs_utente_cache': vs_utente_cache,
        'esclusioni_turno_cache': esclusioni_turno_cache,
        'flag_map': flag_map,
        'wd_map': wd_map,
        'coefficienti': coefficienti,
        'turni_dovuti': turni_dovuti,
        'regole_conflitto': regole_conflitto,
        'ass_per_utente_giorno': ass_per_utente_giorno,
        'turno_flag_nome': turno_flag_nome,
        'des_ref_map': des_ref_map,
        'solo_vuote': solo_vuote,
    }


# ---------------------------------------------------------------------------
# Validazione conflitti in-memory (no query DB durante il loop)
# ---------------------------------------------------------------------------

def _valida_conflitti_inmem(regole, flag_nome_nuovo, flag_id_nuovo,
                            uid, giorno, ass_utente_giorno, flag_map,
                            des_ref_map, escludi_regole):
    """
    Verifica conflitti per un'assegnazione usando dati in-memory.
    Nel solver TUTTE le regole attive sono bloccanti.
    ass_utente_giorno: dict (user_id, giorno) → [ { turno_id, flag_nome } ]

    Returns:
        bloccato (bool)
    """
    from app.services.validatori import _flag_nome_matcha

    # Filtra regole disattivate nello snapshot (is_active) e quelle escluse a monte
    regole_attive = [
        r for r in regole
        if r.get('is_active', 1) and (not escludi_regole or r.get('id') not in escludi_regole)
    ]

    # Desiderata ref
    des_ref = des_ref_map.get((uid, giorno))
    if des_ref and des_ref.get('req_tipo'):
        req_tipo = des_ref.get('req_tipo')
        for r in regole_attive:
            if r.get('tipo_regola') == 'desiderata_assenza_mismatch' and req_tipo == 'assenza':
                return True
            elif r.get('tipo_regola') == 'desiderata_mismatch':
                if req_tipo == 'lavorativo' and des_ref.get('req_flag_nome') and flag_nome_nuovo:
                    if not _flag_nome_matcha(flag_nome_nuovo, des_ref.get('req_flag_id'), flag_map):
                        return True

    # tipo_vs_tipo offset=0 (stesso giorno)
    ass_oggi = ass_utente_giorno.get((uid, giorno), [])
    regole_0 = [r for r in regole_attive if r.get('tipo_regola') == 'tipo_vs_tipo' and r.get('offset_giorni', 0) == 0]
    for r in regole_0:
        for a in ass_oggi:
            flag_e = a.get('flag_nome')
            if (_flag_nome_matcha(flag_nome_nuovo, r.get('flag_a_id'), flag_map)
                    and _flag_nome_matcha(flag_e, r.get('flag_b_id'), flag_map)):
                return True
            if (_flag_nome_matcha(flag_e, r.get('flag_a_id'), flag_map)
                    and _flag_nome_matcha(flag_nome_nuovo, r.get('flag_b_id'), flag_map)):
                return True

    # tipo_vs_tipo offset=1 (oggi=A, domani=B) — turno nuovo oggi, esistente domani
    regole_1 = [r for r in regole_attive if r.get('tipo_regola') == 'tipo_vs_tipo' and r.get('offset_giorni') == 1]
    ass_domani = ass_utente_giorno.get((uid, giorno + 1), [])
    for r in regole_1:
        for a in ass_domani:
            flag_e = a.get('flag_nome')
            if (_flag_nome_matcha(flag_nome_nuovo, r.get('flag_a_id'), flag_map)
                    and _flag_nome_matcha(flag_e, r.get('flag_b_id'), flag_map)):
                return True

    # Reverse offset=1: ieri=A, oggi(nuovo)=B
    if giorno > 1:
        ass_ieri = ass_utente_giorno.get((uid, giorno - 1), [])
        for r in regole_1:
            for a in ass_ieri:
                flag_ieri = a.get('flag_nome')
                if (_flag_nome_matcha(flag_ieri, r.get('flag_a_id'), flag_map)
                        and _flag_nome_matcha(flag_nome_nuovo, r.get('flag_b_id'), flag_map)):
                    return True

    return False


# ---------------------------------------------------------------------------
# Fase 2+3: Loop assegnazione (puro in-memory, riusabile per multi-start)
# ---------------------------------------------------------------------------

def _esegui_assegnazione(ctx, escludi_regole, top_k=1):
    """
    Esegue le fasi 2 (filtro hard) e 3 (assegnazione) del solver.
    Lavora interamente in-memory: non scrive nel DB, non legge dal DB.
    Tutte le regole attive (non in escludi_regole) sono bloccanti.

    Args:
        ctx: contesto costruito da _costruisci_contesto()
        escludi_regole: set di id regole da escludere
        top_k: randomizzazione candidato

    Returns:
        (assegnazioni_proposte, celle_fallite, indispensabili_scoperti, stati)
    """
    import copy

    celle = ctx['celle']
    stati = copy.deepcopy(ctx['stati'])
    utenti = ctx['utenti']
    giorno_tipo = ctx['giorno_tipo']
    indisponibilita = ctx['indisponibilita']
    vincoli_g = ctx['vincoli_g']

    # Quanto vale lavorare nella propria struttura, in centesimi di turno:
    # 0 = indifferente, 100 = un turno intero di vantaggio.
    peso_struttura = vincoli_g.get('preferenza_struttura', 0) / 100.0
    vincoli_utente_cache = ctx['vincoli_utente_cache']
    vincoli_solver_list = ctx['vincoli_solver_list']
    vs_utente_cache = ctx['vs_utente_cache']
    esclusioni_turno_cache = ctx['esclusioni_turno_cache']
    flag_map = ctx['flag_map']
    wd_map = ctx['wd_map']
    coefficienti = ctx['coefficienti']
    turni_dovuti = ctx['turni_dovuti']
    regole_conflitto = ctx['regole_conflitto']
    turno_flag_nome = ctx['turno_flag_nome']
    des_ref_map = ctx['des_ref_map']

    # Copia in-memory delle assegnazioni per utente/giorno (aggiornata man mano)
    ass_utente_giorno = copy.deepcopy(ctx['ass_per_utente_giorno'])

    # Se solo_vuote=False, le assegnazioni dei turni processati saranno azzerate:
    # rimuovi dalla mappa in-memory per coerenza
    if not ctx['solo_vuote']:
        turni_ids_proc = ctx['turni_ids_processati']
        celle_bloccate = ctx['celle_bloccate']
        for key in list(ass_utente_giorno.keys()):
            ass_utente_giorno[key] = [
                a for a in ass_utente_giorno[key]
                if a['turno_id'] not in turni_ids_proc or (a['turno_id'], key[1]) in celle_bloccate
            ]
            if not ass_utente_giorno[key]:
                del ass_utente_giorno[key]

    assegnazioni_proposte = []
    celle_fallite = []
    indispensabili_scoperti = 0

    for cella in celle:
        turno_id = cella['turno_id']
        local_id  = cella.get('local_id')
        gruppo_id = cella.get('gruppo_id')
        sg_id     = cella.get('sg_id')
        giorno = cella['giorno']
        flag_nome = cella['flag_nome']
        flag_id = cella.get('flag_id')
        ore_turno = cella['ore_turno']
        peso_turno = cella.get('peso_turno', 1)
        tq_ids = cella.get('tipi_qualitativo_ids', set())
        is_festivo = giorno_tipo.get(giorno, 'normale') in ('festivo', 'superfestivo')
        flag_antenati = _calcola_antenati_flag(flag_id, flag_map) if flag_id else set()

        # --- FASE 2: Filtro hard ---
        candidati = []

        for u in utenti:
            uid = u['id']
            s = stati[uid]

            # HARD: indisponibilita' (assenza + esclusioni manuali)
            if giorno in indisponibilita and uid in indisponibilita[giorno]:
                continue

            # HARD: max turni/giorno
            max_turni_g = _get_vincolo(vincoli_g, vincoli_utente_cache, uid, 'max_turni_giorno')
            if max_turni_g > 0 and s['turni_per_giorno'].get(giorno, 0) >= max_turni_g:
                continue

            # HARD: max giorni consecutivi
            max_consec = _get_vincolo(vincoli_g, vincoli_utente_cache, uid, 'max_giorni_consecutivi')
            if max_consec > 0:
                consec = _calcola_giorni_consecutivi(s, giorno - 1)
                if consec >= max_consec:
                    continue

            # HARD: max ore/mese
            max_ore = _get_vincolo(vincoli_g, vincoli_utente_cache, uid, 'max_ore_mese')
            if max_ore > 0 and (s['ore_mese'] + ore_turno) > max_ore:
                continue

            # HARD: max festivi
            if is_festivo:
                max_fest = _get_vincolo(vincoli_g, vincoli_utente_cache, uid, 'max_festivi_mese')
                if max_fest > 0 and s['festivi_mese'] >= max_fest:
                    continue

            # HARD: max turni totali (offset da turni dovuti)
            ha_vincolo_turni = ('max_n_turni_mese' in vincoli_g or
                                (uid in vincoli_utente_cache and
                                 'max_n_turni_mese' in vincoli_utente_cache[uid]))
            if ha_vincolo_turni:
                offset_turni = _get_vincolo(vincoli_g, vincoli_utente_cache, uid, 'max_n_turni_mese')
                limite_turni = turni_dovuti + offset_turni
                if limite_turni > 0 and (s['peso_totale'] + peso_turno) > limite_turni:
                    continue

            # HARD: vincoli solver per flag
            skip_flag = False
            for vs in vincoli_solver_list:
                if vs['tipo'] != 'flag':
                    continue
                ref_id = vs['ref_id']
                if ref_id in flag_antenati:
                    max_n = _get_vincolo_solver(vincoli_solver_list, vs_utente_cache, uid, 'flag', ref_id)
                    if max_n is not None and s['conteggio_flag'].get(ref_id, 0) >= max_n:
                        skip_flag = True
                        break
            if not skip_flag:
                for vs_extra in _get_vincoli_solver_utente_extra(vincoli_solver_list, vs_utente_cache, uid):
                    if vs_extra['tipo'] != 'flag':
                        continue
                    ref_id = vs_extra['ref_id']
                    if ref_id in flag_antenati:
                        if vs_extra['max_n'] is not None and s['conteggio_flag'].get(ref_id, 0) >= vs_extra['max_n']:
                            skip_flag = True
                            break
            if skip_flag:
                continue

            # HARD: vincoli solver per tipo qualitativo
            skip_qual = False
            for vs in vincoli_solver_list:
                if vs['tipo'] != 'qualitativo':
                    continue
                ref_id = vs['ref_id']
                if ref_id in tq_ids:
                    max_n = _get_vincolo_solver(vincoli_solver_list, vs_utente_cache, uid, 'qualitativo', ref_id)
                    if max_n is not None and s['conteggio_qualitativo'].get(ref_id, 0) >= max_n:
                        skip_qual = True
                        break
            if not skip_qual:
                for vs_extra in _get_vincoli_solver_utente_extra(vincoli_solver_list, vs_utente_cache, uid):
                    if vs_extra['tipo'] != 'qualitativo':
                        continue
                    ref_id = vs_extra['ref_id']
                    if ref_id in tq_ids:
                        if vs_extra['max_n'] is not None and s['conteggio_qualitativo'].get(ref_id, 0) >= vs_extra['max_n']:
                            skip_qual = True
                            break
            if skip_qual:
                continue

            # HARD: esclusioni per flag turno
            # HARD: esclusioni turno per preset (turno/gruppo/sovragruppo specifico)
            if esclusioni_turno_cache and uid in esclusioni_turno_cache:
                esclusi_u = esclusioni_turno_cache[uid]
                ecc = esclusi_u.get('eccezioni', set())
                if local_id and local_id in esclusi_u.get('turno', set()):
                    continue
                if gruppo_id and gruppo_id in esclusi_u.get('gruppo', set()):
                    # Eccezione: turno figlio esente
                    if not (local_id and local_id in ecc):
                        continue
                if sg_id and sg_id in esclusi_u.get('sovragruppo', set()):
                    # Eccezione: gruppo o turno figlio/nipote esente
                    if not ((gruppo_id and gruppo_id in ecc) or
                            (local_id and local_id in ecc)):
                        continue

            # HARD: regole conflitto (tutte bloccanti nel solver)
            if _valida_conflitti_inmem(
                regole_conflitto, flag_nome, flag_id,
                uid, giorno, ass_utente_giorno, flag_map,
                des_ref_map, escludi_regole
            ):
                continue

            candidati.append({'uid': uid})

        # --- FASE 3: Assegnazione tra candidati ---
        miglior_candidato = None

        if candidati:
            # 1° priorita': WD matching (round-robin per debito flag)
            wd_matching = []
            for cand in candidati:
                uid = cand['uid']
                wd = wd_map.get((uid, giorno))
                if wd and wd.get('req_tipo') == 'lavorativo':
                    if wd.get('req_flag_nome') and flag_nome and wd['req_flag_nome'] == flag_nome:
                        coeff = coefficienti.get(uid, 1.0)
                        quota_flag = max(0.1, coeff)
                        conteggio = stati[uid]['conteggio_flag'].get(flag_id, 0) if flag_id else 0
                        rapporto = conteggio / quota_flag
                        wd_matching.append((rapporto, stati[uid]['sigla'], uid, cand))

            if wd_matching:
                wd_matching.sort(key=lambda x: (x[0], x[1]))
                if top_k > 1 and len(wd_matching) > 1:
                    pool = wd_matching[:min(top_k, len(wd_matching))]
                    miglior_candidato = random.choice(pool)[2]
                else:
                    miglior_candidato = wd_matching[0][2]
            else:
                # 2° priorita': equita' proporzionale (debito turni)
                debito_list = []
                for cand in candidati:
                    uid = cand['uid']
                    s = stati[uid]
                    coeff = coefficienti.get(uid, 1.0)
                    turni_equi = max(0.1, turni_dovuti * coeff)
                    rapporto = s['totale_turni'] / turni_equi

                    if (giorno - 1) not in s['giorni_lavorati']:
                        rapporto -= 0.001

                    rapporto -= _vantaggio_struttura(s, sg_id, peso_struttura)

                    debito_list.append((rapporto, s['sigla'], uid))

                debito_list.sort(key=lambda x: (x[0], x[1]))
                if top_k > 1 and len(debito_list) > 1:
                    pool = debito_list[:min(top_k, len(debito_list))]
                    miglior_candidato = random.choice(pool)[2]
                else:
                    miglior_candidato = debito_list[0][2]

        if miglior_candidato is not None:
            assegnazioni_proposte.append({
                'turno_id': turno_id,
                'turno_sigla': cella['turno_sigla'],
                'giorno': giorno,
                'user_id': miglior_candidato,
                'user_sigla': stati[miglior_candidato]['sigla'],
            })

            # Aggiorna mappa assegnazioni in-memory (per conflict check successive)
            key = (miglior_candidato, giorno)
            ass_utente_giorno.setdefault(key, []).append({
                'turno_id': turno_id,
                'flag_nome': flag_nome,
            })

            # Aggiorna stato running
            s = stati[miglior_candidato]
            s['turni_per_giorno'][giorno] = s['turni_per_giorno'].get(giorno, 0) + 1
            s['giorni_lavorati'].add(giorno)
            s['totale_turni'] += 1
            s['peso_totale'] += peso_turno
            s['ore_mese'] += ore_turno
            if is_festivo:
                s['festivi_mese'] += 1
            for anc in flag_antenati:
                s['conteggio_flag'][anc] = s['conteggio_flag'].get(anc, 0) + 1
                s['peso_per_flag'][anc] = s['peso_per_flag'].get(anc, 0) + peso_turno
            for tq_id in tq_ids:
                s['conteggio_qualitativo'][tq_id] = s['conteggio_qualitativo'].get(tq_id, 0) + 1
        else:
            celle_fallite.append({
                'turno_id': turno_id,
                'turno_sigla': cella['turno_sigla'],
                'giorno': giorno,
                'priorita': cella['priorita_solver'],
            })
            if cella['priorita_solver'] == 'indispensabile':
                indispensabili_scoperti += 1

    return assegnazioni_proposte, celle_fallite, indispensabili_scoperti, stati


# ---------------------------------------------------------------------------
# Algoritmo solver (v2 — 3 fasi)
# ---------------------------------------------------------------------------

def esegui_solver(calendario_id, user_id_chiamante, solo_vuote=True,
                  solo_indispensabili=False,
                  dry_run=False, escludi_regole_ids=None,
                  turni_accessibili=None,
                  utenti_accessibili=None, top_k=1,
                  criteri_ordinamento=None, turni_ids=None,
                  fonte_desiderata='working'):
    """
    Esegue il solver greedy per auto-riempimento turni.

    Fase 1: Costruzione contesto (esclusioni, coefficienti, celle)
    Fase 2: Per ogni cella, filtro hard (assenza HARD, esclusioni, vincoli, regole conflitto)
    Fase 3: Assegnazione con round-robin WD + equita' proporzionale
    """
    escludi_regole = set(escludi_regole_ids or [])
    t_start = time.time()

    # ===================================================================
    # FASE 1: CONTESTO (una sola volta)
    # ===================================================================
    ctx = _costruisci_contesto(
        calendario_id, solo_vuote=solo_vuote,
        solo_indispensabili=solo_indispensabili,
        escludi_regole_ids=escludi_regole_ids,
        turni_accessibili=turni_accessibili,
        utenti_accessibili=utenti_accessibili,
        criteri_ordinamento=criteri_ordinamento,
        turni_ids=turni_ids,
        fonte_desiderata=fonte_desiderata,
    )
    if 'errore' in ctx:
        return {'ok': False, 'errore': ctx['errore']}

    celle = ctx['celle']
    turni_ids_processati = ctx['turni_ids_processati']
    celle_bloccate = ctx['celle_bloccate']
    giorni_info = ctx['giorni_info']

    # --- SNAPSHOT PRECEDENTI (per history) ---
    precedenti_map = {}
    if not dry_run:
        for tid in turni_ids_processati:
            rows = query_all(
                "SELECT * FROM assegnazioni_turni "
                "WHERE calendario_id=? AND turno_id=?",
                (calendario_id, tid)
            )
            for r in rows:
                precedenti_map[(r['turno_id'], r['giorno'])] = dict(r)

    # Se solo_vuote=False e non dry_run, azzera assegnazioni sui turni da processare
    if not solo_vuote and not dry_run:
        turni_ids_list = list(turni_ids_processati)
        if turni_ids_list:
            bloccate_per_turno = {}
            for (tid, g) in celle_bloccate:
                bloccate_per_turno.setdefault(tid, set()).add(g)
            for tid in turni_ids_list:
                giorni_bloccati = bloccate_per_turno.get(tid, set())
                if giorni_bloccati:
                    for g_info in giorni_info:
                        if g_info['giorno'] not in giorni_bloccati:
                            execute_write(
                                "UPDATE assegnazioni_turni SET user_id=NULL, conflitto='free', "
                                "conflitti='[]', forza_inserimento=0 "
                                "WHERE calendario_id=? AND turno_id=? AND giorno=?",
                                (calendario_id, tid, g_info['giorno'])
                            )
                else:
                    execute_write(
                        "UPDATE assegnazioni_turni SET user_id=NULL, conflitto='free', "
                        "conflitti='[]', forza_inserimento=0 "
                        "WHERE calendario_id=? AND turno_id=?",
                        (calendario_id, tid)
                    )

    # ===================================================================
    # FASE 2 + 3: ASSEGNAZIONE (in-memory)
    # ===================================================================
    assegnazioni_proposte, celle_fallite, indispensabili_scoperti, stati = \
        _esegui_assegnazione(ctx, escludi_regole, top_k)

    # ===================================================================
    # SCRITTURA FINALE
    # ===================================================================
    durata_ms = int((time.time() - t_start) * 1000)

    if dry_run:
        return {
            'ok': True,
            'dry_run': True,
            'celle_totali': len(celle),
            'celle_riempite': len(assegnazioni_proposte),
            'celle_fallite': len(celle_fallite),
            'indispensabili_scoperti': indispensabili_scoperti,
            'proposte': assegnazioni_proposte,
            'fallite': celle_fallite,
            'durata_ms': durata_ms,
            'turni_operati': len(ctx['turni_info']),
            'turni_totali': ctx['turni_totali'],
            'utenti_operati': len(ctx['utenti']),
        }

    # Scrivi assegnazioni nel DB
    for prop in assegnazioni_proposte:
        execute_write(
            """
            INSERT INTO assegnazioni_turni
                (calendario_id, turno_id, giorno, user_id, forza_inserimento,
                 conflitto, conflitti, updated_at, updated_by)
            VALUES (?,?,?,?,0,'free','[]',datetime('now'),?)
            ON CONFLICT(calendario_id, turno_id, giorno) DO UPDATE SET
                user_id           = excluded.user_id,
                forza_inserimento = excluded.forza_inserimento,
                conflitto         = excluded.conflitto,
                conflitti         = excluded.conflitti,
                updated_at        = excluded.updated_at,
                updated_by        = excluded.updated_by
            """,
            (calendario_id, prop['turno_id'], prop['giorno'], prop['user_id'],
             user_id_chiamante)
        )

    # Ri-validazione finale (tutte le celle con utente assegnato)
    tutte_ass = query_all(
        "SELECT turno_id, giorno, user_id FROM assegnazioni_turni "
        "WHERE calendario_id=? AND user_id IS NOT NULL",
        (calendario_id,)
    )
    for ass in tutte_ass:
        try:
            val = valida_assegnazione(calendario_id, ass['turno_id'], ass['user_id'], ass['giorno'],
                                      forza_inserimento=False)
            conflitti_json = json.dumps(val.get('conflitti', []))
            conflitto_legacy = 'free' if not val['conflitti'] else 'forced'
        except Exception:
            conflitti_json = '[]'
            conflitto_legacy = 'free'
        execute_write(
            "UPDATE assegnazioni_turni SET conflitto=?, conflitti=? "
            "WHERE calendario_id=? AND turno_id=? AND giorno=?",
            (conflitto_legacy, conflitti_json,
             calendario_id, ass['turno_id'], ass['giorno'])
        )

    # --- HISTORY ---
    dati_prec_history = []
    dati_nuovi_history = []
    for (tid, g), prec in precedenti_map.items():
        nuova = query_one(
            "SELECT * FROM assegnazioni_turni "
            "WHERE calendario_id=? AND turno_id=? AND giorno=?",
            (calendario_id, tid, g)
        )
        if not nuova:
            continue
        prec_uid = prec.get('user_id') if prec else None
        nuova_uid = nuova.get('user_id')
        prec_conf = prec.get('conflitti', '[]') if prec else '[]'
        nuova_conf = nuova.get('conflitti', '[]')
        if prec_uid != nuova_uid or prec_conf != nuova_conf:
            dati_prec_history.append({
                'tabella': 'assegnazioni_turni',
                'record_id': nuova['id'],
                'dati': dict(prec) if prec else None,
            })
            dati_nuovi_history.append({
                'tabella': 'assegnazioni_turni',
                'record_id': nuova['id'],
                'dati': dict(nuova),
            })

    if dati_prec_history:
        aggiungi_step(
            calendario_id, 'solver', 0,
            dati_prec_history, dati_nuovi_history,
            user_id_chiamante
        )

    # Log esecuzione
    dettaglio = json.dumps({
        'proposte': assegnazioni_proposte[:50],
        'fallite': celle_fallite,
    })
    execute_write(
        """
        INSERT INTO solver_esecuzioni
            (calendario_id, stato, celle_totali, celle_riempite,
             celle_fallite, dettaglio, durata_ms, created_by)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (calendario_id, 'completato', len(celle),
         len(assegnazioni_proposte), len(celle_fallite),
         dettaglio, durata_ms, user_id_chiamante)
    )

    esecuzione = query_one(
        "SELECT id FROM solver_esecuzioni WHERE calendario_id=? ORDER BY id DESC LIMIT 1",
        (calendario_id,)
    )

    return {
        'ok': True,
        'dry_run': False,
        'celle_totali': len(celle),
        'celle_riempite': len(assegnazioni_proposte),
        'celle_fallite': len(celle_fallite),
        'indispensabili_scoperti': indispensabili_scoperti,
        'esecuzione_id': esecuzione['id'] if esecuzione else None,
        'durata_ms': durata_ms,
        'fallite': celle_fallite,
        'turni_operati': len(ctx['turni_info']),
        'turni_totali': ctx['turni_totali'],
        'utenti_operati': len(ctx['utenti']),
    }


# ---------------------------------------------------------------------------
# Multi-start: N esecuzioni con randomizzazione, seleziona la migliore
# ---------------------------------------------------------------------------

def esegui_solver_multistart(calendario_id, user_id_chiamante,
                             n_runs=10, top_k=3,
                             solo_vuote=True, solo_indispensabili=False,
                             escludi_regole_ids=None,
                             turni_accessibili=None, utenti_accessibili=None,
                             preset_costo_id=None, criteri_ordinamento=None,
                             turni_ids=None, fonte_desiderata='working'):
    """
    Esegue il solver N volte con randomizzazione (top_k > 1), valuta ogni
    soluzione con la cost function, scrive la migliore su DB.

    Contesto (vincoli, disponibilita', celle) costruito UNA SOLA VOLTA.
    Solo il loop di assegnazione (Fase 2+3) viene ripetuto N volte.
    """
    t_start = time.time()
    n_runs = min(max(n_runs, 2), 50)
    escludi_regole = set(escludi_regole_ids or [])

    # ===================================================================
    # FASE 1: CONTESTO (una sola volta per tutte le N esecuzioni)
    # ===================================================================
    ctx = _costruisci_contesto(
        calendario_id, solo_vuote=solo_vuote,
        solo_indispensabili=solo_indispensabili,
        escludi_regole_ids=escludi_regole_ids,
        turni_accessibili=turni_accessibili,
        utenti_accessibili=utenti_accessibili,
        criteri_ordinamento=criteri_ordinamento,
        turni_ids=turni_ids,
        fonte_desiderata=fonte_desiderata,
    )
    if 'errore' in ctx:
        return {'ok': False, 'errore': ctx['errore']}

    # --- Esecuzione multipla (solo Fase 2+3, in-memory) ---
    risultati_run = []

    for run_idx in range(n_runs):
        proposte, fallite, ind_scop, _stati = _esegui_assegnazione(
            ctx, escludi_regole, top_k
        )
        risultati_run.append({
            'proposte': proposte,
            'fallite': fallite,
            'celle_totali': len(ctx['celle']),
            'celle_riempite': len(proposte),
            'celle_fallite': len(fallite),
            'indispensabili_scoperti': ind_scop,
        })

    if not risultati_run:
        return {'ok': False, 'errore': 'Nessuna esecuzione riuscita.'}

    # --- Valutazione costo ---
    def _valuta_costo(proposte):
        conteggi = {}
        for p in proposte:
            uid = p['user_id']
            conteggi[uid] = conteggi.get(uid, 0) + 1
        if not conteggi:
            return float('inf')
        vals = list(conteggi.values())
        media = sum(vals) / len(vals)
        return sum((v - media) ** 2 for v in vals) / len(vals)

    for r in risultati_run:
        r['_costo'] = _valuta_costo(r['proposte'])

    risultati_run.sort(key=lambda r: (r['_costo'], -r['celle_riempite']))
    migliore = risultati_run[0]
    costi = [round(r['_costo'], 6) for r in risultati_run]

    # ===================================================================
    # SCRITTURA SU DB della soluzione migliore
    # ===================================================================

    turni_ids_processati = ctx['turni_ids_processati']
    celle_bloccate = ctx['celle_bloccate']
    giorni_info = ctx['giorni_info']

    # Snapshot precedenti per history
    precedenti_map = {}
    for tid in turni_ids_processati:
        rows = query_all(
            "SELECT * FROM assegnazioni_turni "
            "WHERE calendario_id=? AND turno_id=?",
            (calendario_id, tid)
        )
        for r in rows:
            precedenti_map[(r['turno_id'], r['giorno'])] = dict(r)

    # Se solo_vuote=False, azzera prima
    if not solo_vuote:
        bloccate_per_turno = {}
        for (tid, g) in celle_bloccate:
            bloccate_per_turno.setdefault(tid, set()).add(g)
        for tid in turni_ids_processati:
            giorni_bloccati = bloccate_per_turno.get(tid, set())
            if giorni_bloccati:
                for g_info in giorni_info:
                    if g_info['giorno'] not in giorni_bloccati:
                        execute_write(
                            "UPDATE assegnazioni_turni SET user_id=NULL, conflitto='free', "
                            "conflitti='[]', forza_inserimento=0 "
                            "WHERE calendario_id=? AND turno_id=? AND giorno=?",
                            (calendario_id, tid, g_info['giorno'])
                        )
            else:
                execute_write(
                    "UPDATE assegnazioni_turni SET user_id=NULL, conflitto='free', "
                    "conflitti='[]', forza_inserimento=0 "
                    "WHERE calendario_id=? AND turno_id=?",
                    (calendario_id, tid)
                )

    # Scrivi assegnazioni
    for prop in migliore['proposte']:
        execute_write(
            """
            INSERT INTO assegnazioni_turni
                (calendario_id, turno_id, giorno, user_id, forza_inserimento,
                 conflitto, conflitti, updated_at, updated_by)
            VALUES (?,?,?,?,0,'free','[]',datetime('now'),?)
            ON CONFLICT(calendario_id, turno_id, giorno) DO UPDATE SET
                user_id           = excluded.user_id,
                forza_inserimento = excluded.forza_inserimento,
                conflitto         = excluded.conflitto,
                conflitti         = excluded.conflitti,
                updated_at        = excluded.updated_at,
                updated_by        = excluded.updated_by
            """,
            (calendario_id, prop['turno_id'], prop['giorno'], prop['user_id'],
             user_id_chiamante)
        )

    # Ri-validazione finale (tutte le celle con utente assegnato)
    tutte_ass = query_all(
        "SELECT turno_id, giorno, user_id FROM assegnazioni_turni "
        "WHERE calendario_id=? AND user_id IS NOT NULL",
        (calendario_id,)
    )
    for ass in tutte_ass:
        try:
            val = valida_assegnazione(
                calendario_id, ass['turno_id'], ass['user_id'], ass['giorno'],
                forza_inserimento=False
            )
            conflitti_json = json.dumps(val.get('conflitti', []))
            conflitto_legacy = 'free' if not val['conflitti'] else 'forced'
        except Exception:
            conflitti_json = '[]'
            conflitto_legacy = 'free'
        execute_write(
            "UPDATE assegnazioni_turni SET conflitto=?, conflitti=? "
            "WHERE calendario_id=? AND turno_id=? AND giorno=?",
            (conflitto_legacy, conflitti_json,
             calendario_id, ass['turno_id'], ass['giorno'])
        )

    # History
    dati_prec_history = []
    dati_nuovi_history = []
    for (tid, g), prec in precedenti_map.items():
        nuova = query_one(
            "SELECT * FROM assegnazioni_turni "
            "WHERE calendario_id=? AND turno_id=? AND giorno=?",
            (calendario_id, tid, g)
        )
        if not nuova:
            continue
        prec_uid = prec.get('user_id') if prec else None
        nuova_uid = nuova.get('user_id')
        prec_conf = prec.get('conflitti', '[]') if prec else '[]'
        nuova_conf = nuova.get('conflitti', '[]')
        if prec_uid != nuova_uid or prec_conf != nuova_conf:
            dati_prec_history.append({
                'tabella': 'assegnazioni_turni',
                'record_id': nuova['id'],
                'dati': dict(prec) if prec else None,
            })
            dati_nuovi_history.append({
                'tabella': 'assegnazioni_turni',
                'record_id': nuova['id'],
                'dati': dict(nuova),
            })

    if dati_prec_history:
        aggiungi_step(
            calendario_id, 'solver', 0,
            dati_prec_history, dati_nuovi_history,
            user_id_chiamante
        )

    # Log esecuzione
    durata_ms = int((time.time() - t_start) * 1000)
    dettaglio = json.dumps({
        'proposte': migliore['proposte'][:50],
        'fallite': migliore['fallite'],
        'multi_start': True,
        'n_runs': n_runs,
        'costi': costi,
    })
    execute_write(
        """
        INSERT INTO solver_esecuzioni
            (calendario_id, stato, celle_totali, celle_riempite,
             celle_fallite, dettaglio, durata_ms, created_by)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (calendario_id, 'completato', migliore['celle_totali'],
         migliore['celle_riempite'], migliore['celle_fallite'],
         dettaglio, durata_ms, user_id_chiamante)
    )

    esecuzione = query_one(
        "SELECT id FROM solver_esecuzioni WHERE calendario_id=? ORDER BY id DESC LIMIT 1",
        (calendario_id,)
    )

    return {
        'ok': True,
        'dry_run': False,
        'celle_totali': migliore['celle_totali'],
        'celle_riempite': migliore['celle_riempite'],
        'celle_fallite': migliore['celle_fallite'],
        'indispensabili_scoperti': migliore['indispensabili_scoperti'],
        'esecuzione_id': esecuzione['id'] if esecuzione else None,
        'durata_ms': durata_ms,
        'fallite': migliore['fallite'],
        'turni_operati': len(ctx['turni_info']),
        'turni_totali': ctx['turni_totali'],
        'utenti_operati': len(ctx['utenti']),
        'multi_start': True,
        'n_runs': n_runs,
        'costi': costi,
        'costo_migliore': round(migliore['_costo'], 6),
    }
