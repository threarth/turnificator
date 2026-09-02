"""
config_snapshot.py — Snapshot e lettura di TUTTA la configurazione
che deve rimanere congelata dentro un calendario.

Contenuto del JSON config_snapshot:
- vincoli_globali: [{chiave, valore}]
- vincoli_utente: [{user_id, chiave, valore, note}]
- vincoli_solver: [{tipo, ref_id, max_n, is_active}]
- vincoli_solver_utente: [{user_id, tipo, ref_id, max_n, note}]
- giorni_esclusi: [{user_id, giorni}]  (giorni = array di day-of-week 0=Lun..6=Dom)
- accesso_turni: [{manager_id, preset_turno_id}]
- accesso_utenti: [{manager_id, user_id}]
- flag_turno: [{id, nome, parent_id, peso_turno, ore_turno,
                 ore_primo_giorno, ore_ultimo_giorno, mostra_in_struttura,
                 orario_inizio, orario_fine, pausa_minuti,
                 durata_netta_minuti, durata_totale_minuti, tipo}]
- tipi_qualitativo: [{id, nome, descrizione, carico_lavoro}]
- tipi_richiesta: [{id, sigla, descrizione, tipo, counting_flag, flag_id,
                    ore_default, ordine}]
- regole_conflitto: le regole attive, nella forma di validatori.snapshot_regole()
- conteggi_context: [{id, label, flag_nome, giorno_settimana, negato, attivo}]

Nota: esclusioni_manuali e celle_bloccate sono per-calendario (campi JSON in
tabella calendari), non nella config globale → non servono nello snapshot.
Solver e optimizer li leggono direttamente dal record calendario.
"""

import json

from app.db import query_all, query_one
from app.services.validatori import snapshot_regole

# Valori di default per l'appearance di un preset struttura
APPEARANCE_DEFAULT = {
    'festivi_bg':             '#fff3cd',
    'superfestivi_bg':        '#f8d7da',
    'prima_riga_bg':          '#f8f9fa',
    'cella_bordo_colore':     '#dee2e6',
    'cella_bordo_spessore':   1,
    'bordo_esterno_colore':   '#adb5bd',
    'bordo_esterno_spessore': 2,
}


def _conteggi_context():
    """
    I conteggi del context menu, che vivono come JSON in `config`.

    Returns:
        list: elenco dei conteggi, vuoto se non configurati o illeggibili.
    """
    riga = query_one("SELECT valore FROM config WHERE chiave = 'conteggi_context'")
    if not (riga and riga['valore']):
        return []

    try:
        return json.loads(riga['valore'])
    except (json.JSONDecodeError, TypeError):
        return []


def crea_config_snapshot(preset_id=None):
    """
    Crea un JSON snapshot di tutta la configurazione corrente.

    Args:
        preset_id: ID del preset struttura — necessario per includere
                   esclusioni_turno e posti_fissi specifici del preset.
    """
    snap = {
        'vincoli_globali': [
            dict(r) for r in query_all(
                "SELECT chiave, valore FROM vincoli_globali WHERE is_active=1"
            )
        ],
        'vincoli_utente': [
            dict(r) for r in query_all(
                "SELECT user_id, chiave, valore, note FROM vincoli_utente"
            )
        ],
        'vincoli_solver': [
            dict(r) for r in query_all(
                "SELECT tipo, ref_id, max_n FROM vincoli_solver WHERE is_active=1"
            )
        ],
        'vincoli_solver_utente': [
            dict(r) for r in query_all(
                "SELECT user_id, tipo, ref_id, max_n, note FROM vincoli_solver_utente"
            )
        ],
        'giorni_esclusi': [
            {'user_id': r['id'], 'giorni': json.loads(r['giorni_esclusi'] or '[]')}
            for r in query_all(
                "SELECT id, giorni_esclusi FROM users "
                "WHERE is_active=1 AND giorni_esclusi != '[]'"
            )
        ],
        'accesso_turni': [
            dict(r) for r in query_all(
                "SELECT manager_id, preset_turno_id FROM manager_accesso_turni"
            )
        ],
        'accesso_utenti': [
            dict(r) for r in query_all(
                "SELECT manager_id, user_id FROM manager_accesso_utenti"
            )
        ],
        'flag_turno': [
            dict(r) for r in query_all(
                "SELECT id, nome, parent_id, peso_turno, ore_turno, "
                "ore_primo_giorno, ore_ultimo_giorno, mostra_in_struttura, "
                "tipo, orario_inizio, orario_fine, pausa_minuti, "
                "durata_netta_minuti, durata_totale_minuti "
                "FROM flag_turno"
            )
        ],
        'tipi_qualitativo': [
            dict(r) for r in query_all(
                "SELECT id, nome, descrizione, carico_lavoro FROM tipi_qualitativo"
            )
        ],
        'tipi_richiesta': [
            dict(r) for r in query_all(
                "SELECT id, sigla, descrizione, tipo, counting_flag, flag_id, "
                "ore_default, ordine FROM tipi_richiesta"
            )
        ],
        # Le regole hanno la forma che validatori sa gia' rileggere: qui si
        # riusa quella, invece di duplicarne il formato. snapshot_regole()
        # serializza gia' per la colonna regole_snapshot, quindi va riletta.
        'regole_conflitto': json.loads(snapshot_regole()),
        'conteggi_context': _conteggi_context(),
    }

    # Dati specifici del preset
    if preset_id is not None:
        snap['esclusioni_turno'] = [
            dict(r) for r in query_all(
                "SELECT user_id, tipo, target_id, eccezioni "
                "FROM preset_esclusioni_turno_per_utente WHERE preset_id=?",
                (preset_id,)
            )
        ]
        posti_rows = query_all(
            """SELECT pf.id, pf.preset_turno_id, pf.giorno_settimana,
                      pf.nome, pf.is_active, pf.manager_id
               FROM posti_fissi pf
               WHERE pf.preset_id = ?
               ORDER BY pf.giorno_settimana, pf.preset_turno_id""",
            (preset_id,)
        )
        posti_snap = []
        for pf in posti_rows:
            utenti = query_all(
                "SELECT user_id, ordine FROM posti_fissi_utenti "
                "WHERE posto_fisso_id=? ORDER BY ordine",
                (pf['id'],)
            )
            posti_snap.append({
                'id': pf['id'],
                'preset_turno_id': pf['preset_turno_id'],
                'giorno_settimana': pf['giorno_settimana'],
                'nome': pf['nome'],
                'is_active': pf['is_active'],
                'manager_id': pf['manager_id'],
                'utenti': [u['user_id'] for u in utenti],
            })
        snap['posti_fissi'] = posti_snap
        # Appearance del preset
        preset_row = query_one("SELECT appearance FROM struttura_presets WHERE id=?", (preset_id,))
        raw_app = preset_row['appearance'] if preset_row else None
        try:
            appearance = json.loads(raw_app) if raw_app else {}
        except (json.JSONDecodeError, TypeError):
            appearance = {}
        snap['appearance'] = {**APPEARANCE_DEFAULT, **appearance}
    else:
        snap['esclusioni_turno'] = []
        snap['posti_fissi'] = []
        snap['appearance'] = APPEARANCE_DEFAULT.copy()

    return json.dumps(snap)


def carica_appearance_snapshot(calendario_id):
    """Carica solo l'appearance_snapshot di un calendario. Ritorna dict con defaults."""
    row = query_one(
        "SELECT appearance_snapshot FROM calendari WHERE id=?",
        (calendario_id,)
    )
    raw = row['appearance_snapshot'] if row else None
    try:
        data = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        data = {}
    return {**APPEARANCE_DEFAULT, **data}


def carica_config_snapshot(calendario_id):
    """Carica il config_snapshot di un calendario. Ritorna dict o None."""
    row = query_one(
        "SELECT config_snapshot FROM calendari WHERE id=?",
        (calendario_id,)
    )
    if row and row['config_snapshot']:
        try:
            return json.loads(row['config_snapshot'])
        except (json.JSONDecodeError, TypeError):
            pass
    return None


# ---------------------------------------------------------------------------
# Helper per estrarre dati dallo snapshot (usati da solver, accesso, ecc.)
# ---------------------------------------------------------------------------

def snap_vincoli_globali(snap):
    """Ritorna dict chiave→int dai vincoli globali dello snapshot."""
    if not snap:
        return {}
    vincoli = {}
    for r in snap.get('vincoli_globali', []):
        try:
            vincoli[r['chiave']] = int(r['valore'])
        except (ValueError, TypeError):
            vincoli[r['chiave']] = 0
    return vincoli


def snap_vincoli_utente(snap):
    """Ritorna dict user_id→{chiave→int} dagli override per utente."""
    if not snap:
        return {}
    cache = {}
    for r in snap.get('vincoli_utente', []):
        uid = r['user_id']
        if uid not in cache:
            cache[uid] = {}
        try:
            cache[uid][r['chiave']] = int(r['valore'])
        except (ValueError, TypeError):
            cache[uid][r['chiave']] = 0
    return cache


def snap_vincoli_solver(snap):
    """Ritorna lista di dict {tipo, ref_id, max_n}."""
    if not snap:
        return []
    return snap.get('vincoli_solver', [])


def snap_vincoli_solver_utente(snap):
    """Ritorna dict (user_id, tipo, ref_id) → max_n."""
    if not snap:
        return {}
    cache = {}
    for r in snap.get('vincoli_solver_utente', []):
        cache[(r['user_id'], r['tipo'], r['ref_id'])] = r['max_n']
    return cache


def snap_giorni_esclusi(snap):
    """Ritorna dict user_id → list di day-of-week esclusi (0=Dom..6=Sab)."""
    if not snap:
        return {}
    cache = {}
    for r in snap.get('giorni_esclusi', []):
        giorni = r.get('giorni', [])
        if giorni:
            cache[r['user_id']] = giorni
    return cache


def snap_esclusioni_turno(snap):
    """
    Ritorna dict user_id → {'turno': set(target_id), 'gruppo': set(target_id),
                             'sovragruppo': set(target_id),
                             'eccezioni': set(target_id figli esenti)}.
    """
    if not snap:
        return {}
    cache = {}
    for r in snap.get('esclusioni_turno', []):
        uid = r['user_id']
        if uid not in cache:
            cache[uid] = {
                'turno': set(), 'gruppo': set(), 'sovragruppo': set(),
                'eccezioni': set(),
            }
        tipo = r.get('tipo', '')
        if tipo in cache[uid]:
            cache[uid][tipo].add(r['target_id'])
        # Eccezioni: target_id figli esenti dall'esclusione
        ecc_raw = r.get('eccezioni', '[]')
        if isinstance(ecc_raw, str):
            try:
                ecc = json.loads(ecc_raw)
            except (json.JSONDecodeError, TypeError):
                ecc = []
        else:
            ecc = ecc_raw or []
        for e in ecc:
            cache[uid]['eccezioni'].add(e)
    return cache


def snap_tipi_qualitativo(snap):
    """
    I tipi qualitativi congelati, come dict id→riga.

    Args:
        snap (dict|None): snapshot del calendario.

    Returns:
        dict: {id → {nome, descrizione, carico_lavoro}}, vuoto senza snapshot.
    """
    if not snap:
        return {}
    return {r['id']: r for r in snap.get('tipi_qualitativo', [])}


def snap_tipi_richiesta(snap):
    """
    I tipi richiesta congelati, come dict id→riga.

    Serve a rileggere un desiderata con il significato che aveva quando il
    calendario e' stato creato: se poi qualcuno cambia `counting_flag` o il
    flag associato, le ore gia' calcolate non devono cambiare sotto i piedi.

    Args:
        snap (dict|None): snapshot del calendario.

    Returns:
        dict: {id → riga tipi_richiesta}, vuoto senza snapshot.
    """
    if not snap:
        return {}
    return {r['id']: r for r in snap.get('tipi_richiesta', [])}


def snap_conteggi_context(snap):
    """
    I conteggi del context menu congelati.

    Args:
        snap (dict|None): snapshot del calendario.

    Returns:
        list: elenco dei conteggi, vuoto senza snapshot.
    """
    if not snap:
        return []
    return snap.get('conteggi_context', [])


def snap_regole_conflitto(snap):
    """
    Le regole di conflitto congelate, gia' filtrate sulle attive.

    Args:
        snap (dict|None): snapshot del calendario.

    Returns:
        list: regole attive, vuoto senza snapshot.
    """
    if not snap:
        return []
    return [r for r in snap.get('regole_conflitto', []) if r.get('is_active', 1)]


def snap_flag_map(snap):
    """Ritorna dict flag_id→{parent_id, nome, ...} per risalita gerarchia."""
    if not snap:
        return {}
    fmap = {}
    for f in snap.get('flag_turno', []):
        fmap[f['id']] = f
    return fmap


def snap_accesso_turni(snap):
    """Ritorna lista di {manager_id, preset_turno_id}."""
    if not snap:
        return []
    return snap.get('accesso_turni', [])


def snap_accesso_utenti(snap):
    """Ritorna lista di {manager_id, user_id}."""
    if not snap:
        return []
    return snap.get('accesso_utenti', [])


def snap_manager_puo_turno(snap, manager_id, preset_turno_id):
    """True se il manager può operare su questo turno secondo lo snapshot."""
    rows = snap_accesso_turni(snap)
    # Sentinel check: manager_id=0 per questo turno = ristretto a nessuno
    for r in rows:
        if r['preset_turno_id'] == preset_turno_id and r['manager_id'] == 0:
            return False
    # Turno senza righe = "Tutti"
    has_rows = any(r['preset_turno_id'] == preset_turno_id for r in rows)
    if not has_rows:
        return True
    # Ha righe → check se questo manager è nella lista
    return any(
        r['preset_turno_id'] == preset_turno_id and r['manager_id'] == manager_id
        for r in rows
    )


def snap_manager_puo_utente(snap, manager_id, user_id):
    """True se il manager può operare su questo utente secondo lo snapshot."""
    rows = snap_accesso_utenti(snap)
    # Sentinel check
    for r in rows:
        if r['user_id'] == user_id and r['manager_id'] == 0:
            return False
    # Utente senza righe = "Tutti"
    has_rows = any(r['user_id'] == user_id for r in rows)
    if not has_rows:
        return True
    return any(
        r['user_id'] == user_id and r['manager_id'] == manager_id
        for r in rows
    )
