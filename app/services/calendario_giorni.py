"""
app/services/calendario_giorni.py — che giorno e' ogni giorno del mese.

Nuova feature. Da qui discende il conteggio dei **turni dovuti**: sono i
giorni lavorativi del mese, e quali giorni siano lavorativi dipende dal
reparto. Sei giorni su sette in molti ospedali, cinque altrove.

Prima la regola era inchiodata nel codice — lavorativo tutto tranne la
domenica e le festivita' — e un reparto che chiude il sabato poteva solo
correggere a mano i giorni di ogni singolo mese.

Festivi e superfestivi non sono mai dovuti. Lavorare un festivo e' sempre un
turno **in piu'**, che matura un recupero: il conteggio di cio' che il
lavoratore ha svolto passa dai pesi dei turni assegnati, dove una lunga o una
notte valgono due.

Convenzione dei giorni della settimana: **0 = lunedi', 6 = domenica**, la
stessa di `date.weekday()` e di `arricchisci_giorni_con_dow`. Attenzione che
i conteggi del context menu usano l'altra, 0 = domenica.
"""

import datetime

# Sei giorni su sette: e' il comportamento che il sistema aveva prima che la
# cosa fosse impostabile, e resta il ripiego.
GIORNI_LAVORATIVI_DEFAULT = (0, 1, 2, 3, 4, 5)

DOMENICA = 6

TIPO_NORMALE = 'normale'
TIPO_FESTIVO = 'festivo'
TIPO_SUPERFESTIVO = 'superfestivo'

# Chiavi con cui le date festive viaggiano fra chi le calcola e chi classifica
# i giorni. Sono i plurali dei tipi, ma scritte: derivarle dal singolare e'
# stato un errore che ha prodotto 'festivoi'.
CHIAVE_FESTIVI = 'festivi'
CHIAVE_SUPERFESTIVI = 'superfestivi'


def leggi_giorni_lavorativi(config):
    """
    I giorni della settimana in cui il reparto lavora.

    Args:
        config (dict): mappa chiave/valore della configurazione.

    Returns:
        set: numeri dei giorni, 0 = lunedi'. Il default se il valore manca o
             non e' leggibile — meglio il comportamento noto che nessun
             giorno lavorativo.
    """
    grezzo = (config or {}).get('giorni_lavorativi_settimana')
    if not grezzo:
        return set(GIORNI_LAVORATIVI_DEFAULT)

    giorni = set()
    for pezzo in str(grezzo).split(','):
        pezzo = pezzo.strip()
        if pezzo.isdigit() and 0 <= int(pezzo) <= DOMENICA:
            giorni.add(int(pezzo))

    return giorni or set(GIORNI_LAVORATIVI_DEFAULT)


def pasqua(anno):
    """
    La domenica di Pasqua di un anno, con l'algoritmo di Gauss.

    Serve perche' due festivita' su tredici non hanno una data fissa: Pasqua
    e il lunedi' dopo si spostano ogni anno, e con loro tutto cio' che si
    conta a partire da li'.

    Args:
        anno (int): anno gregoriano.

    Returns:
        datetime.date: la domenica di Pasqua.
    """
    a = anno % 19
    b = anno // 100
    c = anno % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mese = (h + l - 7 * m + 114) // 31
    giorno = ((h + l - 7 * m + 114) % 31) + 1

    return datetime.date(anno, mese, giorno)


def data_della_ricorrenza(ricorrenza, anno):
    """
    La data che una ricorrenza assume in un dato anno.

    Una ricorrenza o cade sempre nello stesso giorno dell'anno, o si conta
    dalla Pasqua. Le due cose si escludono, e lo schema lo impone.

    Args:
        ricorrenza (dict): riga di `festivita`, con giorno, mese, offset_pasqua.
        anno (int): anno per cui calcolarla.

    Returns:
        datetime.date|None: la data, o None se la riga non individua un giorno
                            valido — un 29 febbraio in un anno non bisestile,
                            per dire, che semplicemente non cade.
    """
    offset = ricorrenza.get('offset_pasqua')
    if offset is not None:
        return pasqua(anno) + datetime.timedelta(days=int(offset))

    giorno, mese = ricorrenza.get('giorno'), ricorrenza.get('mese')
    if giorno is None or mese is None:
        return None

    try:
        return datetime.date(anno, int(mese), int(giorno))
    except ValueError:
        return None


def espandi_festivita(ricorrenze, anno):
    """
    Traduce le ricorrenze configurate nelle date concrete di un anno.

    Args:
        ricorrenze (iterable): righe di `festivita` attive.
        anno (int): anno del calendario.

    Returns:
        dict: {'festivi': [iso], 'superfestivi': [iso]}, nella forma che
              classifica_giorno() sa gia' leggere.
    """
    esito = {CHIAVE_FESTIVI: [], CHIAVE_SUPERFESTIVI: []}

    for r in ricorrenze or []:
        if not r.get('is_active', 1):
            continue
        data = data_della_ricorrenza(r, anno)
        if data is None:
            continue
        chiave = (CHIAVE_SUPERFESTIVI if r.get('tipo') == TIPO_SUPERFESTIVO
                  else CHIAVE_FESTIVI)
        esito[chiave].append(data.isoformat())

    return esito


def classifica_giorno(data, festivita, giorni_lavorativi):
    """
    Che giorno e' questo, per il calendario.

    La domenica e' festiva per definizione; le altre festivita' arrivano
    dall'elenco del calendario. Un giorno e' lavorativo — cioe' dovuto — se
    cade in un giorno della settimana in cui si lavora e non e' festivo.

    Args:
        data (datetime.date): il giorno.
        festivita (dict): {'festivi': [iso], 'superfestivi': [iso]}.
        giorni_lavorativi (set): giorni della settimana lavorativi, 0 = lunedi'.

    Returns:
        tuple: (tipo, is_lavorativo) con tipo normale|festivo|superfestivo.
    """
    iso = data.isoformat()
    festivita = festivita or {}

    if iso in festivita.get('superfestivi', []):
        tipo = TIPO_SUPERFESTIVO
    elif iso in festivita.get('festivi', []) or data.weekday() == DOMENICA:
        tipo = TIPO_FESTIVO
    else:
        tipo = TIPO_NORMALE

    return tipo, tipo == TIPO_NORMALE and data.weekday() in giorni_lavorativi


def conta_turni_dovuti(mese, anno, festivita, giorni_lavorativi):
    """
    Quanti turni deve un lavoratore in questo mese.

    Args:
        mese (int), anno (int): il mese da contare.
        festivita (dict): festivi e superfestivi del calendario.
        giorni_lavorativi (set): giorni della settimana lavorativi.

    Returns:
        int: numero di giorni lavorativi del mese.
    """
    import calendar

    quanti = calendar.monthrange(anno, mese)[1]
    return sum(
        1 for g in range(1, quanti + 1)
        if classifica_giorno(
            datetime.date(anno, mese, g), festivita, giorni_lavorativi
        )[1]
    )
