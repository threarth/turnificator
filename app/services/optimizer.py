"""
app/services/optimizer.py — optimizer swap-based per bilanciamento turni.

Dopo che il solver ha riempito la griglia, l'optimizer ribilancia le
assegnazioni scambiando coppie di utenti per minimizzare una cost function
pesata (da preset_ottimizzazione).

Algoritmo: hill climbing con swap casuali.
  - Tipo 1: stesso giorno, due celle con utenti diversi → scambio
  - Tipo 2: stesso turno, giorni diversi → scambio
  - Accetta swap solo se costo diminuisce e vincoli hard rispettati
  - Stop dopo N iterazioni senza miglioramento (convergenza)
"""

import json
import math
import random
import time

from app.db import query_one, query_all, execute_write
from app.services.validatori import valida_assegnazione, _flag_matcha, _get_flag_map
from app.services.history import aggiungi_step
from app.services.config_snapshot import (
    carica_config_snapshot,
    snap_vincoli_globali, snap_vincoli_utente,
    snap_vincoli_solver, snap_vincoli_solver_utente,
    snap_esclusioni_utente, snap_giorni_esclusi, snap_flag_map,
)
from app.services.solver_common import (
    espandi_esclusioni_manuali, espandi_celle_bloccate,
    calcola_coefficienti, calcola_quote,
    calcola_costo_totale, calcola_costo_componente, calcola_costo_flag,
    calcola_costo_peso_flag,
    arricchisci_giorni_con_dow,
)
from app.services.solver import (
    _carica_vincoli_globali, _carica_vincoli_utente,
    _carica_vincoli_solver, _carica_vincoli_solver_utente_bulk,
    _carica_esclusioni_utente, _carica_giorni_esclusi,
    _espandi_giorni_esclusi, _carica_working_desiderata_bulk,
    _get_vincolo, _get_vincolo_solver,
    _get_vincoli_solver_utente_extra,
    _calcola_antenati_flag, _calcola_giorni_consecutivi,
    _utente_escluso_per_flag,
    _inizializza_stati,
)


# ---------------------------------------------------------------------------
# Validazione vincoli hard per uno swap
# ---------------------------------------------------------------------------

def _verifica_vincoli_hard(uid, turno_id, giorno, stati, vincoli_g,
                           vincoli_utente_cache, vincoli_solver_list,
                           vs_utente_cache, esclusioni_cache, flag_map,
                           indisponibilita, turni_info_map, giorno_tipo,
                           turni_dovuti, calendario_id, escludi_regole):
    """
    Verifica che un utente possa stare nella cella (turno_id, giorno).
    Ritorna True se tutti i vincoli hard sono rispettati.
    """
    s = stati[uid]
    t = turni_info_map.get(turno_id)
    if not t:
        return False

    flag_id = t.get('flag_id')
    ore_turno = t.get('ore_turno') or 0
    tq_raw = t.get('tipi_qualitativi', '[]')
    try:
        tq_list = json.loads(tq_raw) if isinstance(tq_raw, str) else (tq_raw or [])
    except (json.JSONDecodeError, TypeError):
        tq_list = []
    tq_ids = {item['id'] for item in tq_list if isinstance(item, dict) and 'id' in item}
    flag_antenati = _calcola_antenati_flag(flag_id, flag_map) if flag_id else set()
    is_festivo = giorno_tipo.get(giorno, 'normale') in ('festivo', 'superfestivo')

    # Indisponibilita' (assenza + esclusioni manuali)
    if giorno in indisponibilita and uid in indisponibilita[giorno]:
        return False

    # Max turni/giorno
    max_turni_g = _get_vincolo(vincoli_g, vincoli_utente_cache, uid, 'max_turni_giorno')
    if max_turni_g > 0 and s['turni_per_giorno'].get(giorno, 0) >= max_turni_g:
        return False

    # Max giorni consecutivi
    max_consec = _get_vincolo(vincoli_g, vincoli_utente_cache, uid, 'max_giorni_consecutivi')
    if max_consec > 0:
        consec = _calcola_giorni_consecutivi(s, giorno - 1)
        if consec >= max_consec:
            return False

    # Max ore/mese
    max_ore = _get_vincolo(vincoli_g, vincoli_utente_cache, uid, 'max_ore_mese')
    if max_ore > 0 and (s['ore_mese'] + ore_turno) > max_ore:
        return False

    # Max festivi
    if is_festivo:
        max_fest = _get_vincolo(vincoli_g, vincoli_utente_cache, uid, 'max_festivi_mese')
        if max_fest > 0 and s['festivi_mese'] >= max_fest:
            return False

    # Max turni totali
    ha_vincolo_turni = ('max_n_turni_mese' in vincoli_g or
                        (uid in vincoli_utente_cache and
                         'max_n_turni_mese' in vincoli_utente_cache[uid]))
    if ha_vincolo_turni:
        offset_turni = _get_vincolo(vincoli_g, vincoli_utente_cache, uid, 'max_n_turni_mese')
        limite_turni = turni_dovuti + offset_turni
        if limite_turni > 0 and s['totale_turni'] >= limite_turni:
            return False

    # Vincoli solver per flag
    for vs in vincoli_solver_list:
        if vs['tipo'] != 'flag':
            continue
        ref_id = vs['ref_id']
        if ref_id in flag_antenati:
            max_n = _get_vincolo_solver(vincoli_solver_list, vs_utente_cache, uid, 'flag', ref_id)
            if max_n is not None and s['conteggio_flag'].get(ref_id, 0) >= max_n:
                return False

    for vs_extra in _get_vincoli_solver_utente_extra(vincoli_solver_list, vs_utente_cache, uid):
        if vs_extra['tipo'] != 'flag':
            continue
        ref_id = vs_extra['ref_id']
        if ref_id in flag_antenati:
            if vs_extra['max_n'] is not None and s['conteggio_flag'].get(ref_id, 0) >= vs_extra['max_n']:
                return False

    # Vincoli solver per qualitativo
    for vs in vincoli_solver_list:
        if vs['tipo'] != 'qualitativo':
            continue
        ref_id = vs['ref_id']
        if ref_id in tq_ids:
            max_n = _get_vincolo_solver(vincoli_solver_list, vs_utente_cache, uid, 'qualitativo', ref_id)
            if max_n is not None and s['conteggio_qualitativo'].get(ref_id, 0) >= max_n:
                return False

    for vs_extra in _get_vincoli_solver_utente_extra(vincoli_solver_list, vs_utente_cache, uid):
        if vs_extra['tipo'] != 'qualitativo':
            continue
        ref_id = vs_extra['ref_id']
        if ref_id in tq_ids:
            if vs_extra['max_n'] is not None and s['conteggio_qualitativo'].get(ref_id, 0) >= vs_extra['max_n']:
                return False

    # Esclusioni per flag turno
    if flag_id and _utente_escluso_per_flag(esclusioni_cache, uid, flag_id):
        return False

    # Regole conflitto bloccanti
    try:
        val = valida_assegnazione(calendario_id, turno_id, uid, giorno,
                                  forza_inserimento=False)
    except (ValueError, Exception):
        return False

    # Nel solver/optimizer tutte le regole attive sono bloccanti
    if escludi_regole:
        val['conflitti'] = [c for c in val['conflitti']
                            if c.get('id') not in escludi_regole]

    if val['conflitti']:
        return False

    return True


# ---------------------------------------------------------------------------
# Aggiornamento stato running dopo swap
# ---------------------------------------------------------------------------

def _rimuovi_da_stato(stato, turno_info, giorno, flag_map, giorno_tipo):
    """Rimuove una assegnazione dallo stato running."""
    t = turno_info
    ore = t.get('ore_turno') or 0
    peso = t.get('peso_turno') or 1
    flag_id = t.get('flag_id')
    is_festivo = giorno_tipo.get(giorno, 'normale') in ('festivo', 'superfestivo')

    tq_raw = t.get('tipi_qualitativi', '[]')
    try:
        tq_list = json.loads(tq_raw) if isinstance(tq_raw, str) else (tq_raw or [])
    except (json.JSONDecodeError, TypeError):
        tq_list = []
    tq_ids = {item['id'] for item in tq_list if isinstance(item, dict) and 'id' in item}

    stato['turni_per_giorno'][giorno] = max(0, stato['turni_per_giorno'].get(giorno, 1) - 1)
    if stato['turni_per_giorno'][giorno] == 0:
        stato['giorni_lavorati'].discard(giorno)
    stato['totale_turni'] = max(0, stato['totale_turni'] - 1)
    stato['peso_totale'] = max(0, stato['peso_totale'] - peso)
    stato['ore_mese'] = max(0, stato['ore_mese'] - ore)
    if is_festivo:
        stato['festivi_mese'] = max(0, stato['festivi_mese'] - 1)

    if flag_id:
        for anc in _calcola_antenati_flag(flag_id, flag_map):
            stato['conteggio_flag'][anc] = max(0, stato['conteggio_flag'].get(anc, 1) - 1)
            stato.setdefault('peso_per_flag', {})[anc] = max(0, stato.get('peso_per_flag', {}).get(anc, peso) - peso)

    for tq_id in tq_ids:
        stato['conteggio_qualitativo'][tq_id] = max(0, stato['conteggio_qualitativo'].get(tq_id, 1) - 1)


def _aggiungi_a_stato(stato, turno_info, giorno, flag_map, giorno_tipo):
    """Aggiunge una assegnazione allo stato running."""
    t = turno_info
    ore = t.get('ore_turno') or 0
    peso = t.get('peso_turno') or 1
    flag_id = t.get('flag_id')
    is_festivo = giorno_tipo.get(giorno, 'normale') in ('festivo', 'superfestivo')

    tq_raw = t.get('tipi_qualitativi', '[]')
    try:
        tq_list = json.loads(tq_raw) if isinstance(tq_raw, str) else (tq_raw or [])
    except (json.JSONDecodeError, TypeError):
        tq_list = []
    tq_ids = {item['id'] for item in tq_list if isinstance(item, dict) and 'id' in item}

    stato['turni_per_giorno'][giorno] = stato['turni_per_giorno'].get(giorno, 0) + 1
    stato['giorni_lavorati'].add(giorno)
    stato['totale_turni'] += 1
    stato['peso_totale'] += peso
    stato['ore_mese'] += ore
    if is_festivo:
        stato['festivi_mese'] += 1

    if flag_id:
        for anc in _calcola_antenati_flag(flag_id, flag_map):
            stato['conteggio_flag'][anc] = stato['conteggio_flag'].get(anc, 0) + 1
            stato.setdefault('peso_per_flag', {})[anc] = stato.get('peso_per_flag', {}).get(anc, 0) + peso

    for tq_id in tq_ids:
        stato['conteggio_qualitativo'][tq_id] = stato['conteggio_qualitativo'].get(tq_id, 0) + 1


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def esegui_ottimizzazione(calendario_id, user_id_chiamante,
                          preset_id=None, pesi_custom=None, ref_id_custom=None,
                          max_iterazioni=1000, preview=False,
                          turni_accessibili=None, utenti_accessibili=None,
                          escludi_regole_ids=None,
                          temperatura_iniziale=0.0, raffreddamento=0.995,
                          temperatura_minima=0.0001, filtro_turni_ids=None):
    """
    Esegue l'ottimizzazione swap-based per bilanciare le assegnazioni.

    Supporta due modalita':
    - Hill Climbing (default): temperatura_iniziale=0.0, accetta solo miglioramenti
    - Simulated Annealing: temperatura_iniziale>0, accetta peggioramenti con
      probabilita' P=exp(-delta/T), cooling T*=raffreddamento.
      Dopo convergenza SA, esegue tail-pass HC per rifinitura.

    Args:
        calendario_id: ID calendario
        user_id_chiamante: chi ha lanciato
        preset_id: ID preset da preset_ottimizzazione (opzionale)
        pesi_custom: dict pesi se non si usa preset (opzionale)
        ref_id_custom: flag_turno.id per bilancio per_flag custom
        max_iterazioni: max iterazioni (default 1000)
        preview: se True non scrive su DB
        turni_accessibili: set di local_id (per manager non-admin)
        utenti_accessibili: set di user_id (per manager non-admin)
        escludi_regole_ids: regole conflitto da ignorare
        temperatura_iniziale: temperatura SA (0.0 = HC puro, >0 = SA)
        raffreddamento: fattore cooling (0.995 default)
        temperatura_minima: soglia sotto cui T diventa 0 (HC tail-pass)

    Returns:
        dict con risultato ottimizzazione
    """
    escludi_regole = set(escludi_regole_ids or [])
    t_start = time.time()

    # --- Carica preset ---
    pesi = {'ore': 1.0, 'target': 1.0, 'festivi': 1.0,
            'peso': 1.0, 'varieta': 1.0, 'desiderata': 1.0}
    ref_id = None
    tipo_preset = 'completo'

    if preset_id:
        preset = query_one(
            "SELECT * FROM preset_ottimizzazione WHERE id=? AND is_active=1",
            (preset_id,)
        )
        if preset:
            try:
                pesi.update(json.loads(preset['pesi'] or '{}'))
            except (json.JSONDecodeError, TypeError):
                pass
            ref_id = preset['ref_id']
            tipo_preset = preset['tipo']
    elif pesi_custom:
        pesi.update(pesi_custom)
        ref_id = ref_id_custom

    # --- Carica contesto (come solver Fase 1) ---
    cal = query_one(
        "SELECT mese, anno, esclusioni_manuali, celle_bloccate FROM calendari WHERE id=?",
        (calendario_id,)
    )
    if not cal:
        return {'ok': False, 'errore': 'Calendario non trovato.'}

    turni_info = query_all(
        """
        SELECT ct.id, ct.local_id, ct.sigla, ct.flag_nome, ct.flag_id,
               ct.priorita_solver, ct.peso_priorita_solver, ct.peso_turno, ct.ordine,
               ct.ore_turno, ct.tipi_qualitativi,
               ct.apri_festivi, ct.apri_superfestivi, ct.aperture_straordinarie,
               ct.is_disabled
        FROM calendario_turni ct
        WHERE ct.calendario_id = ?
        ORDER BY ct.ordine
        """,
        (calendario_id,)
    )
    # Escludi turni disattivati
    turni_info = [t for t in turni_info if not t.get('is_disabled', 0)]

    if turni_accessibili is not None:
        turni_info = [t for t in turni_info if int(t['local_id']) in turni_accessibili]

    turni_info_map = {t['id']: dict(t) for t in turni_info}
    turni_ids = set(turni_info_map.keys())

    # Filtro turni selezionati dall'utente: restringe solo le celle swap,
    # NON il calcolo costo (che resta globale su tutti i turni accessibili)
    turni_ids_swap = turni_ids
    if filtro_turni_ids is not None:
        _filtro_set = {int(x) for x in filtro_turni_ids}
        turni_ids_swap = {tid for tid, tinfo in turni_info_map.items()
                         if int(tinfo['local_id']) in _filtro_set}

    giorni_info = query_all(
        "SELECT giorno, is_lavorativo, ore_lavorative, tipo "
        "FROM giorni_calendario WHERE calendario_id = ? ORDER BY giorno",
        (calendario_id,)
    )
    arricchisci_giorni_con_dow(giorni_info, cal['mese'], cal['anno'])
    giorno_tipo = {g['giorno']: g.get('tipo', 'normale') for g in giorni_info}
    giorni_lavorativi = sum(1 for g in giorni_info if g.get('is_lavorativo'))
    turni_dovuti = giorni_lavorativi

    # Esclusioni manuali e celle bloccate
    indisponibilita_manuali = espandi_esclusioni_manuali(
        cal.get('esclusioni_manuali', '[]'), giorni_info
    )
    celle_bloccate = espandi_celle_bloccate(cal.get('celle_bloccate', '[]'))

    # Config snapshot o live
    config_snap = carica_config_snapshot(calendario_id)
    if config_snap:
        vincoli_g = snap_vincoli_globali(config_snap)
        flag_map = snap_flag_map(config_snap)
        vincoli_utente_cache = snap_vincoli_utente(config_snap)
        vincoli_solver_list = snap_vincoli_solver(config_snap)
        vs_utente_cache = snap_vincoli_solver_utente(config_snap)
        esclusioni_cache = snap_esclusioni_utente(config_snap)
        giorni_esclusi_cache = snap_giorni_esclusi(config_snap)
    else:
        vincoli_g = _carica_vincoli_globali()
        flag_map = _get_flag_map()
        vincoli_utente_cache = {}
        for u_temp in query_all(
            "SELECT id FROM users WHERE is_active=1 AND role IN ('basic','manager','admin')"
        ):
            vu = _carica_vincoli_utente(u_temp['id'])
            if vu:
                vincoli_utente_cache[u_temp['id']] = vu
        vincoli_solver_list = _carica_vincoli_solver()
        vs_utente_cache = _carica_vincoli_solver_utente_bulk()
        esclusioni_cache = _carica_esclusioni_utente()
        giorni_esclusi_cache = _carica_giorni_esclusi()

    stati, utenti = _inizializza_stati(calendario_id, giorni_info, turni_info, flag_map,
                                       utenti_accessibili=utenti_accessibili)

    # Working desiderata
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
    utenti_ids = [u['id'] for u in utenti]
    coefficienti = calcola_coefficienti(utenti_ids, giorni_lavorativi, indisponibilita, wd_map)
    quote_ore = calcola_quote(
        sum(g.get('ore_lavorative', 0) or 0 for g in giorni_info) / max(len(utenti), 1),
        coefficienti
    )
    n_festivi = sum(1 for g in giorni_info if g.get('tipo') in ('festivo', 'superfestivo'))
    quote_festivi = calcola_quote(n_festivi / max(len(utenti), 1), coefficienti)

    # Quote peso: peso medio per turno * turni_dovuti
    peso_medio = 1.0
    if turni_info:
        peso_medio = sum(t.get('peso_turno', 1) or 1 for t in turni_info) / len(turni_info)
    quote_peso = calcola_quote(peso_medio * turni_dovuti / max(len(utenti), 1), coefficienti)

    # Quote flag (per per_flag: solo ref_id)
    quote_flag = None
    quote_peso_flag = None
    if ref_id is not None:
        # Conta assegnazioni totali per quel flag → distribuzione equa
        totale_flag = sum(s.get('conteggio_flag', {}).get(ref_id, 0) for s in stati.values())
        quote_flag = calcola_quote(totale_flag / max(len(utenti), 1), coefficienti)
        # Somma pesi turni per quel flag → distribuzione equa del carico
        totale_peso_flag = sum(s.get('peso_per_flag', {}).get(ref_id, 0) for s in stati.values())
        quote_peso_flag = calcola_quote(totale_peso_flag / max(len(utenti), 1), coefficienti)

    # Stati WD per cost function desiderata
    stati_wd = {}
    for uid in utenti_ids:
        richiesti = 0
        soddisfatti = 0
        for g_info in giorni_info:
            g = g_info['giorno']
            wd = wd_map.get((uid, g))
            if not wd or wd.get('req_tipo') != 'lavorativo':
                continue
            richiesti += 1
            # Verifica se soddisfatto (utente ha assegnazione con flag matching)
            # Approssimazione: controlla se ha lavorato quel giorno
            if g in stati[uid]['giorni_lavorati']:
                soddisfatti += 1
        if richiesti > 0:
            stati_wd[uid] = {'richiesti': richiesti, 'soddisfatti': soddisfatti}

    # --- Carica assegnazioni correnti per swap ---
    ass_correnti = query_all(
        "SELECT id, turno_id, giorno, user_id FROM assegnazioni_turni "
        "WHERE calendario_id = ? AND user_id IS NOT NULL",
        (calendario_id,)
    )
    # Filtra per turni accessibili/selezionati e celle non bloccate
    celle_swap = []
    for a in ass_correnti:
        if a['turno_id'] not in turni_ids_swap:
            continue
        if (a['turno_id'], a['giorno']) in celle_bloccate:
            continue
        if a['user_id'] not in stati:
            continue
        celle_swap.append(dict(a))

    if len(celle_swap) < 2:
        return {
            'ok': True, 'swap_count': 0,
            'costo_iniziale': 0, 'costo_finale': 0,
            'durata_ms': 0, 'motivo': 'Insufficienti celle per swap.',
        }

    # --- Calcolo costo iniziale ---
    costo_iniziale = calcola_costo_totale(
        stati, pesi, ref_id=ref_id,
        quote_ore=quote_ore, quote_festivi=quote_festivi,
        quote_peso=quote_peso, quote_flag=quote_flag,
        quote_peso_flag=quote_peso_flag,
        stati_wd=stati_wd
    )

    # --- Loop principale ---
    costo_attuale = costo_iniziale
    costo_migliore = costo_iniziale  # traccia il miglior costo raggiunto (per SA)
    swap_accettati = []
    iterazioni_senza_miglioramento = 0
    sa_attivo = temperatura_iniziale > 0
    T = temperatura_iniziale
    max_stallo = 500 if sa_attivo else 200
    fase_hc_tail = False  # True quando SA converge e si passa a HC finale

    # Indice per ricerca veloce
    celle_per_giorno = {}
    celle_per_turno = {}
    for i, c in enumerate(celle_swap):
        celle_per_giorno.setdefault(c['giorno'], []).append(i)
        celle_per_turno.setdefault(c['turno_id'], []).append(i)

    for it in range(max_iterazioni):
        if iterazioni_senza_miglioramento >= max_stallo:
            break

        # Genera swap candidato (50/50 tipo 1 vs tipo 2)
        if random.random() < 0.5:
            # Tipo 1: stesso giorno, turni diversi
            giorni_con_multi = [g for g, idxs in celle_per_giorno.items() if len(idxs) >= 2]
            if not giorni_con_multi:
                iterazioni_senza_miglioramento += 1
                continue
            g = random.choice(giorni_con_multi)
            i1, i2 = random.sample(celle_per_giorno[g], 2)
        else:
            # Tipo 2: stesso turno, giorni diversi
            turni_con_multi = [t for t, idxs in celle_per_turno.items() if len(idxs) >= 2]
            if not turni_con_multi:
                iterazioni_senza_miglioramento += 1
                continue
            t = random.choice(turni_con_multi)
            i1, i2 = random.sample(celle_per_turno[t], 2)

        c1 = celle_swap[i1]
        c2 = celle_swap[i2]

        # Gli utenti devono essere diversi
        if c1['user_id'] == c2['user_id']:
            iterazioni_senza_miglioramento += 1
            continue

        uid_a = c1['user_id']
        uid_b = c2['user_id']

        # --- Simula swap: rimuovi entrambi dagli stati ---
        t1_info = turni_info_map.get(c1['turno_id'])
        t2_info = turni_info_map.get(c2['turno_id'])
        if not t1_info or not t2_info:
            iterazioni_senza_miglioramento += 1
            continue

        _rimuovi_da_stato(stati[uid_a], t1_info, c1['giorno'], flag_map, giorno_tipo)
        _rimuovi_da_stato(stati[uid_b], t2_info, c2['giorno'], flag_map, giorno_tipo)

        # Verifica vincoli hard per le nuove posizioni
        ok_a = _verifica_vincoli_hard(
            uid_a, c2['turno_id'], c2['giorno'], stati,
            vincoli_g, vincoli_utente_cache, vincoli_solver_list,
            vs_utente_cache, esclusioni_cache, flag_map,
            indisponibilita, turni_info_map, giorno_tipo,
            turni_dovuti, calendario_id, escludi_regole
        )
        ok_b = _verifica_vincoli_hard(
            uid_b, c1['turno_id'], c1['giorno'], stati,
            vincoli_g, vincoli_utente_cache, vincoli_solver_list,
            vs_utente_cache, esclusioni_cache, flag_map,
            indisponibilita, turni_info_map, giorno_tipo,
            turni_dovuti, calendario_id, escludi_regole
        )

        if not ok_a or not ok_b:
            # Ripristina stati
            _aggiungi_a_stato(stati[uid_a], t1_info, c1['giorno'], flag_map, giorno_tipo)
            _aggiungi_a_stato(stati[uid_b], t2_info, c2['giorno'], flag_map, giorno_tipo)
            iterazioni_senza_miglioramento += 1
            continue

        # Aggiungi nelle nuove posizioni
        _aggiungi_a_stato(stati[uid_a], t2_info, c2['giorno'], flag_map, giorno_tipo)
        _aggiungi_a_stato(stati[uid_b], t1_info, c1['giorno'], flag_map, giorno_tipo)

        # Calcola nuovo costo
        costo_nuovo = calcola_costo_totale(
            stati, pesi, ref_id=ref_id,
            quote_ore=quote_ore, quote_festivi=quote_festivi,
            quote_peso=quote_peso, quote_flag=quote_flag,
            quote_peso_flag=quote_peso_flag,
            stati_wd=stati_wd
        )

        # --- Criterio di accettazione ---
        accetta = False
        if costo_nuovo < costo_attuale:
            accetta = True
        elif T > 0:
            # Simulated Annealing: accetta peggioramenti con probabilita'
            delta = costo_nuovo - costo_attuale
            try:
                accetta = random.random() < math.exp(-delta / T)
            except (OverflowError, ZeroDivisionError):
                accetta = False

        if accetta:
            costo_attuale = costo_nuovo
            if costo_nuovo < costo_migliore:
                costo_migliore = costo_nuovo
            swap_accettati.append({
                'cella1': {'ass_id': c1['id'], 'turno_id': c1['turno_id'],
                           'giorno': c1['giorno'], 'user_id_prima': uid_a,
                           'user_id_dopo': uid_b},
                'cella2': {'ass_id': c2['id'], 'turno_id': c2['turno_id'],
                           'giorno': c2['giorno'], 'user_id_prima': uid_b,
                           'user_id_dopo': uid_a},
            })
            c1['user_id'] = uid_b
            c2['user_id'] = uid_a
            iterazioni_senza_miglioramento = 0
        else:
            # Rifiuta swap: ripristina stati
            _rimuovi_da_stato(stati[uid_a], t2_info, c2['giorno'], flag_map, giorno_tipo)
            _rimuovi_da_stato(stati[uid_b], t1_info, c1['giorno'], flag_map, giorno_tipo)
            _aggiungi_a_stato(stati[uid_a], t1_info, c1['giorno'], flag_map, giorno_tipo)
            _aggiungi_a_stato(stati[uid_b], t2_info, c2['giorno'], flag_map, giorno_tipo)
            iterazioni_senza_miglioramento += 1

        # --- Cooling (SA) ---
        if T > 0:
            T *= raffreddamento
            if T < temperatura_minima:
                T = 0.0
                # SA convergenza: tail-pass HC per rifinitura
                if not fase_hc_tail:
                    fase_hc_tail = True
                    iterazioni_senza_miglioramento = 0
                    max_stallo = 200  # HC tail-pass con stallo standard

    # --- Risultato ---
    durata_ms = int((time.time() - t_start) * 1000)
    delta_pct = ((costo_iniziale - costo_attuale) / max(costo_iniziale, 0.001)) * 100

    risultato = {
        'ok': True,
        'swap_count': len(swap_accettati),
        'costo_iniziale': round(costo_iniziale, 6),
        'costo_finale': round(costo_attuale, 6),
        'delta_pct': round(delta_pct, 2),
        'durata_ms': durata_ms,
        'preview': preview,
        'modalita': 'sa' if sa_attivo else 'hc',
    }

    if preview:
        risultato['swaps'] = swap_accettati
        return risultato

    # --- Applica swap al DB ---
    dati_prec_history = []
    dati_nuovi_history = []

    for swap in swap_accettati:
        for cella_info in [swap['cella1'], swap['cella2']]:
            ass_id = cella_info['ass_id']
            nuovo_uid = cella_info.get('user_id_dopo')

            precedente = query_one(
                "SELECT * FROM assegnazioni_turni WHERE id=?", (ass_id,)
            )

            execute_write(
                "UPDATE assegnazioni_turni SET user_id=?, updated_at=datetime('now'), "
                "updated_by=? WHERE id=?",
                (nuovo_uid, user_id_chiamante, ass_id)
            )

            nuova = query_one(
                "SELECT * FROM assegnazioni_turni WHERE id=?", (ass_id,)
            )

            dati_prec_history.append({
                'tabella': 'assegnazioni_turni',
                'record_id': ass_id,
                'dati': dict(precedente) if precedente else None,
            })
            dati_nuovi_history.append({
                'tabella': 'assegnazioni_turni',
                'record_id': ass_id,
                'dati': dict(nuova),
            })

    # Ri-validazione conflitti
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

    # History: singolo step composto
    if dati_prec_history:
        aggiungi_step(
            calendario_id, 'optimizer', 0,
            dati_prec_history, dati_nuovi_history,
            user_id_chiamante
        )

    return risultato
