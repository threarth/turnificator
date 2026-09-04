"""
genera_config_turni.py — la semantica del modello turni in forma tabellare.

Nuova feature. Il modello Excel (`modello_turni_set26.xlsx`) tiene la propria
semantica in tre posti che non si possono interrogare: dentro le sigle
(`deaM;` = DEA + mattina), dentro la geometria delle righe (una riga e'
"mattina" perche' sta fra la 22 e la 39) e dentro le formule del Riepilogo
(`COUNTIF(...,"*tcSG*")`). Questo script la estrae e la riscrive come tabelle
normalizzate: una riga per entita', una colonna per attributo.

Il risultato e' una cartella di lavoro nuova, non una modifica dell'originale.
La ragione e' tecnica: openpyxl non conosce le estensioni x14 e, riscrivendo il
file di partenza, ne cancellerebbe le 38 formattazioni condizionali e le
validazioni dati. L'originale viene aperto in sola lettura.

Le tabelle sono Tabelle Excel vere (ListObject): si allungano da sole, e le
tendine che le citano restano agganciate quando si aggiunge una riga.
"""

import re
import unicodedata

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo


MODELLO_ORIGINE = 'modello_turni_set26.xlsx'
FILE_USCITA = 'modello_config.xlsx'
FOGLIO_TABELLE = 'Tabelle'

# I tre presidi, come li ha definiti il reparto.
SEDI = (
    ('S.G.', 'San Giovanni', 'Ospedale principale, sede del DEA'),
    ('ADDO', 'Addolorata',   'Ambulatori e oncologia'),
    ('S.M.', 'Santa Maria',  'Mammografia, ecografia e biopsia mammaria'),
)

# Le fasce orarie, dai default di migrations/init_db.sql (flag_turno).
# Il peso e' la durata netta rapportata al turno tipo di 380 minuti.
FASCE = (
    ('mattina',    'diurno',   '08:00', '14:20', 10, 1.0, 'NO'),
    ('pomeriggio', 'diurno',   '14:00', '20:20', 10, 1.0, 'NO'),
    ('lunga',      'diurno',   '08:00', '20:40', 10, 2.0, 'SI'),
    ('notte',      'notturno', '20:00', '08:40', 10, 2.0, 'NO'),
)

# I blocchi di turni dentro Tabelle: fascia, colonna del nome, prima e
# ultima riga, colonna della sigla, se sono turni aggiuntivi.
BLOCCHI = (
    ('mattina',    'A',  2, 19, 'C', False),
    ('pomeriggio', 'E',  2, 19, 'G', False),
    ('notte',      'I',  2,  3, 'K', False),
    ('mattina',    'A', 27, 34, 'C', True),
    ('pomeriggio', 'E', 27, 34, 'G', True),
)

COLONNE_PERSONE = ('N', 'O', 'P')
RIGHE_PERSONE = (2, 42)
BLOCCO_RICHIESTE = ('R', 2, 13)
BLOCCO_ASSENZE = ('S', 2, 9)
BLOCCO_ASSENZE_FESTIVI = ('T', 2, 2)

# Le righe che il foglio lascia libere per tenere fissa la geometria.
SEGNAPOSTO = ('-', '', 'vuoto', 'vuoto_c', 'vuoto_d', 'vuoto_e',
              'chiusa', 'chiuso')

# La sede si legge dal prefisso del nome. Dove il nome non la dice, la
# dichiara il reparto: le notti sono DEA al San Giovanni, la mammografia
# aggiuntiva sta al polo senologico, l'aggiuntiva generica all'Addolorata.
PREFISSI_SEDE = (
    ('AGGIUNT ADDO',  'ADDO'),
    ('AGGIUNT SG',    'S.G.'),
    ('AGGIUNT MAMMO', 'S.M.'),
    ('AGGIUNT ALTRO', 'ADDO'),
    ('S.G.',          'S.G.'),
    ('ADD',           'ADDO'),
    ('S.M.',          'S.M.'),
    ('NOTTE',         'S.G.'),
)

# `DEANOTTE` impasta metodica e fascia: separati gli assi, resta DEA.
METODICHE_DA_NORMALIZZARE = {'DEANOTTE': 'DEA'}

# Le metodiche, con la lettura per esteso dove e' ricavabile dall'acronimo.
DESCRIZIONI_METODICHE = {
    'DEA':     'Dipartimento Emergenza e Accettazione',
    'TC':      'Tomografia computerizzata',
    'RM':      'Risonanza magnetica',
    'ECO':     'Ecografia',
    'ECORX':   'Ecografia e radiologia tradizionale',
    'ECODOP':  'Ecocolordoppler',
    'ECOMX':   'Ecografia e mammografia',
    'MX':      'Mammografia',
    'MXBIO':   'Mammografia e biopsia',
    'VABBCEM': 'Biopsia VABB e mammografia con contrasto',
    'SENO':    'Senologia',
    'ALTRO':   'Altro',
}

# I turni che coprono l'emergenza girano sette giorni su sette; gli altri
# seguono il calendario del foglio, che chiude la sola domenica
# (WEEKDAY()=1 alla riga 6, NETWORKDAYS.INTL(...,11,...) in AE14).
METODICHE_SETTE_SU_SETTE = ('DEA',)
GIORNI_CONTINUI = 'LMMGVSD'
GIORNI_FERIALI = 'LMMGVS-'
NECESSITA_DEFAULT = 50
NECESSITA_MASSIMA = 100

# Quanto valgono le preferenze morbide, in centesimi di turno.
PESO_EVITA = -30
PESO_PREFERISCI = 30

# Quante regole per persona prevede la tabella delle preferenze.
REGOLE_PER_PERSONA = 10
MODI_REGOLA = 'mai,solo,evita,preferisci'
SI_NO = 'SI,NO'

# Il separatore fra nome del turno e fascia nell'etichetta univoca.
SEPARATORE_ETICHETTA = ' · '

PASSO_ORDINE = 10
STILE_TABELLA = 'TableStyleMedium2'
LARGHEZZA_MASSIMA = 42


def _testo(cella):
    """Il contenuto di una cella come testo pulito, o stringa vuota."""
    if cella is None or cella.value is None:
        return ''

    return str(cella.value).strip()


def _e_segnaposto(testo):
    """La riga e' una di quelle lasciate libere per riempire la griglia."""
    return testo.lower().strip(' .;') in SEGNAPOSTO


def _sede_di(nome):
    """La sede di un turno, dal prefisso del nome; vuota se non lo dice."""
    maiuscolo = nome.upper()
    for prefisso, sede in PREFISSI_SEDE:
        if maiuscolo.startswith(prefisso):
            return sede

    return ''


def _postazione_di(nome):
    """
    Il posto di lavoro dietro un turno, ripulito del suffisso di fascia.

    Lo stesso posto compare due volte nel foglio, una per la mattina e una
    per il pomeriggio, e non sempre con lo stesso nome: `S.G. TC MOB/128 M`
    e `S.G. TC MOB/128 P` sono la stessa TC. Qui si riconducono a un nome
    solo, correggendo anche le sviste dell'originale (`ADD SUPP. TC P` senza
    punto, `ADD. RM SieM.` con la M maiuscola).

    Args:
        nome (str): nome del turno come sta nel foglio.

    Returns:
        str: nome della postazione.
    """
    pulito = re.sub(r'\s+', ' ', nome).strip()
    pulito = re.sub(r'\s+(M|P)$', '', pulito)
    pulito = re.sub(r'^ADD\.?\s+', 'ADD. ', pulito)

    return pulito


def leggi_turni(ws):
    """
    I turni del foglio Tabelle, con gli assi resi espliciti.

    Ogni turno diventa una riga con sede, metodica, fascia e postazione in
    colonne separate, al posto della sigla che oggi le impasta tutte.

    Args:
        ws: foglio `Tabelle`, a valori.

    Returns:
        list: dizionari, uno per turno, nell'ordine del foglio.
    """
    turni = []
    for fascia, col_nome, prima, ultima, col_sigla, aggiuntiva in BLOCCHI:
        col_tipo = get_column_letter(column_index_from_string(col_nome) + 1)

        for riga in range(prima, ultima + 1):
            nome = _testo(ws[f'{col_nome}{riga}'])
            if _e_segnaposto(nome):
                continue

            metodica = _testo(ws[f'{col_tipo}{riga}'])
            metodica = METODICHE_DA_NORMALIZZARE.get(metodica, metodica)
            sigla = _testo(ws[f'{col_sigla}{riga}']).strip('; ')
            spento = _e_segnaposto(metodica) or _e_segnaposto(sigla)

            turni.append({
                'nome': nome,
                'etichetta': f'{nome}{SEPARATORE_ETICHETTA}{fascia}',
                'postazione': _postazione_di(nome),
                'sede': _sede_di(nome),
                'metodica': '' if _e_segnaposto(metodica) else metodica,
                'fascia': fascia,
                'aggiuntiva': 'SI' if aggiuntiva else 'NO',
                'sigla_gruppo': '' if _e_segnaposto(sigla) else sigla,
                'attivo': 'NO' if spento else 'SI',
            })

    return turni


def unifica_postazioni(turni):
    """
    Riconduce a una scrittura sola le postazioni che differiscono per
    maiuscole.

    Nell'originale la stessa RM dell'Addolorata compare come `ADD. RM Siem.`
    la mattina e `ADD. RM SieM.` il pomeriggio. Senza questo passaggio
    resterebbero due postazioni distinte, e una regola scritta sull'una non
    varrebbe per l'altra.

    Args:
        turni (list): i turni come li restituisce `leggi_turni`.

    Returns:
        list: gli stessi turni, con la postazione uniformata.
    """
    canoniche = {}
    for turno in turni:
        chiave = turno['postazione'].upper()
        canoniche.setdefault(chiave, turno['postazione'])
        turno['postazione'] = canoniche[chiave]

    return turni


def completa_turni(turni):
    """
    Aggiunge ai turni i parametri di riempimento, con valori di partenza.

    Questi valori il foglio originale non li contiene: nessuno vi ha mai
    scritto quali turni siano obbligatori o in che giorni aprano. Sono
    quindi proposte da rivedere, non dati letti.

    Args:
        turni (list): i turni come li restituisce `leggi_turni`.

    Returns:
        list: gli stessi turni, con le colonne di riempimento aggiunte.
    """
    for indice, turno in enumerate(turni, start=1):
        emergenza = turno['metodica'] in METODICHE_SETTE_SU_SETTE
        spento = turno['attivo'] == 'NO'

        turno['id'] = f'T{indice:02d}'
        turno['riempimento'] = ('chiuso' if spento
                                else 'obbligatorio' if emergenza
                                else 'opzionale')
        turno['necessita'] = (0 if spento
                              else NECESSITA_MASSIMA if emergenza
                              else NECESSITA_DEFAULT)
        turno['giorni'] = GIORNI_CONTINUI if emergenza else GIORNI_FERIALI
        turno['festivi'] = 'SI' if emergenza else 'NO'
        turno['superfestivi'] = 'SI' if emergenza else 'NO'
        turno['ordine'] = indice * PASSO_ORDINE

    return turni


def leggi_persone(ws):
    """
    Le persone del foglio Tabelle, senza le righe segnaposto.

    Args:
        ws: foglio `Tabelle`, a valori.

    Returns:
        list: dizionari con acronimo, cognome e nome.
    """
    col_acronimo, col_cognome, col_nome = COLONNE_PERSONE
    prima, ultima = RIGHE_PERSONE

    persone = []
    for riga in range(prima, ultima + 1):
        acronimo = _testo(ws[f'{col_acronimo}{riga}'])
        if _e_segnaposto(acronimo):
            continue

        persone.append({
            'acronimo': acronimo,
            'cognome': _testo(ws[f'{col_cognome}{riga}']),
            'nome': _testo(ws[f'{col_nome}{riga}']),
        })

    return persone


def leggi_colonna(ws, blocco):
    """I valori non vuoti di una colonna, nell'ordine del foglio."""
    colonna, prima, ultima = blocco

    valori = []
    for riga in range(prima, ultima + 1):
        valore = _testo(ws[f'{colonna}{riga}'])
        if valore and not _e_segnaposto(valore) and valore not in valori:
            valori.append(valore)

    return valori


def costruisci_bersagli(turni):
    """
    L'elenco unico dei bersagli su cui si puo' scrivere una regola.

    Fasce, metodiche, sedi, categorie, postazioni e singoli turni stanno in
    una lista sola: chi compila scrive un nome soltanto e il livello lo
    deduce questa tabella. Il prezzo e' che i nomi devono essere univoci fra
    i livelli, e qui si verifica che lo siano.

    Args:
        turni (list): i turni gia' completati.

    Returns:
        tuple: (righe della tabella, elenco dei nomi in collisione).
    """
    righe = [[f[0], 'fascia', f'Tutti i turni di fascia {f[0]}']
             for f in FASCE]

    for metodica in sorted({t['metodica'] for t in turni if t['metodica']}):
        righe.append([metodica, 'metodica',
                      DESCRIZIONI_METODICHE.get(metodica, '')])

    for codice, nome, descrizione in SEDI:
        righe.append([codice, 'sede', f'{nome} — {descrizione}'])

    righe.append(['aggiuntiva', 'categoria', 'Tutti i turni aggiuntivi'])

    viste = {}
    for turno in turni:
        if turno['postazione'] not in viste:
            viste[turno['postazione']] = turno
            righe.append([turno['postazione'], 'postazione',
                          f"{turno['sede']} · {turno['metodica']} "
                          f"— tutte le fasce"])

    for turno in turni:
        righe.append([turno['etichetta'], 'turno',
                      f"{turno['sede']} · {turno['metodica']} "
                      f"· {turno['fascia']}"])

    return righe, _collisioni(righe)


def _collisioni(righe):
    """I bersagli che due livelli diversi chiamano allo stesso modo."""
    visti = {}
    collisioni = []

    for bersaglio, livello, _ in righe:
        chiave = unicodedata.normalize('NFKD', bersaglio.upper())
        if chiave in visti and visti[chiave] != livello:
            collisioni.append(f'{bersaglio}: {visti[chiave]} / {livello}')
        visti[chiave] = livello

    return collisioni


def costruisci_richieste(ws):
    """
    I tipi di richiesta, distinguendo le assenze dalle preferenze di fascia.

    Args:
        ws: foglio `Tabelle`, a valori.

    Returns:
        list: righe con sigla, tipo, se conta le ore, se vale nei festivi.
    """
    tutte = leggi_colonna(ws, BLOCCO_RICHIESTE)
    assenze = leggi_colonna(ws, BLOCCO_ASSENZE)
    anche_festivi = leggi_colonna(ws, BLOCCO_ASSENZE_FESTIVI)

    righe = []
    for sigla in tutte:
        e_assenza = sigla in assenze
        righe.append([
            sigla,
            'assenza' if e_assenza else 'lavorativo',
            # ROMC e' l'unico riposo che non concorre al monte ore.
            'NO' if sigla.upper() == 'ROMC' else 'SI',
            'SI' if sigla in anche_festivi else 'NO',
            '',
        ])

    return righe


def scrivi_tabella(wb, titolo, nome_tabella, intestazioni, righe):
    """
    Crea un foglio con una Tabella Excel vera (ListObject).

    Una Tabella, a differenza di un intervallo, si allunga da sola quando si
    aggiunge una riga in fondo: le tendine e le formule che la citano non
    vanno riagganciate a mano.

    Args:
        wb: cartella di lavoro di destinazione.
        titolo (str): nome del foglio.
        nome_tabella (str): nome della Tabella, es. `T_Turni`.
        intestazioni (list): nomi delle colonne.
        righe (list): liste di valori, una per riga.

    Returns:
        Il foglio creato.
    """
    ws = wb.create_sheet(titolo)
    ws.append(intestazioni)
    for riga in righe:
        ws.append(riga)

    # Una Tabella Excel non puo' essere vuota: senza dati si tiene comunque
    # una riga libera, altrimenti Excel rifiuta di aprire il file.
    ultima = max(len(righe) + 1, 2)
    tabella = Table(displayName=nome_tabella,
                    ref=f'A1:{get_column_letter(len(intestazioni))}{ultima}')
    tabella.tableStyleInfo = TableStyleInfo(
        name=STILE_TABELLA, showRowStripes=True, showColumnStripes=False)
    ws.add_table(tabella)

    _adatta_larghezze(ws, intestazioni, righe)
    ws.freeze_panes = 'A2'

    return ws


def _adatta_larghezze(ws, intestazioni, righe):
    """Allarga le colonne quanto basta al contenuto piu' lungo."""
    for indice, intestazione in enumerate(intestazioni):
        lunghezze = [len(str(intestazione)) + 4]
        lunghezze += [len(str(riga[indice])) + 2 for riga in righe
                      if indice < len(riga) and riga[indice] is not None]

        larghezza = min(max(lunghezze), LARGHEZZA_MASSIMA)
        ws.column_dimensions[get_column_letter(indice + 1)].width = larghezza


def aggiungi_tendina(ws, colonne, sorgente, prima_riga, ultima_riga):
    """
    Aggancia un menu' a tendina a una o piu' colonne di un foglio.

    Args:
        ws: il foglio.
        colonne (list): lettere delle colonne da vincolare.
        sorgente (str): formula dell'elenco, es. `=elenco_bersagli`.
        prima_riga (int): prima riga di dati.
        ultima_riga (int): ultima riga da vincolare.
    """
    validazione = DataValidation(
        type='list', formula1=sorgente, allowBlank=True,
        showErrorMessage=True, errorTitle='Valore non ammesso',
        error='Scegli una voce dal menu a tendina.')
    ws.add_data_validation(validazione)

    for colonna in colonne:
        validazione.add(f'{colonna}{prima_riga}:{colonna}{ultima_riga}')


def registra_nome(wb, nome, riferimento):
    """Dichiara un nome definito che punta a una colonna di Tabella."""
    wb.defined_names[nome] = DefinedName(nome, attr_text=riferimento)


def scrivi_preferenze(wb, persone):
    """
    La tabella delle regole per lavoratore: una riga a testa.

    Ogni regola occupa due colonne, bersaglio e modo, con la tendina su
    entrambe. Le colonne appaiate al posto di una stringa da spacchettare
    (`notte,mai; S.M.,mai`) servono a due cose: la tendina impedisce il
    refuso, e rinominando un turno non resta un riferimento morto dentro
    una cella di testo.

    Args:
        wb: cartella di lavoro di destinazione.
        persone (list): le persone, per precompilare la prima colonna.

    Returns:
        Il foglio creato.
    """
    intestazioni = ['persona']
    for numero in range(1, REGOLE_PER_PERSONA + 1):
        intestazioni += [f'r{numero}_bersaglio', f'r{numero}_modo']
    intestazioni.append('note')

    righe = [[p['acronimo']] + [''] * (REGOLE_PER_PERSONA * 2 + 1)
             for p in persone]
    ws = scrivi_tabella(wb, 'Preferenze', 'T_Preferenze', intestazioni, righe)

    ultima = len(righe) + 1
    colonne_bersaglio = [get_column_letter(2 + indice * 2)
                         for indice in range(REGOLE_PER_PERSONA)]
    colonne_modo = [get_column_letter(3 + indice * 2)
                    for indice in range(REGOLE_PER_PERSONA)]

    aggiungi_tendina(ws, colonne_bersaglio, '=elenco_bersagli', 2, ultima)
    aggiungi_tendina(ws, colonne_modo, f'"{MODI_REGOLA}"', 2, ultima)

    return ws


def scrivi_leggimi(wb, note):
    """Il foglio che dice cosa e' stato letto e cosa e' stato proposto."""
    ws = wb.create_sheet('Leggimi', 0)
    ws.column_dimensions['A'].width = 26
    ws.column_dimensions['B'].width = 96

    for riga, (voce, testo) in enumerate(note, start=1):
        ws.cell(riga, 1, voce).font = openpyxl.styles.Font(bold=True)
        ws.cell(riga, 2, testo).alignment = \
            openpyxl.styles.Alignment(wrap_text=True, vertical='top')

    return ws


# Le regole assolute, oggi sepolte nelle formattazioni condizionali di
# `Inserimento`. `*` vale per qualsiasi fascia.
REGOLE = (
    ('notte piu altro turno', 'incompatibilita', 'notte', '*', 0, 'SI',
     'Chi fa la notte non puo avere altri turni lo stesso giorno'),
    ('smonto notte', 'incompatibilita', 'notte', '*', 1, 'SI',
     'Il giorno dopo la notte e di riposo obbligatorio'),
    ('doppio turno', 'incompatibilita', '*', '*', 0, 'SI',
     'Una persona non puo coprire due turni lo stesso giorno'),
    ('desiderata disatteso', 'segnalazione', '*', '*', 0, 'NO',
     'Colora la cella per farlo notare, non impedisce l inserimento'),
)


def scrivi_anagrafiche(wb, turni, persone, bersagli, richieste):
    """
    Scrive le tabelle di anagrafica e vi aggancia le tendine.

    Args:
        wb: cartella di lavoro di destinazione.
        turni (list): i turni completati.
        persone (list): le persone.
        bersagli (list): le righe della tabella dei bersagli.
        richieste (list): le righe dei tipi di richiesta.
    """
    campi = ('id', 'etichetta', 'nome', 'postazione', 'sede', 'metodica',
             'fascia', 'aggiuntiva', 'sigla_gruppo', 'riempimento',
             'necessita', 'giorni', 'festivi', 'superfestivi', 'ordine',
             'attivo')
    ws = scrivi_tabella(wb, 'Turni', 'T_Turni', list(campi),
                        [[t[c] for c in campi] for t in turni])
    ultima = len(turni) + 1
    aggiungi_tendina(ws, ['E'], '=elenco_sedi', 2, ultima)
    aggiungi_tendina(ws, ['F'], '=elenco_metodiche', 2, ultima)
    aggiungi_tendina(ws, ['G'], '=elenco_fasce', 2, ultima)
    aggiungi_tendina(ws, ['J'], '"obbligatorio,opzionale,chiuso"', 2, ultima)
    aggiungi_tendina(ws, ['H', 'M', 'N', 'P'], f'"{SI_NO}"', 2, ultima)

    ws = scrivi_tabella(
        wb, 'Persone', 'T_Persone',
        ['acronimo', 'cognome', 'nome', 'sede', 'solo_sede_propria',
         'attivo', 'note'],
        [[p['acronimo'], p['cognome'], p['nome'], '', 'NO', 'SI', '']
         for p in persone])
    aggiungi_tendina(ws, ['D'], '=elenco_sedi', 2, len(persone) + 1)
    aggiungi_tendina(ws, ['E', 'F'], f'"{SI_NO}"', 2, len(persone) + 1)

    scrivi_tabella(wb, 'Bersagli', 'T_Bersagli',
                   ['bersaglio', 'livello', 'descrizione'], bersagli)
    scrivi_tabella(wb, 'Sedi', 'T_Sedi',
                   ['codice', 'nome', 'descrizione'], [list(s) for s in SEDI])
    scrivi_tabella(wb, 'Metodiche', 'T_Metodiche', ['metodica', 'descrizione'],
                   [[m, DESCRIZIONI_METODICHE.get(m, '')] for m in
                    sorted({t['metodica'] for t in turni if t['metodica']})])
    scrivi_tabella(wb, 'Fasce', 'T_Fasce',
                   ['fascia', 'concetto', 'inizio', 'fine', 'pausa_minuti',
                    'peso', 'solo_su_richiesta'], [list(f) for f in FASCE])
    scrivi_tabella(wb, 'Richieste', 'T_Richieste',
                   ['sigla', 'tipo', 'conta_ore', 'anche_festivi', 'note'],
                   richieste)
    scrivi_tabella(wb, 'Regole', 'T_Regole',
                   ['nome', 'tipo', 'fascia_a', 'fascia_b', 'offset_giorni',
                    'blocca', 'note'], [list(r) for r in REGOLE])


def scrivi_parametri(wb, mese, anno):
    """I parametri globali, compresi i pesi delle preferenze morbide."""
    parametri = (
        ('mese', mese, 'Mese del calendario in lavorazione'),
        ('anno', anno, 'Anno del calendario in lavorazione'),
        ('peso_evita', PESO_EVITA,
         'Quanto penalizza un "evita", in centesimi di turno'),
        ('peso_preferisci', PESO_PREFERISCI,
         'Quanto premia un "preferisci", in centesimi di turno'),
        ('max_giorni_consecutivi', 6, 'Giorni lavorativi di fila al massimo'),
        ('max_turni_giorno', 1, 'Turni per persona al giorno'),
        ('max_festivi_mese', 4, 'Turni in giorni festivi al mese'),
        ('giorno_chiuso', 'domenica',
         'Il giorno non lavorativo settimanale, come da modello originale'),
        ('turno_tipo_minuti', 380,
         'Unita di misura del peso: 6h20 di lavoro effettivo'),
        ('pausa_default_minuti', 10, 'Pausa obbligatoria, si somma alla netta'),
    )
    scrivi_tabella(wb, 'Parametri', 'T_Parametri',
                   ['chiave', 'valore', 'descrizione'],
                   [list(p) for p in parametri])


def main():
    """Legge il modello e scrive la cartella di lavoro di configurazione."""
    origine = openpyxl.load_workbook(MODELLO_ORIGINE, data_only=True,
                                     read_only=False)
    tabelle = origine[FOGLIO_TABELLE]

    turni = completa_turni(unifica_postazioni(leggi_turni(tabelle)))
    persone = leggi_persone(tabelle)
    bersagli, collisioni = costruisci_bersagli(turni)
    richieste = costruisci_richieste(tabelle)
    mese = origine['Inserimento']['Y15'].value
    anno = origine['Inserimento']['AA15'].value

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    scrivi_anagrafiche(wb, turni, persone, bersagli, richieste)
    scrivi_preferenze(wb, persone)
    scrivi_parametri(wb, mese, anno)

    for nome, colonna in (('elenco_bersagli', 'T_Bersagli[bersaglio]'),
                          ('elenco_persone', 'T_Persone[acronimo]'),
                          ('elenco_sedi', 'T_Sedi[codice]'),
                          ('elenco_metodiche', 'T_Metodiche[metodica]'),
                          ('elenco_fasce', 'T_Fasce[fascia]')):
        registra_nome(wb, nome, colonna)

    postazioni = len({t['postazione'] for t in turni})
    scrivi_leggimi(wb, _note_di_lettura(turni, persone, postazioni))
    wb.save(FILE_USCITA)

    print(f'Scritto {FILE_USCITA}')
    print(f'  turni {len(turni)} · postazioni {postazioni} · '
          f'persone {len(persone)} · bersagli {len(bersagli)}')
    if collisioni:
        print('  COLLISIONI fra livelli:')
        for collisione in collisioni:
            print(f'    {collisione}')
    else:
        print('  nessuna collisione di nomi fra i livelli')


def _note_di_lettura(turni, persone, postazioni):
    """Il testo del foglio Leggimi: cosa e' letto e cosa e' proposto."""
    proposti = 'riempimento, necessita, giorni, festivi, superfestivi'
    return (
        ('Da dove viene', f'Generato da {MODELLO_ORIGINE}, foglio Tabelle, '
         f'con genera_config_turni.py. L originale non e stato modificato.'),
        ('Letto dal foglio', f'{len(turni)} turni raggruppati in '
         f'{postazioni} postazioni, {len(persone)} persone, sigle, '
         f'metodiche e tipi di richiesta.'),
        ('Proposto, da rivedere', f'Le colonne {proposti} di T_Turni: il '
         f'foglio originale non contiene questa informazione. I valori '
         f'attuali sono un default ragionevole, non un dato letto.'),
        ('Da compilare', 'T_Persone: sede e solo_sede_propria. '
         'T_Preferenze: tutte le regole.'),
        ('Livelli dei bersagli', 'fascia, metodica, sede, categoria, '
         'postazione (tutte le fasce di un posto), turno (una fascia sola).'),
        ('Modi delle regole', 'mai e solo sono assoluti; evita e preferisci '
         'pesano quanto dice T_Parametri. Piu regole solo su assi diversi '
         'si intersecano. mai batte solo batte i modi morbidi.'),
    )


if __name__ == '__main__':
    main()
