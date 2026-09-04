"""
app/services/validatori.py — regole di business per l'inserimento dei turni.

Tutte le regole sono configurabili via tabella regole_conflitto.
Nessuna regola hardcoded. Le regole usano flag semantici per il matching.

tipo_regola:
  - tipo_vs_tipo: conflitto turno A vs turno B (flag-based)
  - desiderata_mismatch: flag richiesto ≠ flag assegnato
  - desiderata_assenza_mismatch: assegnato con richiesta assenza
  - desiderata_composizione_parziale: al lavoratore e' arrivato un pezzo
    della fascia che aveva chiesto, e ne mancano altri

valida_assegnazione() restituisce:
  - conflitti: lista di dict con id regola, severità, blocca_inserimento
  - bloccato: True se almeno una regola con blocca_inserimento è attiva
  - avviso_domani: bool

get_disponibili() restituisce lista lavoratori con i loro conflitti.
"""

import json

from app.db import query_one, query_all
from app.services.fasce_orarie import (
    COPERTURA_MATCH, COPERTURA_MISMATCH, COPERTURA_PARZIALE,
    carica_mappa_flag, catena_antenati, copertura_richiesta
)


# ---------------------------------------------------------------------------
# Tipi di regola
# ---------------------------------------------------------------------------

# Il codice li cerca per nome nella colonna regole_conflitto.tipo_regola:
# sono l'interfaccia fra la tabella e chi la interroga.
TIPO_REGOLA_TIPO_VS_TIPO = 'tipo_vs_tipo'
TIPO_REGOLA_DESIDERATA_MISMATCH = 'desiderata_mismatch'
TIPO_REGOLA_DESIDERATA_ASSENZA = 'desiderata_assenza_mismatch'
TIPO_REGOLA_COMPOSIZIONE_PARZIALE = 'desiderata_composizione_parziale'

TIPI_REGOLA = (
    TIPO_REGOLA_TIPO_VS_TIPO,
    TIPO_REGOLA_DESIDERATA_MISMATCH,
    TIPO_REGOLA_DESIDERATA_ASSENZA,
    TIPO_REGOLA_COMPOSIZIONE_PARZIALE,
)

# Le regole che guardano il desiderata del lavoratore, non gli altri turni.
TIPI_REGOLA_DESIDERATA = (
    TIPO_REGOLA_DESIDERATA_MISMATCH,
    TIPO_REGOLA_DESIDERATA_ASSENZA,
    TIPO_REGOLA_COMPOSIZIONE_PARZIALE,
)

# Aspetto e gravita' di serie della regola sul parziale: un avviso tenue,
# perche' una composizione a meta' non e' un errore.
STILE_COMPOSIZIONE_PARZIALE = (
    '{"backgroundColor":"#e3f2fd","color":"#1565c0","fontStyle":"italic"}'
)
PESO_COMPOSIZIONE_PARZIALE = 1.0


# ---------------------------------------------------------------------------
# Gerarchia dei flag
# ---------------------------------------------------------------------------

def _flag_matcha(flag_id_entita, flag_id_regola, mappa_flag):
    """
    Il flag di un'entita' soddisfa il flag richiesto da una regola?

    Vale anche per discendenza: una regola sul concetto `notturno` matcha
    ogni fascia che ne discende, comunque l'abbiano rinominata.

    Args:
        flag_id_entita (int|None): flag dell'entita'; None non matcha nulla.
        flag_id_regola (int|None): flag della regola; None e' un jolly.
        mappa_flag (dict): mappa id → flag della configurazione in vigore.

    Returns:
        bool: True se la regola si applica.
    """
    if flag_id_regola is None:
        return True
    if flag_id_entita is None:
        return False

    return flag_id_regola in catena_antenati(flag_id_entita, mappa_flag)


def _flag_nome_matcha(flag_nome_entita, flag_id_regola, mappa_flag):
    """
    Come _flag_matcha, partendo dal nome invece che dall'id.

    Gli snapshot dei calendari portano il nome del flag, non il suo id.

    Args:
        flag_nome_entita (str|None): nome del flag dell'entita'.
        flag_id_regola (int|None): flag della regola; None e' un jolly.
        mappa_flag (dict): mappa id → flag della configurazione in vigore.

    Returns:
        bool: True se la regola si applica.
    """
    if flag_id_regola is None:
        return True
    if not flag_nome_entita:
        return False

    for fid, fdata in mappa_flag.items():
        if fdata['nome'] == flag_nome_entita:
            return _flag_matcha(fid, flag_id_regola, mappa_flag)

    return False


# ---------------------------------------------------------------------------
# Caricamento regole
# ---------------------------------------------------------------------------

def _get_regole_attive_db():
    """Carica tutte le regole conflitto attive dal DB."""
    return query_all(
        "SELECT rc.*, "
        "  fa.nome AS flag_a_nome, fb.nome AS flag_b_nome "
        "FROM regole_conflitto rc "
        "LEFT JOIN flag_turno fa ON rc.flag_a_id = fa.id "
        "LEFT JOIN flag_turno fb ON rc.flag_b_id = fb.id "
        "WHERE rc.is_active = 1 "
        "ORDER BY rc.id",
        ()
    )


def _get_regole_attive(calendario_id=None):
    """
    Carica le regole conflitto per un calendario.
    Se il calendario ha uno snapshot non vuoto, usa quello.
    Altrimenti fallback alle regole live dal DB.
    """
    if calendario_id is not None:
        cal = query_one(
            "SELECT regole_snapshot FROM calendari WHERE id=?",
            (calendario_id,)
        )
        if cal and cal['regole_snapshot']:
            snap = json.loads(cal['regole_snapshot'])
            if snap:
                # Filtra regole disattivate nello snapshot
                return [r for r in snap if r.get('is_active', 1)]
    return _get_regole_attive_db()


def snapshot_regole():
    """
    Crea uno snapshot JSON delle regole conflitto attive.
    Usato al momento della creazione del calendario.
    """
    regole = _get_regole_attive_db()
    snap = []
    for r in regole:
        snap.append({
            'id': r['id'],
            'nome': r['nome'],
            'tipo_regola': r['tipo_regola'],
            'flag_a_id': r.get('flag_a_id'),
            'flag_b_id': r.get('flag_b_id'),
            'flag_a_nome': r.get('flag_a_nome'),
            'flag_b_nome': r.get('flag_b_nome'),
            'offset_giorni': r['offset_giorni'],
            'categoria': r['categoria'],
            'stile': r['stile'],
            'blocca_inserimento': r['blocca_inserimento'],
            'peso_numerico': r['peso_numerico'],
        })
    return json.dumps(snap)


# ---------------------------------------------------------------------------
# Helpers turno/desiderata
# ---------------------------------------------------------------------------

def _get_info_turno(turno_id):
    """
    Restituisce info del turno dallo snapshot calendario_turni.
    Include flag_nome per matching basato su flag.
    """
    row = query_one(
        "SELECT flag_id, flag_nome, gruppo_id, "
        "       apri_festivi, apri_superfestivi, aperture_straordinarie "
        "FROM calendario_turni WHERE id = ?",
        (turno_id,)
    )
    if not row:
        raise ValueError(f'Turno {turno_id} non trovato.')
    ap_raw = row.get('aperture_straordinarie', '[]')
    try:
        ap = json.loads(ap_raw) if isinstance(ap_raw, str) else (ap_raw or [])
    except (json.JSONDecodeError, TypeError):
        ap = []
    return {
        'flag_id': row['flag_id'],
        'flag_nome': row.get('flag_nome'),
        'gruppo_id': row['gruppo_id'],
        'apri_festivi': row.get('apri_festivi', 0),
        'apri_superfestivi': row.get('apri_superfestivi', 0),
        'aperture_straordinarie': set(ap),
    }


def _get_assegnazioni_utente_giorno(calendario_id, user_id, giorno):
    """Tutte le assegnazioni di un lavoratore in un dato giorno."""
    return query_all(
        """
        SELECT at.id, at.turno_id, ct.flag_id, ct.gruppo_id,
               ct.flag_nome
        FROM assegnazioni_turni at
        JOIN calendario_turni ct ON at.turno_id = ct.id
        WHERE at.calendario_id = ?
          AND at.user_id = ?
          AND at.giorno = ?
        """,
        (calendario_id, user_id, giorno)
    )


def _get_working_desiderata(calendario_id, user_id, giorno):
    """Working desiderata di un lavoratore per un dato giorno, con flag."""
    return query_one(
        """
        SELECT wd.id, wd.tipo_richiesta_id,
               tr.sigla AS req_sigla, tr.tipo AS req_tipo,
               tr.counting_flag, tr.flag_id AS req_flag_id,
               ft.nome AS req_flag_nome
        FROM working_desiderata wd
        LEFT JOIN tipi_richiesta tr ON wd.tipo_richiesta_id = tr.id
        LEFT JOIN flag_turno ft ON tr.flag_id = ft.id
        WHERE wd.calendario_id = ? AND wd.user_id = ? AND wd.giorno = ?
        """,
        (calendario_id, user_id, giorno)
    )


def _get_desiderata_originale(calendario_id, user_id, giorno):
    """Desiderata originale con flag."""
    return query_one(
        """
        SELECT d.id, d.tipo_richiesta_id,
               tr.sigla AS req_sigla, tr.tipo AS req_tipo,
               tr.flag_id AS req_flag_id,
               ft.nome AS req_flag_nome
        FROM desiderata d
        LEFT JOIN tipi_richiesta tr ON d.tipo_richiesta_id = tr.id
        LEFT JOIN flag_turno ft ON tr.flag_id = ft.id
        WHERE d.calendario_id = ? AND d.user_id = ? AND d.giorno = ?
        """,
        (calendario_id, user_id, giorno)
    )


def _turno_chiuso(info_turno, calendario_id, giorno):
    """
    Verifica se un turno è chiuso su un dato giorno.
    Ritorna True se chiuso (festivo/superfestivo senza apertura).
    """
    if giorno in info_turno.get('aperture_straordinarie', set()):
        return False  # apertura straordinaria → APERTO
    gc = query_one(
        "SELECT tipo FROM giorni_calendario WHERE calendario_id=? AND giorno=?",
        (calendario_id, giorno)
    )
    if not gc:
        return False
    tipo = gc.get('tipo', 'normale')
    if tipo == 'festivo' and not info_turno.get('apri_festivi'):
        return True
    if tipo == 'superfestivo' and not info_turno.get('apri_superfestivi'):
        return True
    return False


def _congelato(calendario_id):
    cal = query_one(
        "SELECT desiderata_congelati FROM calendari WHERE id = ?",
        (calendario_id,)
    )
    return bool(cal and cal['desiderata_congelati'])


def _get_desiderata_ref(calendario_id, user_id, giorno):
    """Restituisce il desiderata di riferimento (WD se congelati, originale altrimenti)."""
    if _congelato(calendario_id):
        return _get_working_desiderata(calendario_id, user_id, giorno)
    return _get_desiderata_originale(calendario_id, user_id, giorno)


# ---------------------------------------------------------------------------
# Matching regole
# ---------------------------------------------------------------------------

def _valuta_tipo_vs_tipo(regole, flag_nuovo, ass_lista, mappa_flag, bidirezionale=True):
    """
    Valuta regole tipo_vs_tipo tra il turno nuovo e le assegnazioni esistenti.
    Restituisce lista di regole attivate (dict con id, categoria, stile, blocca, peso).

    bidirezionale=True → prova anche la direzione inversa (per offset=0, stesso giorno).
    bidirezionale=False → solo direzione A=nuovo, B=esistente (per offset=1, ordine temporale conta).
    """
    conflitti = []
    for r in regole:
        if r['tipo_regola'] != TIPO_REGOLA_TIPO_VS_TIPO:
            continue
        for a in ass_lista:
            flag_esistente = a.get('flag_nome')
            # Direzione: nuovo=A, esistente=B
            if (_flag_nome_matcha(flag_nuovo, r.get('flag_a_id'), mappa_flag)
                    and _flag_nome_matcha(flag_esistente, r.get('flag_b_id'), mappa_flag)):
                conflitti.append(_conflitto_da_regola(r))
                break
            # Direzione inversa: esistente=A, nuovo=B (solo per stesso giorno)
            if bidirezionale:
                if (_flag_nome_matcha(flag_esistente, r.get('flag_a_id'), mappa_flag)
                        and _flag_nome_matcha(flag_nuovo, r.get('flag_b_id'), mappa_flag)):
                    conflitti.append(_conflitto_da_regola(r))
                    break
    return conflitti


def _valuta_desiderata(regole, flag_turno, des_ref, mappa_flag, altri_flag=None):
    """
    Valuta le regole che guardano il desiderata del lavoratore.

    Args:
        regole (list): regole attive di tipo desiderata.
        flag_turno (str|None): fascia del turno che si sta valutando.
        des_ref (dict|None): richiesta del lavoratore per quel giorno.
        mappa_flag (dict): gerarchia in vigore.
        altri_flag (iterable|None): fasce gia' assegnate allo stesso
                                    lavoratore nello stesso giorno, che
                                    possono completare una composizione.

    Returns:
        list[dict]: regole attivate.
    """
    conflitti = []
    if not des_ref or not des_ref.get('tipo_richiesta_id'):
        return conflitti

    req_tipo = des_ref.get('req_tipo')
    req_flag_nome = des_ref.get('req_flag_nome')

    # La copertura si calcola una volta sola: le due regole sul lavorativo
    # sono due esiti della stessa domanda.
    copertura = None
    if req_tipo == 'lavorativo' and req_flag_nome and flag_turno:
        copertura = copertura_richiesta(
            flag_turno, des_ref.get('req_flag_id'), mappa_flag, altri_flag
        )

    for r in regole:
        if r['tipo_regola'] == TIPO_REGOLA_DESIDERATA_ASSENZA:
            # Attiva se il lavoratore ha un desiderata assenza
            if req_tipo == 'assenza':
                # Verifica che il flag del desiderata matchi flag_a della regola
                req_flag_id = des_ref.get('req_flag_id')
                if r.get('flag_a_id') is None or _flag_matcha(req_flag_id, r.get('flag_a_id'), mappa_flag):
                    conflitti.append(_conflitto_da_regola(r))

        elif r['tipo_regola'] == TIPO_REGOLA_DESIDERATA_MISMATCH:
            # Attiva se il turno e' un'altra cosa rispetto a quello chiesto.
            # Un pezzo di composizione non lo e': quello ha una regola sua.
            if copertura == COPERTURA_MISMATCH:
                conflitti.append(_conflitto_da_regola(r))

        elif r['tipo_regola'] == TIPO_REGOLA_COMPOSIZIONE_PARZIALE:
            # Attiva finche' la composizione e' incompleta.
            if copertura == COPERTURA_PARZIALE:
                conflitti.append(_conflitto_da_regola(r))

    return conflitti


def _conflitto_da_regola(r):
    """Estrae i campi rilevanti da una regola per il risultato conflitto."""
    return {
        'id': r['id'],
        'nome': r.get('nome', ''),
        'categoria': r.get('categoria', 'consigliata'),
        'stile': r.get('stile', '{}'),
        'blocca_inserimento': r.get('blocca_inserimento', 0),
        'peso_numerico': r.get('peso_numerico', 1.0),
        'tipo_regola': r.get('tipo_regola', ''),
    }


# ---------------------------------------------------------------------------
# Funzione principale di validazione
# ---------------------------------------------------------------------------

def valida_assegnazione(calendario_id, turno_id, user_id, giorno,
                        forza_inserimento=False):
    """
    Valuta i conflitti per l'inserimento di un lavoratore in un turno.

    Returns:
        dict:
            - 'conflitti' (list[dict]): regole attivate con id, categoria, stile, blocca
            - 'bloccato' (bool): True se c'è almeno un conflitto con blocca_inserimento
                                 e forza_inserimento=False
            - 'avviso_domani' (bool): True se regole offset=1 coinvolgono questo flag
    """
    # Import locale: config_snapshot importa snapshot_regole da qui.
    from app.services.config_snapshot import carica_config_snapshot

    mappa_flag = carica_mappa_flag(carica_config_snapshot(calendario_id))
    info_nuovo = _get_info_turno(turno_id)
    flag_nuovo = info_nuovo['flag_nome']

    regole = _get_regole_attive(calendario_id)
    conflitti = []

    # ── Turno chiuso ──
    if _turno_chiuso(info_nuovo, calendario_id, giorno):
        conflitti.append({
            'id': -2,
            'nome': 'Turno chiuso',
            'categoria': 'critica',
            'stile': '{"backgroundColor":"#e0e0e0","color":"#616161"}',
            'blocca_inserimento': 1,
            'peso_numerico': 100.0,
            'tipo_regola': 'turno_chiuso',
        })

    # Gli altri turni dello stesso giorno servono due volte: alle regole
    # tipo_vs_tipo e alla composizione, che si completa fra piu' celle.
    ass_oggi = [a for a in _get_assegnazioni_utente_giorno(calendario_id, user_id, giorno)
                if a['turno_id'] != turno_id]

    # ── Regole desiderata ──
    des_ref = _get_desiderata_ref(calendario_id, user_id, giorno)
    regole_des = [r for r in regole if r['tipo_regola'] in TIPI_REGOLA_DESIDERATA]
    conflitti.extend(_valuta_desiderata(
        regole_des, flag_nuovo, des_ref, mappa_flag,
        altri_flag=[a.get('flag_nome') for a in ass_oggi]
    ))

    # ── Regole tipo_vs_tipo offset=0 (stesso giorno) ──
    regole_0 = [r for r in regole if r['tipo_regola'] == TIPO_REGOLA_TIPO_VS_TIPO and r['offset_giorni'] == 0]
    conflitti.extend(_valuta_tipo_vs_tipo(regole_0, flag_nuovo, ass_oggi, mappa_flag))

    # ── Regole tipo_vs_tipo offset=1 (turno nuovo oggi=A, esistente domani=B) ──
    ass_domani = _get_assegnazioni_utente_giorno(calendario_id, user_id, giorno + 1)
    regole_1 = [r for r in regole if r['tipo_regola'] == TIPO_REGOLA_TIPO_VS_TIPO and r['offset_giorni'] == 1]
    conflitti.extend(_valuta_tipo_vs_tipo(regole_1, flag_nuovo, ass_domani, mappa_flag, bidirezionale=False))

    # ── Reverse: se ieri c'è un turno con regola offset=1, oggi è il "giorno dopo" ──
    if giorno > 1:
        ass_ieri = _get_assegnazioni_utente_giorno(calendario_id, user_id, giorno - 1)
        # Per ogni assegnazione di ieri, verifica se c'è una regola offset=1
        # dove ieri=A e oggi(nuovo)=B
        for r in regole_1:
            for a in ass_ieri:
                flag_ieri = a.get('flag_nome')
                if (_flag_nome_matcha(flag_ieri, r.get('flag_a_id'), mappa_flag)
                        and _flag_nome_matcha(flag_nuovo, r.get('flag_b_id'), mappa_flag)):
                    conflitti.append(_conflitto_da_regola(r))
                    break

    # Deduplica per id regola
    seen = set()
    conflitti_unici = []
    for c in conflitti:
        if c['id'] not in seen:
            seen.add(c['id'])
            conflitti_unici.append(c)

    # Bloccato?
    bloccato = (not forza_inserimento and
                any(c['blocca_inserimento'] for c in conflitti_unici))

    # avviso_domani: ci sono regole offset=1 che coinvolgono il flag di questo turno?
    avviso_domani = any(
        r['tipo_regola'] == TIPO_REGOLA_TIPO_VS_TIPO
        and r['offset_giorni'] == 1
        and _flag_nome_matcha(flag_nuovo, r.get('flag_a_id'), mappa_flag)
        for r in regole
    )

    return {
        'conflitti': conflitti_unici,
        'bloccato': bloccato,
        'avviso_domani': avviso_domani,
    }


# ---------------------------------------------------------------------------
# Calcolo codice colore cella (working desiderata)
# ---------------------------------------------------------------------------

def calcola_conflitto_wd(working_desiderata, flag_nome=None, mappa_flag=None,
                         altri_flag=None):
    """
    Il codice colore di una cella rispetto al desiderata del lavoratore.

    Args:
        working_desiderata (dict|None): richiesta del lavoratore per quel giorno.
        flag_nome (str|None): fascia del turno assegnato.
        mappa_flag (dict|None): gerarchia in vigore; senza, si usa quella
                                corrente, che e' il caso dei chiamanti che non
                                partono da un calendario.
        altri_flag (iterable|None): fasce gia' assegnate allo stesso lavoratore
                                    nello stesso giorno, che possono completare
                                    una composizione.

    Returns:
        str: 'free', 'forced', 'match', 'parziale' o 'mismatch'.
    """
    if not working_desiderata or not working_desiderata.get('tipo_richiesta_id'):
        return 'free'

    req_tipo = working_desiderata.get('req_tipo')
    if req_tipo == 'assenza':
        return 'forced'

    # Match basato su flag
    req_flag_id = working_desiderata.get('req_flag_id')
    if req_flag_id and flag_nome:
        if mappa_flag is None:
            mappa_flag = carica_mappa_flag()
        return copertura_richiesta(flag_nome, req_flag_id, mappa_flag, altri_flag)

    return COPERTURA_MATCH


def calcola_conflitto(flag_nome, working_desiderata, forzato, mappa_flag=None):
    """Retrocompatibilità."""
    if forzato:
        return 'forced'
    return calcola_conflitto_wd(working_desiderata, flag_nome, mappa_flag)


# ---------------------------------------------------------------------------
# Lista lavoratori disponibili per dropdown
# ---------------------------------------------------------------------------

def get_disponibili(calendario_id, turno_id, giorno, ignora_notte=False):
    """
    Restituisce la lista dei lavoratori disponibili per un dato turno/giorno.
    Include conflitti come lista di regole attivate con severità.
    """
    # Import locale: config_snapshot importa snapshot_regole da qui.
    from app.services.config_snapshot import carica_config_snapshot

    mappa_flag = carica_mappa_flag(carica_config_snapshot(calendario_id))
    info_nuovo = _get_info_turno(turno_id)
    flag_nuovo = info_nuovo['flag_nome']

    # Check turno chiuso (uguale per tutti i lavoratori)
    chiuso = _turno_chiuso(info_nuovo, calendario_id, giorno)

    regole = _get_regole_attive(calendario_id)

    tutti = query_all(
        "SELECT id AS user_id, sigla FROM users "
        "WHERE is_active=1 AND escluso_turni=0 AND role IN ('basic','manager','admin') ORDER BY sigla",
        ()
    )

    disponibili = []

    for lav in tutti:
        uid = lav['user_id']
        sigla = lav['sigla']

        conflitti = []

        # Turno chiuso
        if chiuso:
            conflitti.append({
                'id': -2,
                'nome': 'Turno chiuso',
                'categoria': 'critica',
                'stile': '{"backgroundColor":"#e0e0e0","color":"#616161"}',
                'blocca_inserimento': 1,
                'peso_numerico': 100.0,
                'tipo_regola': 'turno_chiuso',
            })

        # I turni che il lavoratore ha gia' quel giorno: servono alle regole
        # tipo_vs_tipo e alla composizione, che si completa fra piu' celle.
        ass_oggi = _get_assegnazioni_utente_giorno(calendario_id, uid, giorno)
        flag_oggi = [a.get('flag_nome') for a in ass_oggi]

        # Regole desiderata
        des_ref = _get_desiderata_ref(calendario_id, uid, giorno)
        regole_des = [r for r in regole if r['tipo_regola'] in
                      TIPI_REGOLA_DESIDERATA]
        conflitti.extend(_valuta_desiderata(regole_des, flag_nuovo, des_ref,
                                            mappa_flag, altri_flag=flag_oggi))

        # Stesso giorno (offset=0)
        regole_0 = [r for r in regole if r['tipo_regola'] == TIPO_REGOLA_TIPO_VS_TIPO and r['offset_giorni'] == 0]
        conflitti.extend(_valuta_tipo_vs_tipo(regole_0, flag_nuovo, ass_oggi, mappa_flag))

        # Giorno precedente → regole offset=1 (ieri=A, oggi=B)
        if giorno > 1:
            ass_ieri = _get_assegnazioni_utente_giorno(calendario_id, uid, giorno - 1)
            regole_1 = [r for r in regole if r['tipo_regola'] == TIPO_REGOLA_TIPO_VS_TIPO and r['offset_giorni'] == 1]
            for r in regole_1:
                for a in ass_ieri:
                    flag_ieri = a.get('flag_nome')
                    if (_flag_nome_matcha(flag_ieri, r.get('flag_a_id'), mappa_flag)
                            and _flag_nome_matcha(flag_nuovo, r.get('flag_b_id'), mappa_flag)):
                        conflitti.append(_conflitto_da_regola(r))
                        break

        # Giorno successivo (offset=1)
        ass_domani = _get_assegnazioni_utente_giorno(calendario_id, uid, giorno + 1)
        regole_1_fwd = [r for r in regole if r['tipo_regola'] == TIPO_REGOLA_TIPO_VS_TIPO and r['offset_giorni'] == 1]
        conflitti.extend(_valuta_tipo_vs_tipo(regole_1_fwd, flag_nuovo, ass_domani, mappa_flag))

        # Deduplica
        seen = set()
        conflitti_unici = []
        for c in conflitti:
            if c['id'] not in seen:
                seen.add(c['id'])
                conflitti_unici.append(c)

        # Working desiderata per stato colore cella
        wd = _get_working_desiderata(calendario_id, uid, giorno)
        stato_wd = calcola_conflitto_wd(wd, flag_nuovo, mappa_flag, flag_oggi)

        # Bloccato da regola?
        bloccato = any(c['blocca_inserimento'] for c in conflitti_unici)

        # Priorità per ordinamento
        if bloccato:
            priorita = 4
            label = f'🚫 {sigla}'
        elif conflitti_unici:
            priorita = 3
            label = f'⚠ {sigla}'
        elif stato_wd == COPERTURA_MATCH:
            priorita = 1
            label = f'★ {sigla}'
        elif stato_wd == COPERTURA_PARZIALE:
            priorita = 1
            label = f'☆ {sigla}'
        elif stato_wd in (COPERTURA_MISMATCH, 'forced'):
            priorita = 2
            label = f'≠ {sigla}'
        else:
            priorita = 2
            label = f'  {sigla}'

        # Manteniamo conflitti_ids per retrocompatibilità frontend
        conflitti_ids = [c['id'] for c in conflitti_unici]

        disponibili.append({
            'user_id':       uid,
            'sigla':         sigla,
            'label':         label,
            'priorita':      priorita,
            'conflitti_ids': conflitti_ids,
            'conflitti':     conflitti_unici,
            'bloccato':      bloccato,
            'stato_wd':      stato_wd,
        })

    disponibili.sort(key=lambda x: (x['priorita'], x['sigla']))
    return disponibili
