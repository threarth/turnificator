"""
app/services/proposte.py — proposte di configurazione dal master ai tenant.

Nuova feature. Il master non impone: deposita una proposta nel database del
tenant, e l'amministratore del tenant la confronta con quello che ha e decide
se accettarla.

Cosa si propone
---------------
Il **vocabolario** e le **regole**, che sono trasferibili fra reparti diversi:
fasce orarie e assenze, tipologie turno, tipi richiesta, regole di conflitto.

Restano fuori le cose specifiche del posto: la struttura turni, le persone, i
vincoli del solver e i conteggi. Un reparto puo' condividere il vocabolario
con un altro e avere tetti e organico tutti suoi.

Perche' nel database del tenant
-------------------------------
Cosi' il tenant resta autosufficiente: la proposta si legge e si accetta anche
se il master e' irraggiungibile, ed e' dove l'amministratore la trova senza
dover interrogare un altro sistema.
"""

# Le parti di uno snapshot che si possono proporre. L'ordine e' quello in cui
# si mostrano all'utente: prima il vocabolario, poi le regole che lo usano.
PARTI_PROPONIBILI = (
    ('flag_turno',       'Fasce orarie e assenze', 'nome'),
    ('tipi_qualitativo', 'Tipologie turno',        'nome'),
    ('tipi_richiesta',   'Tipi richiesta',         'sigla'),
    ('regole_conflitto', 'Regole di conflitto',    'nome'),
)

# Campi che non vanno confrontati: cambiano senza che l'utente abbia deciso
# niente, e segnalarli sarebbe rumore.
CAMPI_DERIVATI = frozenset({
    'durata_netta_minuti', 'durata_totale_minuti', 'ore_turno', 'peso_turno',
})


def estrai_proposta(snapshot):
    """
    Tiene di uno snapshot solo le parti proponibili.

    Args:
        snapshot (dict): configurazione completa di un tenant.

    Returns:
        dict: le sole quattro parti trasferibili.
    """
    return {
        chiave: snapshot.get(chiave, [])
        for chiave, _, _ in PARTI_PROPONIBILI
    }


def _differenze_riga(attuale, proposta):
    """
    I campi che la proposta cambierebbe, con il prima e il dopo.

    Args:
        attuale (dict): riga come e' adesso.
        proposta (dict): riga come la propone il master.

    Returns:
        list: [{campo, prima, dopo}], vuota se nulla cambia.
    """
    cambi = []
    for campo, valore in proposta.items():
        if campo == 'id' or campo in CAMPI_DERIVATI:
            continue
        if campo in attuale and attuale[campo] != valore:
            cambi.append({'campo': campo, 'prima': attuale[campo], 'dopo': valore})

    return cambi


def _confronta_parte(righe_attuali, righe_proposte, chiave_nome):
    """
    Confronta una parte del vocabolario, riga per riga.

    Il confronto e' per nome, non per id: due tenant nati da database diversi
    hanno id diversi per la stessa fascia, ed e' il nome che l'utente riconosce.

    Args:
        righe_attuali (list): righe del tenant.
        righe_proposte (list): righe della proposta.
        chiave_nome (str): campo che identifica la riga per l'utente.

    Returns:
        dict: {nuove: [...], modificate: [...], solo_qui: [...]}.
    """
    per_nome = {r.get(chiave_nome): r for r in righe_attuali}
    nomi_proposti = {r.get(chiave_nome) for r in righe_proposte}

    nuove, modificate = [], []
    for riga in righe_proposte:
        nome = riga.get(chiave_nome)
        attuale = per_nome.get(nome)

        if attuale is None:
            nuove.append({'nome': nome, 'riga': riga})
            continue

        cambi = _differenze_riga(attuale, riga)
        if cambi:
            modificate.append({'nome': nome, 'cambi': cambi})

    # Cio' che il tenant ha in piu' non viene toccato: si segnala perche'
    # l'utente sappia che restera' li'.
    solo_qui = [n for n in per_nome if n not in nomi_proposti]

    return {'nuove': nuove, 'modificate': modificate, 'solo_qui': sorted(solo_qui)}


def confronta(proposta, snapshot_attuale):
    """
    Cosa cambierebbe accettando la proposta.

    Args:
        proposta (dict): le parti proponibili offerte dal master.
        snapshot_attuale (dict): la configurazione viva del tenant.

    Returns:
        list: una voce per parte, con etichetta e differenze.
    """
    return [
        {
            'chiave': chiave,
            'etichetta': etichetta,
            **_confronta_parte(
                snapshot_attuale.get(chiave, []),
                proposta.get(chiave, []),
                chiave_nome
            ),
        }
        for chiave, etichetta, chiave_nome in PARTI_PROPONIBILI
    ]


def e_senza_effetto(differenze):
    """
    La proposta e' identica a quello che il tenant ha gia'?

    Args:
        differenze (list): risultato di confronta().

    Returns:
        bool: True se non cambierebbe nulla.
    """
    return all(
        not parte['nuove'] and not parte['modificate']
        for parte in differenze
    )


# Colonne scrivibili di ogni parte. Gli id non ci sono di proposito: quelli
# della proposta appartengono al tenant che l'ha generata. I riferimenti fra
# tabelle si risolvono a parte, per nome.
COLONNE = {
    'flag_turno': (
        'descrizione', 'orario_inizio', 'orario_fine', 'pausa_minuti',
        'ore_primo_giorno', 'ore_ultimo_giorno', 'mostra_in_struttura',
        'solo_su_richiesta', 'tipo',
    ),
    'tipi_qualitativo': ('descrizione', 'carico_lavoro'),
    'tipi_richiesta': ('descrizione', 'tipo', 'counting_flag', 'ore_default', 'ordine'),
    'regole_conflitto': (
        'tipo_regola', 'offset_giorni', 'categoria', 'stile',
        'blocca_inserimento', 'peso_numerico',
    ),
}

# Riferimenti a `flag_turno` che vanno tradotti da un tenant all'altro:
#   tabella → colonne che contengono un id di flag
RIFERIMENTI_A_FLAG = {
    'flag_turno':       ('parent_id',),
    'tipi_richiesta':   ('flag_id',),
    'regole_conflitto': ('flag_a_id', 'flag_b_id'),
}


def _id_per_nome(db, tabella, chiave_nome):
    """Mappa nome → id delle righe che il tenant ha gia'."""
    righe = db.execute(f'SELECT id, {chiave_nome} FROM {tabella}').fetchall()
    return {r[1]: r[0] for r in righe}


def _traduttore_di_flag(db, righe_flag_proposte):
    """
    Costruisce la traduzione degli id di flag, da proposta a tenant.

    Un `parent_id` nella proposta punta a una riga del tenant che l'ha
    generata. Qui vale solo il nome: si risale al nome nella proposta e si
    ridiscende all'id locale.

    Args:
        db: connessione al tenant.
        righe_flag_proposte (list): flag_turno della proposta.

    Returns:
        function: id proposto → id locale, o None se non traducibile.
    """
    nome_proposto = {r.get('id'): r.get('nome') for r in righe_flag_proposte}
    id_locale = _id_per_nome(db, 'flag_turno', 'nome')

    def traduci(id_proposto):
        if id_proposto is None:
            return None
        return id_locale.get(nome_proposto.get(id_proposto))

    return traduci


def _applica_parte(db, tabella, chiave_nome, righe, colonne):
    """
    Allinea una parte del vocabolario alla proposta, andando per nome.

    Le righe che il tenant ha in piu' restano dove sono: accettare una
    proposta non cancella niente. Nemmeno le colonne: una proposta che di un
    campo non parla lo lascia com'e', cosi' una proposta piu' vecchia del
    campo non lo azzera passando.

    Args:
        db: connessione al tenant.
        tabella (str): tabella da allineare.
        chiave_nome (str): campo con cui si riconosce una riga.
        righe (list): righe proposte.
        colonne (tuple): colonne scrivibili.

    Returns:
        dict: {aggiunte, aggiornate}.
    """
    esistenti = _id_per_nome(db, tabella, chiave_nome)
    aggiunte = aggiornate = 0

    for riga in righe:
        nome = riga.get(chiave_nome)
        if not nome:
            continue

        presenti = tuple(c for c in colonne if c in riga)
        valori = [riga[c] for c in presenti]

        if nome in esistenti:
            if not presenti:
                continue
            assegnazioni = ', '.join(f'{c} = ?' for c in presenti)
            db.execute(f'UPDATE {tabella} SET {assegnazioni} WHERE id = ?',
                       valori + [esistenti[nome]])
            aggiornate += 1
        else:
            elenco = ', '.join((chiave_nome,) + presenti)
            segnaposto = ', '.join('?' * (len(presenti) + 1))
            db.execute(f'INSERT INTO {tabella} ({elenco}) VALUES ({segnaposto})',
                       [nome] + valori)
            aggiunte += 1

    return {'aggiunte': aggiunte, 'aggiornate': aggiornate}


def _collega_riferimenti(db, tabella, chiave_nome, righe, traduci):
    """
    Riaggancia i riferimenti a flag_turno dopo aver scritto le righe.

    Si fa in un secondo giro perche' il flag a cui una riga punta puo' essere
    stato creato dalla proposta stessa, e prima non esisteva.

    Args:
        db: connessione al tenant.
        tabella (str): tabella da riagganciare.
        chiave_nome (str): campo con cui si riconosce una riga.
        righe (list): righe proposte.
        traduci (function): id proposto → id locale.
    """
    colonne = RIFERIMENTI_A_FLAG.get(tabella, ())
    if not colonne:
        return

    esistenti = _id_per_nome(db, tabella, chiave_nome)
    for riga in righe:
        locale = esistenti.get(riga.get(chiave_nome))
        if locale is None:
            continue

        assegnazioni = ', '.join(f'{c} = ?' for c in colonne)
        db.execute(
            f'UPDATE {tabella} SET {assegnazioni} WHERE id = ?',
            [traduci(riga.get(c)) for c in colonne] + [locale]
        )


def applica(db, proposta):
    """
    Accetta una proposta: allinea il vocabolario e le regole del tenant.

    Tutto in transazione. I riferimenti fra tabelle — la fascia che discende
    da un concetto, il tipo richiesta legato al suo flag, la regola che punta
    a due flag — si traducono per nome: gli id della proposta appartengono a
    un altro tenant e qui non valgono niente.

    Args:
        db: connessione al tenant.
        proposta (dict): le parti proponibili.

    Returns:
        dict: quante righe aggiunte e aggiornate per parte.
    """
    esito = {}
    try:
        for chiave, _, chiave_nome in PARTI_PROPONIBILI:
            esito[chiave] = _applica_parte(
                db, chiave, chiave_nome, proposta.get(chiave, []), COLONNE[chiave]
            )

        # Ora che tutti i flag esistono, si possono agganciare i riferimenti.
        traduci = _traduttore_di_flag(db, proposta.get('flag_turno', []))
        for chiave, _, chiave_nome in PARTI_PROPONIBILI:
            _collega_riferimenti(db, chiave, chiave_nome, proposta.get(chiave, []), traduci)

        db.commit()
    except Exception:
        db.rollback()
        raise

    return esito
