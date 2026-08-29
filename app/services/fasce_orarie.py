"""
app/services/fasce_orarie.py — parametri orari delle fasce (flag_turno).

Nuova feature: orario di inizio/fine, pausa obbligatoria e durate sulle fasce
orarie, con ore turno e peso derivati dai soli orari.

Modello
-------
I flag_turno root (turno_tipo, diurno, notturno, guardia_24h) portano il
concetto, non sono agganciabili ai gruppi e non hanno orari. Le fasce orarie
sono i loro figli e portano gli orari concreti.

Il root `turno_tipo` non classifica nulla: e' l'unita' di misura con cui si
deriva il peso di ogni fascia. Cosi' il peso 1 delle fasce diurne e il peso 2
della notte emergono dagli orari, senza numeri scritti a mano.

Campi derivati (ricalcolati a ogni scrittura, mai digitati dall'utente):
    durata_netta_minuti  = orario_fine - orario_inizio, con sconfinamento
    durata_totale_minuti = durata netta + pausa obbligatoria
    ore_turno            = durata totale in ore decimali
    peso_turno           = durata netta / durata netta del turno tipo
"""

import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

MINUTI_PER_ORA = 60
ORE_PER_GIORNO = 24
MINUTI_PER_GIORNO = ORE_PER_GIORNO * MINUTI_PER_ORA

SEPARATORE_ORARIO = ':'
CIFRE_CAMPO_ORARIO = 2

# Pausa obbligatoria di default, in minuti. Si somma alla durata netta:
# una fascia 08:00-14:20 vale 6h20 di lavoro e 6h30 di durata totale.
PAUSA_DEFAULT_MINUTI = 10

# Durata netta di riferimento del turno tipo, usata solo come fallback
# quando il flag `turno_tipo` non e' presente in banca dati.
DURATA_TURNO_TIPO_DEFAULT_MINUTI = 380  # 6h20

# Nomi dei flag root. Sono l'unico riferimento stabile: le fasce figlie
# possono chiamarsi come vuole l'utente.
NOME_TURNO_TIPO = 'turno_tipo'
NOME_ROOT_DIURNO = 'diurno'
NOME_ROOT_NOTTURNO = 'notturno'
NOME_ROOT_GUARDIA = 'guardia_24h'

# Guardia contro gerarchie cicliche: nessun albero flag legittimo e' profondo
# piu' di pochi livelli.
PROFONDITA_MAX_GERARCHIA = 16


class FormatoOrarioNonValido(ValueError):
    """Orario non esprimibile come 'HH:MM' con ore 0-24 e minuti 0-59."""


# ---------------------------------------------------------------------------
# Conversione orari
# ---------------------------------------------------------------------------

def parse_orario(orario):
    """
    Converte un orario 'HH:MM' nei minuti trascorsi dalla mezzanotte.

    Accetta '24:00' come sinonimo di fine giornata (1440 minuti), perche' e'
    la forma naturale per una guardia che copre l'intera giornata.

    Args:
        orario (str): orario nel formato 'HH:MM'.

    Returns:
        int: minuti dalla mezzanotte (0-1440).

    Raises:
        FormatoOrarioNonValido: formato, tipo o intervallo non validi.
    """
    if not isinstance(orario, str):
        raise FormatoOrarioNonValido(f"orario non testuale: {orario!r}")

    parti = orario.strip().split(SEPARATORE_ORARIO)
    if len(parti) != CIFRE_CAMPO_ORARIO:
        raise FormatoOrarioNonValido(f"formato atteso HH:MM, ricevuto {orario!r}")

    try:
        ore, minuti = int(parti[0]), int(parti[1])
    except ValueError:
        raise FormatoOrarioNonValido(f"ore e minuti non numerici in {orario!r}")

    if not 0 <= ore <= ORE_PER_GIORNO:
        raise FormatoOrarioNonValido(f"ore fuori intervallo in {orario!r}")
    if not 0 <= minuti < MINUTI_PER_ORA:
        raise FormatoOrarioNonValido(f"minuti fuori intervallo in {orario!r}")

    totale = ore * MINUTI_PER_ORA + minuti
    if totale > MINUTI_PER_GIORNO:
        raise FormatoOrarioNonValido(f"orario oltre le 24:00 in {orario!r}")

    return totale


def formatta_orario(minuti):
    """
    Converte minuti dalla mezzanotte in 'HH:MM'.

    Args:
        minuti (int): minuti dalla mezzanotte (0-1440).

    Returns:
        str: orario nel formato 'HH:MM' ('24:00' per 1440).

    Raises:
        FormatoOrarioNonValido: valore fuori dall'intervallo di una giornata.
    """
    if minuti is None or not 0 <= minuti <= MINUTI_PER_GIORNO:
        raise FormatoOrarioNonValido(f"minuti fuori intervallo: {minuti!r}")

    return '{:02d}{}{:02d}'.format(
        minuti // MINUTI_PER_ORA, SEPARATORE_ORARIO, minuti % MINUTI_PER_ORA
    )


def formatta_durata(minuti):
    """
    Rende una durata in minuti nella forma 'HhMM' per log e interfacce.

    Args:
        minuti (int): durata in minuti, anche superiore alle 24 ore.

    Returns:
        str: durata leggibile, es. '6h20'. Stringa vuota se minuti e' None.
    """
    if minuti is None:
        return ''

    return '{}h{:02d}'.format(minuti // MINUTI_PER_ORA, minuti % MINUTI_PER_ORA)


# ---------------------------------------------------------------------------
# Durate, ore e peso
# ---------------------------------------------------------------------------

def calcola_durata_netta(orario_inizio, orario_fine):
    """
    Minuti di lavoro effettivo fra due orari, pausa esclusa.

    Gestisce lo sconfinamento oltre la mezzanotte: una fascia 20:00-08:40
    dura 12h40. Orari coincidenti valgono 24 ore, perche' nessun turno dura
    zero minuti: e' la forma con cui si esprime una guardia 00:00-00:00.

    Args:
        orario_inizio (str): orario di inizio 'HH:MM'.
        orario_fine (str): orario di fine 'HH:MM'.

    Returns:
        int: durata netta in minuti (1-1440).

    Raises:
        FormatoOrarioNonValido: uno dei due orari non e' valido.
    """
    inizio = parse_orario(orario_inizio)
    fine = parse_orario(orario_fine)

    durata = (fine - inizio) % MINUTI_PER_GIORNO

    return durata if durata > 0 else MINUTI_PER_GIORNO


def calcola_durata_totale(durata_netta_minuti, pausa_minuti):
    """
    Durata complessiva della fascia: lavoro effettivo piu' pausa obbligatoria.

    Args:
        durata_netta_minuti (int|None): minuti di lavoro effettivo.
        pausa_minuti (int|None): minuti di pausa obbligatoria.

    Returns:
        int|None: durata totale in minuti, None se la netta non e' nota.
    """
    if durata_netta_minuti is None:
        return None

    return durata_netta_minuti + (pausa_minuti or 0)


def calcola_ore_turno(durata_totale_minuti):
    """
    Durata totale espressa in ore decimali, la forma letta dal calcolo ore.

    Args:
        durata_totale_minuti (int|None): durata totale in minuti.

    Returns:
        float|None: ore decimali, None se la durata non e' nota.
    """
    if durata_totale_minuti is None:
        return None

    return durata_totale_minuti / MINUTI_PER_ORA


def calcola_peso(durata_netta_minuti, durata_netta_turno_tipo):
    """
    Peso della fascia, espresso in multipli del turno tipo.

    Usa le durate nette e non le totali: cosi' una fascia da 6h20 pesa
    esattamente 1 e una notte da 12h40 esattamente 2, senza che la pausa
    introduca decimali.

    Args:
        durata_netta_minuti (int|None): durata netta della fascia.
        durata_netta_turno_tipo (int|None): durata netta del turno tipo.

    Returns:
        float|None: peso della fascia, None se una delle due durate manca
                    o il turno tipo ha durata nulla.
    """
    if not durata_netta_minuti or not durata_netta_turno_tipo:
        return None

    return durata_netta_minuti / durata_netta_turno_tipo


def ricalcola_parametri(fascia, durata_netta_turno_tipo):
    """
    Ricalcola i campi derivati di una fascia a partire dai suoi orari.

    La durata netta viene dagli orari quando ci sono; in loro assenza si usa
    quella gia' memorizzata, che e' il caso del turno tipo (unita' di misura
    senza orari concreti). Se non c'e' ne' l'una ne' l'altra la fascia non ha
    parametri temporali e non viene toccata: e' il caso dei flag assenza.

    Args:
        fascia (dict): riga flag_turno, con orario_inizio, orario_fine,
                       durata_netta_minuti e pausa_minuti.
        durata_netta_turno_tipo (int|None): durata netta del turno tipo.

    Returns:
        dict|None: {durata_netta_minuti, durata_totale_minuti, ore_turno,
                    peso_turno}, oppure None se la fascia non ha durata.

    Raises:
        FormatoOrarioNonValido: gli orari presenti non sono validi.
    """
    inizio = fascia.get('orario_inizio')
    fine = fascia.get('orario_fine')

    if inizio and fine:
        netta = calcola_durata_netta(inizio, fine)
    else:
        netta = fascia.get('durata_netta_minuti')

    if netta is None:
        return None

    totale = calcola_durata_totale(netta, fascia.get('pausa_minuti'))

    return {
        'durata_netta_minuti': netta,
        'durata_totale_minuti': totale,
        'ore_turno': calcola_ore_turno(totale),
        'peso_turno': calcola_peso(netta, durata_netta_turno_tipo),
    }


def ricalcola_tutte(db):
    """
    Ricalcola durate, ore e peso di ogni fascia a partire da orari e pausa.

    Idempotente e auto-riparante: i campi derivati non si scrivono mai a
    mano, quindi ricalcolarli riallinea eventuali divergenze. Va invocata
    all'avvio e dopo ogni scrittura su un flag, perche' un peso stantio
    resterebbe a video fino al riavvio successivo.

    Lascia intatti i flag privi sia di orari sia di durata netta — i concetti
    root diversi da turno_tipo e i flag assenza — perche' li' un ricalcolo
    azzererebbe le ore inserite a mano prima delle fasce orarie.

    Args:
        db: connessione al database del tenant.
    """
    try:
        flag = [dict(r) for r in db.execute(
            "SELECT id, nome, orario_inizio, orario_fine, pausa_minuti, "
            "durata_netta_minuti FROM flag_turno"
        ).fetchall()]
    except Exception as e:
        log.warning('Lettura flag per il ricalcolo fasce fallita: %s', e)
        return

    netta_turno_tipo = next(
        (f['durata_netta_minuti'] for f in flag if f['nome'] == NOME_TURNO_TIPO),
        None
    ) or DURATA_TURNO_TIPO_DEFAULT_MINUTI

    try:
        for fascia in flag:
            try:
                derivati = ricalcola_parametri(fascia, netta_turno_tipo)
            except FormatoOrarioNonValido as e:
                log.warning(
                    "Fascia '%s': orari non validi, parametri non ricalcolati "
                    "(%s)", fascia['nome'], e
                )
                continue

            if derivati is None:
                continue

            db.execute(
                "UPDATE flag_turno SET durata_netta_minuti = ?, "
                "durata_totale_minuti = ?, ore_turno = ?, peso_turno = ? "
                "WHERE id = ?",
                (derivati['durata_netta_minuti'], derivati['durata_totale_minuti'],
                 derivati['ore_turno'], derivati['peso_turno'], fascia['id'])
            )

        db.commit()
    except Exception as e:
        db.rollback()
        log.warning('Ricalcolo parametri fasce fallito: %s', e)


# ---------------------------------------------------------------------------
# Gerarchia: appartenenza di una fascia a un concetto root
# ---------------------------------------------------------------------------

def costruisci_mappa_flag(righe):
    """
    Indicizza per id le righe flag, per le interrogazioni sulla gerarchia.

    Args:
        righe (iterable): righe con almeno id, nome e parent_id.

    Returns:
        dict: { id → dict della riga }.
    """
    return {riga['id']: dict(riga) for riga in righe}


def catena_antenati(flag_id, mappa_flag):
    """
    Set di id composto dal flag stesso e da tutti i suoi antenati.

    Args:
        flag_id (int|None): id del flag di partenza.
        mappa_flag (dict): mappa prodotta da costruisci_mappa_flag().

    Returns:
        set: id del flag e dei suoi antenati, vuoto se il flag e' ignoto.
    """
    antenati = set()
    corrente = flag_id
    profondita = 0

    while corrente is not None and corrente not in antenati:
        if profondita >= PROFONDITA_MAX_GERARCHIA:
            break
        antenati.add(corrente)
        riga = mappa_flag.get(corrente)
        corrente = riga['parent_id'] if riga else None
        profondita += 1

    return antenati


def discende_da(flag_id, nome_root, mappa_flag):
    """
    Verifica se un flag e' il concetto root indicato o una sua fascia.

    Il root stesso conta come match: i calendari creati prima delle fasce
    orarie agganciano i gruppi direttamente ai root (flag_nome='notturno'),
    e i loro snapshot non vengono riscritti.

    Args:
        flag_id (int|None): id del flag da verificare.
        nome_root (str): nome del concetto root, es. 'notturno'.
        mappa_flag (dict): mappa prodotta da costruisci_mappa_flag().

    Returns:
        bool: True se il flag appartiene a quel concetto.
    """
    if flag_id is None:
        return False

    return any(
        mappa_flag.get(antenato, {}).get('nome') == nome_root
        for antenato in catena_antenati(flag_id, mappa_flag)
    )


def discende_da_nome(flag_nome, nome_root, mappa_flag):
    """
    Come discende_da(), partendo dal nome del flag.

    Serve per gli snapshot in calendario_turni, che memorizzano flag_nome.

    Args:
        flag_nome (str|None): nome del flag da verificare.
        nome_root (str): nome del concetto root, es. 'notturno'.
        mappa_flag (dict): mappa prodotta da costruisci_mappa_flag().

    Returns:
        bool: True se il flag appartiene a quel concetto.
    """
    if not flag_nome:
        return False

    for flag_id, riga in mappa_flag.items():
        if riga.get('nome') == flag_nome:
            return discende_da(flag_id, nome_root, mappa_flag)

    return False


def carica_mappa_flag(config_snapshot=None):
    """
    Carica la gerarchia dei flag per le interrogazioni sulla discendenza.

    Preferisce lo snapshot di configurazione del calendario quando c'e': un
    calendario chiuso va riletto con la gerarchia con cui e' stato costruito,
    non con quella di oggi.

    Args:
        config_snapshot (dict|None): snapshot del calendario, se disponibile.

    Returns:
        dict: mappa { id → flag }, eventualmente vuota.
    """
    if config_snapshot and config_snapshot.get('flag_turno'):
        return costruisci_mappa_flag(config_snapshot['flag_turno'])

    # Import locale: cosi' la logica di calcolo resta usabile senza database.
    from app.db import query_all

    return costruisci_mappa_flag(
        query_all("SELECT id, nome, parent_id FROM flag_turno", ())
    )


def e_notturna(flag_nome, mappa_flag):
    """
    Scorciatoia leggibile per la domanda piu' frequente del codice chiamante:
    questa fascia e' una notte?

    Args:
        flag_nome (str|None): nome del flag della fascia.
        mappa_flag (dict): mappa prodotta da costruisci_mappa_flag().

    Returns:
        bool: True se la fascia discende dal concetto notturno.
    """
    return discende_da_nome(flag_nome, NOME_ROOT_NOTTURNO, mappa_flag)
