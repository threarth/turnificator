"""
app/services/configurazioni.py — configurazioni salvate e commutabili.

Nuova feature. Una configurazione e' l'intera impostazione del tenant —
fasce orarie, tipologie, tipi richiesta, regole, vincoli, conteggi —
congelata in uno snapshot, piu' la struttura turni che le corrisponde.
Attivarne una riporta le tabelle di configurazione a quello stato.

Perche' funzioni senza rompere i calendari gia' costruiti valgono due
invarianti:

1. **Gli id si conservano.** Il ripristino aggiorna le righe per id invece di
   ricrearle, perche' `gruppi.flag_id`, `tipi_richiesta.flag_id` e gli
   snapshot dei calendari puntano a quegli id.

2. **I nomi strutturali non cambiano.** `turno_tipo`, `notturno` e `diurno`
   sono cercati per nome dal codice — il primo per derivare i pesi, gli altri
   per riconoscere le notti — quindi restano uguali in ogni configurazione.
   Una configurazione che li omettesse verrebbe rifiutata.
"""

import json

from app.services.config_snapshot import crea_config_snapshot

# I concetti su cui il codice ragiona per nome: una configurazione non puo'
# ometterli, o il ricalcolo dei pesi e il riconoscimento delle notti
# perderebbero il riferimento.
NOMI_STRUTTURALI = ('turno_tipo', 'notturno', 'diurno')


class ConfigurazioneNonValida(ValueError):
    """La configurazione non e' applicabile: manca un invariante."""


def verifica_invarianti(snapshot):
    """
    Controlla che lo snapshot porti i concetti strutturali.

    Args:
        snapshot (dict): configurazione da applicare.

    Raises:
        ConfigurazioneNonValida: se manca uno dei nomi strutturali.
    """
    nomi = {f.get('nome') for f in snapshot.get('flag_turno', [])}
    mancanti = [n for n in NOMI_STRUTTURALI if n not in nomi]

    if mancanti:
        raise ConfigurazioneNonValida(
            'La configurazione non contiene ' + ', '.join(mancanti)
            + ": sono i concetti su cui il sistema ragiona e non possono mancare."
        )


# Come si ripristina ogni parte dello snapshot.
#   tabella  → (chiave nello snapshot, colonne da scrivere)
# Le tabelle elencate qui si riscrivono per intero: nessuno le referenzia per
# id, quindi cancellarle e riscriverle non lascia riferimenti appesi.
TABELLE_DA_RISCRIVERE = {
    'vincoli_solver':        ('vincoli_solver',        ('tipo', 'ref_id', 'max_n', 'is_active')),
    'vincoli_solver_utente': ('vincoli_solver_utente', ('user_id', 'tipo', 'ref_id', 'max_n', 'note')),
    'esclusioni_utente':     ('esclusioni_utente',     ('user_id', 'flag_id', 'note')),
}

# Le tabelle che invece si aggiornano per id, perche' qualcun altro vi punta.
COLONNE_FLAG_TURNO = (
    'nome', 'parent_id', 'orario_inizio', 'orario_fine', 'pausa_minuti',
    'durata_netta_minuti', 'durata_totale_minuti', 'peso_turno', 'ore_turno',
    'ore_primo_giorno', 'ore_ultimo_giorno', 'mostra_in_struttura', 'tipo',
)
COLONNE_TIPI_QUALITATIVO = ('nome', 'descrizione', 'carico_lavoro')
COLONNE_TIPI_RICHIESTA = (
    'sigla', 'descrizione', 'tipo', 'counting_flag', 'flag_id',
    'ore_default', 'ordine',
)


def _riscrivi_per_id(db, tabella, colonne, righe):
    """
    Allinea una tabella allo snapshot conservando gli id.

    Le righe presenti nello snapshot si aggiornano o si inseriscono con il
    loro id; quelle che lo snapshot non ha si lasciano dove sono. Non si
    cancella nulla: una fascia tolta da una configurazione puo' essere
    ancora agganciata a un gruppo o a un calendario chiuso.

    Args:
        db: connessione al tenant.
        tabella (str): nome della tabella.
        colonne (tuple): colonne da scrivere, escluso l'id.
        righe (list): righe dello snapshot, ciascuna con il proprio id.

    Returns:
        int: quante righe sono state scritte.
    """
    elenco = ', '.join(colonne)
    segnaposto = ', '.join('?' * (len(colonne) + 1))
    aggiornamento = ', '.join(f'{c} = excluded.{c}' for c in colonne)

    for riga in righe:
        db.execute(
            f"INSERT INTO {tabella} (id, {elenco}) VALUES ({segnaposto}) "
            f"ON CONFLICT(id) DO UPDATE SET {aggiornamento}",
            [riga.get('id')] + [riga.get(c) for c in colonne]
        )

    return len(righe)


def _riscrivi_da_zero(db, tabella, colonne, righe):
    """
    Svuota una tabella e la riscrive dallo snapshot.

    Riservata alle tabelle che nessuno referenzia per id.

    Args:
        db: connessione al tenant.
        tabella (str): nome della tabella.
        colonne (tuple): colonne da scrivere.
        righe (list): righe dello snapshot.

    Returns:
        int: quante righe sono state scritte.
    """
    db.execute(f'DELETE FROM {tabella}')

    elenco = ', '.join(colonne)
    segnaposto = ', '.join('?' * len(colonne))
    for riga in righe:
        db.execute(
            f"INSERT INTO {tabella} ({elenco}) VALUES ({segnaposto})",
            [riga.get(c) for c in colonne]
        )

    return len(righe)


def _riscrivi_regole(db, righe):
    """
    Riscrive le regole di conflitto dallo snapshot, conservando gli id.

    Args:
        db: connessione al tenant.
        righe (list): regole dello snapshot.

    Returns:
        int: quante regole sono state scritte.
    """
    colonne = ('nome', 'tipo_regola', 'flag_a_id', 'flag_b_id', 'offset_giorni',
               'categoria', 'stile', 'blocca_inserimento', 'peso_numerico')
    return _riscrivi_per_id(db, 'regole_conflitto', colonne, righe)


def _riscrivi_conteggi(db, conteggi):
    """
    Riporta i conteggi del context menu, che vivono come JSON in `config`.

    Args:
        db: connessione al tenant.
        conteggi (list): elenco dei conteggi.

    Returns:
        int: quanti conteggi sono stati scritti.
    """
    db.execute(
        "INSERT INTO config (chiave, valore) VALUES ('conteggi_context', ?) "
        "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore",
        (json.dumps(conteggi),)
    )
    return len(conteggi)


def applica_snapshot(db, snapshot):
    """
    Riporta le tabelle di configurazione allo stato dello snapshot.

    Tutto dentro una transazione: o passa l'intera configurazione, o non ne
    passa nessun pezzo.

    Args:
        db: connessione al tenant.
        snapshot (dict): configurazione da applicare.

    Returns:
        dict: quante righe scritte per parte.

    Raises:
        ConfigurazioneNonValida: manca un concetto strutturale.
    """
    verifica_invarianti(snapshot)

    scritte = {}
    try:
        scritte['flag_turno'] = _riscrivi_per_id(
            db, 'flag_turno', COLONNE_FLAG_TURNO, snapshot.get('flag_turno', []))
        scritte['tipi_qualitativo'] = _riscrivi_per_id(
            db, 'tipi_qualitativo', COLONNE_TIPI_QUALITATIVO,
            snapshot.get('tipi_qualitativo', []))
        scritte['tipi_richiesta'] = _riscrivi_per_id(
            db, 'tipi_richiesta', COLONNE_TIPI_RICHIESTA,
            snapshot.get('tipi_richiesta', []))
        scritte['regole_conflitto'] = _riscrivi_regole(
            db, snapshot.get('regole_conflitto', []))

        for tabella, (chiave, colonne) in TABELLE_DA_RISCRIVERE.items():
            scritte[tabella] = _riscrivi_da_zero(
                db, tabella, colonne, snapshot.get(chiave, []))

        scritte['conteggi_context'] = _riscrivi_conteggi(
            db, snapshot.get('conteggi_context', []))

        db.commit()
    except Exception:
        db.rollback()
        raise

    return scritte


# ---------------------------------------------------------------------------
# Le configurazioni salvate
# ---------------------------------------------------------------------------

def salva_configurazione(db, nome, preset_id=None):
    """
    Congela la configurazione corrente sotto un nome.

    Se il nome esiste gia' la configurazione viene sovrascritta: e' cosi' che
    la procedura guidata aggiorna quella che ha creato, invece di lasciare
    dietro di se' una scia di copie.

    Args:
        db: connessione al tenant.
        nome (str): nome della configurazione.
        preset_id (int|None): struttura turni che le corrisponde.

    Returns:
        int: id della configurazione salvata.
    """
    snapshot = crea_config_snapshot(preset_id)

    db.execute(
        "INSERT INTO configurazioni (nome, snapshot, preset_id) VALUES (?,?,?) "
        "ON CONFLICT(nome) DO UPDATE SET "
        "  snapshot = excluded.snapshot, "
        "  preset_id = excluded.preset_id, "
        "  updated_at = datetime('now')",
        (nome, snapshot, preset_id)
    )
    db.commit()

    return db.execute(
        "SELECT id FROM configurazioni WHERE nome = ?", (nome,)
    ).fetchone()[0]


def attiva_configurazione(db, configurazione_id):
    """
    Applica una configurazione salvata e la segna come attiva.

    Args:
        db: connessione al tenant.
        configurazione_id (int): configurazione da attivare.

    Returns:
        dict: quante righe scritte per parte.

    Raises:
        ConfigurazioneNonValida: la configurazione non esiste o non e'
                                 applicabile.
    """
    riga = db.execute(
        "SELECT snapshot FROM configurazioni WHERE id = ?", (configurazione_id,)
    ).fetchone()
    if not riga:
        raise ConfigurazioneNonValida('Configurazione non trovata.')

    try:
        snapshot = json.loads(riga[0])
    except (json.JSONDecodeError, TypeError) as e:
        raise ConfigurazioneNonValida('Lo snapshot non e\' leggibile.') from e

    scritte = applica_snapshot(db, snapshot)

    # L'indice unico ammette una sola riga attiva: prima si spegne l'altra.
    db.execute("UPDATE configurazioni SET is_attiva = 0 WHERE is_attiva = 1")
    db.execute("UPDATE configurazioni SET is_attiva = 1 WHERE id = ?", (configurazione_id,))
    db.commit()

    return scritte
