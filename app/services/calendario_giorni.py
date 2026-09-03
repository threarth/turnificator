"""
app/services/calendario_giorni.py — che giorno e' ogni giorno del mese.

Nuova feature. Da qui discende il conteggio dei **turni dovuti**: sono i
giorni lavorativi del mese, e quali giorni siano lavorativi dipende dal
reparto. Sei giorni su sette in molti ospedali, cinque altrove.

Prima la regola era inchiodata nel codice — lavorativo tutto tranne la
domenica e le festivita' — e un reparto che chiude il sabato poteva solo
correggere a mano i giorni di ogni singolo mese.

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


def festivi_sono_lavorativi(config):
    """
    Un giorno festivo conta fra i turni dovuti?

    Args:
        config (dict): mappa chiave/valore della configurazione.

    Returns:
        bool: True se i festivi contano come lavorativi.
    """
    return str((config or {}).get('festivi_lavorativi', '0')) == '1'


def classifica_giorno(data, festivita, giorni_lavorativi, festivi_lavorativi):
    """
    Che giorno e' questo, per il calendario.

    La domenica e' festiva per definizione; le altre festivita' arrivano
    dall'elenco del calendario. Un giorno e' lavorativo se cade in un giorno
    della settimana in cui si lavora e non e' festivo — salvo che il reparto
    conti i festivi come lavorativi.

    Args:
        data (datetime.date): il giorno.
        festivita (dict): {'festivi': [iso], 'superfestivi': [iso]}.
        giorni_lavorativi (set): giorni della settimana lavorativi, 0 = lunedi'.
        festivi_lavorativi (bool): i festivi contano come lavorativi.

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

    nel_giro = data.weekday() in giorni_lavorativi
    if tipo == TIPO_NORMALE:
        return tipo, nel_giro

    return tipo, nel_giro and festivi_lavorativi


def conta_turni_dovuti(mese, anno, festivita, giorni_lavorativi, festivi_lavorativi):
    """
    Quanti turni deve un lavoratore in questo mese.

    Args:
        mese (int), anno (int): il mese da contare.
        festivita (dict): festivi e superfestivi del calendario.
        giorni_lavorativi (set): giorni della settimana lavorativi.
        festivi_lavorativi (bool): i festivi contano come lavorativi.

    Returns:
        int: numero di giorni lavorativi del mese.
    """
    import calendar

    quanti = calendar.monthrange(anno, mese)[1]
    return sum(
        1 for g in range(1, quanti + 1)
        if classifica_giorno(
            datetime.date(anno, mese, g), festivita,
            giorni_lavorativi, festivi_lavorativi
        )[1]
    )
