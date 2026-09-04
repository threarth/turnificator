"""
app/services/modello_struttura.py — la struttura turni letta da un foglio Excel.

Nuova feature. Chi arriva da un foglio di calcolo ha gia' tutto scritto li':
i turni, come sono raggruppati, chi ci lavora, con che tipologie. Ridigitarlo
nella configurazione guidata e' un lavoro lungo e un'occasione di sbagliare.

Il foglio `Tabelle` e' la struttura in forma leggibile dalla macchina, e non
per caso: le righe della griglia in `Inserimento` sono generate da li' con
formule matriciali. Importare da `Tabelle` significa quindi ottenere una
struttura che combacia riga per riga con il foglio, ed e' cio' che permette
poi di riesportare il mese dentro lo stesso modello.

Cosa si legge:

    colonne A/B/C   turni della mattina: nome, tipologia, sigla di gruppo
    colonne E/F/G   turni del pomeriggio
    colonne I/J/K   turni della notte
    righe 27+       gli aggiuntivi, mattina e pomeriggio
    colonne N/O/P   le persone: acronimo, cognome, nome
    colonne R/S     i tipi di richiesta: desiderata e assenze

Il raggruppamento in strutture lo dichiara il foglio stesso: il `Riepilogo`
ha una colonna per struttura, e la formula che la riempie dice quali sigle vi
appartengono. Dove quel foglio non si legge, si ripiega sulla sigla privata
del suffisso di fascia — `tcSGm;` e `tcSGp;` sono la stessa struttura.

Questo modulo **non tocca il database**: legge e descrive. Chi scrive decide
a parte, dopo aver mostrato all'utente cosa e' stato capito.
"""

import re

import openpyxl
from openpyxl.utils import column_index_from_string


# Il foglio da cui si legge la struttura, e quello che dichiara i gruppi.
FOGLIO_TABELLE = 'Tabelle'
FOGLIO_RIEPILOGO = 'Riepilogo'

# I blocchi di turni, per nome dell'intervallo definito nel foglio. Il modello
# li dichiara, e sono la stessa cosa che le formule matriciali di
# `Inserimento` usano per generare le righe della griglia: leggere di qui
# significa ottenere i turni nell'ordine esatto in cui la griglia li dispone.
#
# `ripiego` sono le posizioni del modello, per un foglio che i nomi non li ha.
BLOCCHI_TURNI = (
    {'fascia': 'mattina',    'nomi': 'turni_mattina',
     'sigle': 'sigle_turni_matt',      'ripiego': ('A', 2, 19, 'C')},
    {'fascia': 'pomeriggio', 'nomi': 'turni_pomeriggio',
     'sigle': 'sigle_turni_pomeriggio', 'ripiego': ('E', 2, 19, 'G')},
    {'fascia': 'notte',      'nomi': 'turni_notte',
     'sigle': 'sigle_turni_notte',      'ripiego': ('I', 2, 3, 'K')},
    {'fascia': 'mattina',    'nomi': 'agg_mattina',
     'sigle': 'sigle_agg_matt',         'ripiego': ('A', 27, 34, 'C')},
    {'fascia': 'pomeriggio', 'nomi': 'agg_pomeriggio',
     'sigle': 'sigle_agg_pom',          'ripiego': ('E', 27, 34, 'G')},
)

# La tipologia sta sempre nella colonna accanto al nome.
SCARTO_COLONNA_TIPOLOGIA = 1

# Le persone e i tipi di richiesta, sempre per nome dell'intervallo.
NOME_PERSONE = 'medici'
RIPIEGO_PERSONE = ('N', 2, 42)
SCARTO_COGNOME = 1
SCARTO_NOME = 2

# Tutto cio' che si puo' chiedere, e quali di quelle cose sono assenze.
NOME_RICHIESTE = 'tipo_desiderata'
RIPIEGO_RICHIESTE = ('R', 2, 13)
NOME_ASSENZE = 'tipo_assenze_romc'
RIPIEGO_ASSENZE = ('S', 2, 9)

TIPO_LAVORATIVO = 'lavorativo'
TIPO_ASSENZA = 'assenza'

# Il segnaposto con cui il foglio riempie le righe non usate.
SEGNAPOSTO = ('-', '', 'vuoto', 'chiusa', 'chiuso')

# Nel Riepilogo, la riga delle intestazioni delle strutture e quante righe
# sotto cercare le formule che ne dichiarano il contenuto.
RIGA_INTESTAZIONI_RIEPILOGO = 52
RIGHE_FORMULE_RIEPILOGO = 8
COLONNA_TOTALE = 'TOTALE'


def _testo(cella):
    """Il contenuto di una cella come testo pulito, o stringa vuota."""
    if cella is None or cella.value is None:
        return ''

    return str(cella.value).strip()


def _e_segnaposto(testo):
    """La riga e' una di quelle che il foglio lascia libere."""
    return testo.lower().strip(' .;') in SEGNAPOSTO


def _intervallo(wb, nome, ripiego):
    """
    Dove sta un blocco: colonna e righe, dall'intervallo che il foglio nomina.

    Il modello dichiara i propri blocchi con un nome (`turni_mattina`,
    `medici`): leggerli di li' e' piu' solido che contare le colonne, e
    sopravvive a una riga aggiunta in mezzo. Il ripiego serve a un foglio
    costruito a mano, senza quei nomi.

    Args:
        wb: cartella di lavoro.
        nome (str): nome dell'intervallo definito.
        ripiego (tuple): (colonna, prima riga, ultima riga) del modello.

    Returns:
        tuple: (indice colonna, prima riga, ultima riga).
    """
    definito = wb.defined_names.get(nome)
    if definito is not None:
        trovato = re.search(r'\$([A-Z]+)\$(\d+):\$[A-Z]+\$(\d+)', str(definito.value))
        if trovato:
            return (column_index_from_string(trovato.group(1)),
                    int(trovato.group(2)), int(trovato.group(3)))

    colonna, prima, ultima = ripiego

    return column_index_from_string(colonna), prima, ultima


def _chiave_sigla(sigla):
    """
    La sigla privata del punto e virgola e del suffisso di fascia.

    `deaM;` e `deaP;` diventano `dea`: sono lo stesso posto, in due momenti
    della giornata. E' il ripiego per quando il Riepilogo non si legge.

    Args:
        sigla (str): sigla come sta nel foglio.

    Returns:
        str: la chiave del raggruppamento, minuscola.
    """
    pulita = sigla.strip().rstrip(';').strip()

    return re.sub(r'[mpn]$', '', pulita, flags=re.IGNORECASE).lower()


def _raggruppamenti_dal_riepilogo(wb_formule):
    """
    Le strutture come le dichiara il foglio Riepilogo.

    Ogni colonna e' una struttura, e la formula che la riempie elenca le
    sigle che vi appartengono: `COUNTIF(...,"*tcSG*")` dice che tutto cio'
    che contiene `tcSG` e' di quella struttura. Serve la cartella aperta
    **con le formule**: a valori si leggerebbe il numero, non la regola.

    Args:
        wb_formule: cartella di lavoro aperta con data_only=False.

    Returns:
        list: [(nome, [pattern in minuscolo])], vuota se il foglio non c'e'.
    """
    if FOGLIO_RIEPILOGO not in wb_formule.sheetnames:
        return []

    ws = wb_formule[FOGLIO_RIEPILOGO]
    gruppi = []

    for c in range(1, ws.max_column + 1):
        nome = ' '.join(_testo(ws.cell(RIGA_INTESTAZIONI_RIEPILOGO, c)).split())
        if not nome or nome.upper() == COLONNA_TOTALE:
            continue

        for r in range(RIGA_INTESTAZIONI_RIEPILOGO + 1,
                       RIGA_INTESTAZIONI_RIEPILOGO + 1 + RIGHE_FORMULE_RIEPILOGO):
            formula = _testo(ws.cell(r, c))
            if 'COUNTIF' not in formula.upper():
                continue
            pattern = [p.lower() for p in re.findall(r'"\*([^"*]+)\*"', formula)]
            if pattern:
                gruppi.append((nome, pattern))
            break

    return gruppi


def _struttura_di(sigla, raggruppamenti):
    """
    A quale struttura appartiene un turno, data la sua sigla.

    Args:
        sigla (str): sigla del turno nel foglio.
        raggruppamenti (list): [(nome, [pattern])] dal Riepilogo.

    Returns:
        tuple: (chiave, nome) della struttura.
    """
    pulita = sigla.strip().rstrip(';').strip().lower()

    for nome, pattern in raggruppamenti:
        if any(p in pulita for p in pattern):
            return nome, nome

    chiave = _chiave_sigla(sigla)

    return chiave, chiave.upper()


def _leggi_turni(wb, ws, raggruppamenti):
    """
    I turni del foglio, nell'ordine in cui la griglia li dispone.

    Args:
        wb: cartella di lavoro, per gli intervalli nominati.
        ws: foglio Tabelle, a valori.
        raggruppamenti (list): strutture dichiarate dal Riepilogo.

    Returns:
        tuple: (lista di turni, lista di avvisi).
    """
    turni = []
    avvisi = []

    for blocco in BLOCCHI_TURNI:
        col_nome, prima, ultima = _intervallo(wb, blocco['nomi'], blocco['ripiego'][:3])
        col_sigla, _, _ = _intervallo(
            wb, blocco['sigle'],
            (blocco['ripiego'][3], prima, ultima)
        )

        for r in range(prima, ultima + 1):
            nome = _testo(ws.cell(r, col_nome))
            if _e_segnaposto(nome):
                continue

            sigla = _testo(ws.cell(r, col_sigla))
            if not sigla or _e_segnaposto(sigla):
                avvisi.append(
                    f'Il turno "{nome}" non ha una sigla di gruppo: non so in '
                    f'che struttura metterlo, l\'ho saltato.'
                )
                continue

            chiave, nome_struttura = _struttura_di(sigla, raggruppamenti)
            turni.append({
                'nome': nome,
                'fascia': blocco['fascia'],
                'struttura': chiave,
                'struttura_nome': nome_struttura,
                'tipologia': _testo(ws.cell(r, col_nome + SCARTO_COLONNA_TIPOLOGIA)),
                'ordine': len(turni),
            })

    return turni, avvisi


def _leggi_persone(wb, ws):
    """Le persone del foglio, saltando i segnaposto."""
    colonna, prima, ultima = _intervallo(wb, NOME_PERSONE, RIPIEGO_PERSONE)

    persone = []
    for r in range(prima, ultima + 1):
        sigla = _testo(ws.cell(r, colonna))
        cognome = _testo(ws.cell(r, colonna + SCARTO_COGNOME))
        if not sigla or _e_segnaposto(sigla) or _e_segnaposto(cognome):
            continue
        if sigla.upper().startswith('VUOTO'):
            continue

        persone.append({
            'sigla': sigla.upper(),
            'cognome': cognome,
            'nome': _testo(ws.cell(r, colonna + SCARTO_NOME)),
        })

    return persone


def _sigle_in(wb, ws, nome, ripiego):
    """Le sigle non vuote di un intervallo, nell'ordine del foglio."""
    colonna, prima, ultima = _intervallo(wb, nome, ripiego)

    sigle = []
    for r in range(prima, ultima + 1):
        sigla = _testo(ws.cell(r, colonna))
        if sigla and not _e_segnaposto(sigla) and sigla not in sigle:
            sigle.append(sigla)

    return sigle


def _leggi_tipi_richiesta(wb, ws):
    """
    Le sigle con cui il foglio esprime desiderata e assenze.

    Il foglio tiene due elenchi: tutto cio' che si puo' chiedere, e quali di
    quelle cose sono un'assenza. Il secondo e' un sottoinsieme del primo, non
    una lista a parte.
    """
    assenze = {s.upper() for s in _sigle_in(wb, ws, NOME_ASSENZE, RIPIEGO_ASSENZE)}

    return [
        {'sigla': sigla,
         'tipo': TIPO_ASSENZA if sigla.upper() in assenze else TIPO_LAVORATIVO}
        for sigla in _sigle_in(wb, ws, NOME_RICHIESTE, RIPIEGO_RICHIESTE)
    ]


def leggi_struttura(sorgente):
    """
    Legge da un modello Excel tutto cio' che serve a costruire la struttura.

    Args:
        sorgente: percorso, oggetto file o BytesIO del foglio.

    Returns:
        dict: strutture, turni, tipologie, persone, tipi_richiesta, avvisi.

    Raises:
        ValueError: il foglio non ha la tabella da cui si legge la struttura.
    """
    # Due letture dello stesso file: i valori servono per le tabelle, le
    # formule per capire come il Riepilogo raggruppa le strutture.
    wb = openpyxl.load_workbook(sorgente, data_only=True)
    if hasattr(sorgente, 'seek'):
        sorgente.seek(0)
    wb_formule = openpyxl.load_workbook(sorgente, data_only=False)

    if FOGLIO_TABELLE not in wb.sheetnames:
        raise ValueError(
            f'Nel file manca il foglio "{FOGLIO_TABELLE}", che e\' quello da '
            f'cui si legge la struttura.'
        )

    ws = wb[FOGLIO_TABELLE]
    raggruppamenti = _raggruppamenti_dal_riepilogo(wb_formule)
    turni, avvisi = _leggi_turni(wb, ws, raggruppamenti)

    if not turni:
        raise ValueError('Nel foglio non ho trovato nessun turno.')

    # Le strutture, nell'ordine in cui i turni le incontrano.
    strutture = []
    viste = set()
    for t in turni:
        if t['struttura'] not in viste:
            viste.add(t['struttura'])
            strutture.append({'chiave': t['struttura'], 'nome': t['struttura_nome']})

    tipologie = []
    for t in turni:
        if t['tipologia'] and not _e_segnaposto(t['tipologia']) \
                and t['tipologia'] not in tipologie:
            tipologie.append(t['tipologia'])

    if not raggruppamenti:
        avvisi.append(
            'Il foglio Riepilogo non dichiara le strutture: le ho ricavate '
            'dalle sigle dei turni, e i nomi sono quelli.'
        )

    return {
        'strutture': strutture,
        'turni': turni,
        'tipologie': tipologie,
        'persone': _leggi_persone(wb, ws),
        'tipi_richiesta': _leggi_tipi_richiesta(wb, ws),
        'avvisi': avvisi,
    }
