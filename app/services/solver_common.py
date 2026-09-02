"""
app/services/solver_common.py — contesto e funzioni condivise tra solver e optimizer.

Fornisce:
- Parsing esclusioni manuali e celle bloccate (JSON da calendari)
- Calcolo coefficiente disponibilita' e quote proporzionali
- Cost function pesata per optimizer
- Caricamento contesto completo (pre-processing Fase 1)
"""

import json
import math

from app.db import query_one, query_all
from app.services.config_snapshot import (
    carica_config_snapshot,
    snap_vincoli_globali, snap_vincoli_utente,
    snap_vincoli_solver, snap_vincoli_solver_utente,
    snap_flag_map,
)


# ---------------------------------------------------------------------------
# Parsing JSON calendari
# ---------------------------------------------------------------------------

def espandi_esclusioni_manuali(esclusioni_json, giorni_calendario):
    """
    Espande le esclusioni manuali JSON in una mappa giorno → set(user_id).

    Args:
        esclusioni_json: stringa JSON o lista di esclusioni.
        giorni_calendario: lista di dict con 'giorno' e info giorno della settimana.

    Returns:
        dict[int, set[int]]: giorno → set di user_id esclusi.
    """
    if isinstance(esclusioni_json, str):
        try:
            esclusioni = json.loads(esclusioni_json)
        except (json.JSONDecodeError, TypeError):
            return {}
    else:
        esclusioni = esclusioni_json or []

    # Mappa giorno → giorno della settimana (0=lun..6=dom)
    # Calcolata da anno/mese del calendario + giorno
    giorno_dow = {}
    for g in giorni_calendario:
        giorno_dow[g['giorno']] = g.get('dow')  # precomputato dal chiamante

    indisponibilita = {}

    for esc in esclusioni:
        uid = esc.get('user_id')
        if uid is None:
            continue
        tipo = esc.get('tipo')

        if tipo == 'giorno':
            g = esc.get('giorno')
            if g is not None:
                indisponibilita.setdefault(g, set()).add(uid)

        elif tipo == 'intervallo':
            g_da = esc.get('giorno_da', 1)
            g_a = esc.get('giorno_a', 31)
            for g in range(g_da, g_a + 1):
                if g in giorno_dow:  # giorno valido per questo mese
                    indisponibilita.setdefault(g, set()).add(uid)

        elif tipo == 'giorno_settimana':
            giorni_sett = esc.get('giorni_settimana', [])
            for g, dow in giorno_dow.items():
                if dow is not None and dow in giorni_sett:
                    indisponibilita.setdefault(g, set()).add(uid)

    return indisponibilita


def espandi_celle_bloccate(celle_json):
    """
    Espande le celle bloccate JSON in un set di tuple (turno_id, giorno).

    Args:
        celle_json: stringa JSON o lista di {turno_id, giorno}.

    Returns:
        set[(int, int)]: set di tuple (turno_id, giorno).
    """
    if isinstance(celle_json, str):
        try:
            celle = json.loads(celle_json)
        except (json.JSONDecodeError, TypeError):
            return set()
    else:
        celle = celle_json or []

    return {(c['turno_id'], c['giorno']) for c in celle
            if isinstance(c, dict) and 'turno_id' in c and 'giorno' in c}


# ---------------------------------------------------------------------------
# Equita' proporzionale
# ---------------------------------------------------------------------------

def calcola_coefficienti(utenti_ids, giorni_lavorativi_totali, indisponibilita,
                         wd_map):
    """
    Calcola il coefficiente di disponibilita' per ogni utente.

    coefficiente = giorni_disponibili / giorni_lavorativi_totali
    dove giorni_disponibili = giorni_lavorativi - giorni con assenza/esclusione manuale.

    Args:
        utenti_ids: lista di user_id.
        giorni_lavorativi_totali: numero giorni lavorativi nel mese.
        indisponibilita: dict giorno → set(user_id) da esclusioni manuali.
        wd_map: dict (user_id, giorno) → {req_tipo, req_flag_nome} da WD.

    Returns:
        dict[int, float]: user_id → coefficiente (0.0 .. 1.0).
    """
    if giorni_lavorativi_totali <= 0:
        return {uid: 0.0 for uid in utenti_ids}

    coefficienti = {}
    for uid in utenti_ids:
        giorni_indisponibili = 0
        for g in range(1, 32):
            # Escluso per esclusione manuale
            if g in indisponibilita and uid in indisponibilita[g]:
                giorni_indisponibili += 1
                continue
            # Escluso per WD assenza
            wd = wd_map.get((uid, g))
            if wd and wd.get('req_tipo') == 'assenza':
                giorni_indisponibili += 1

        disponibili = max(0, giorni_lavorativi_totali - giorni_indisponibili)
        coefficienti[uid] = disponibili / giorni_lavorativi_totali

    return coefficienti


def calcola_quote(valore_totale, coefficienti):
    """
    Calcola la quota proporzionale per ogni utente.

    Args:
        valore_totale: valore da distribuire (es. max_notti, ore_totali).
        coefficienti: dict user_id → coefficiente.

    Returns:
        dict[int, float]: user_id → quota.
    """
    return {uid: valore_totale * coeff for uid, coeff in coefficienti.items()}


# ---------------------------------------------------------------------------
# Cost function per optimizer
# ---------------------------------------------------------------------------

def calcola_costo_componente(stati, parametro, quote):
    """
    Calcola la varianza normalizzata per una componente della cost function.

    scarto(u) = (valore_attuale - quota) / max(quota, 1)
    costo = sum(scarto^2) / N

    Args:
        stati: dict user_id → stato running con il parametro.
        parametro: chiave nello stato (es. 'ore_mese', 'festivi_mese').
        quote: dict user_id → quota proporzionale.

    Returns:
        float: varianza normalizzata (0 = perfettamente equo).
    """
    if not stati:
        return 0.0
    scarti = []
    for uid, s in stati.items():
        quota = quote.get(uid, 1.0)
        valore = s.get(parametro, 0)
        scarto = (valore - quota) / max(quota, 1.0)
        scarti.append(scarto)
    n = len(scarti)
    if n == 0:
        return 0.0
    return sum(s ** 2 for s in scarti) / n


def calcola_costo_flag(stati, flag_id, quote_flag):
    """
    Calcola varianza normalizzata per conteggio assegnazioni di un flag specifico.

    Args:
        stati: dict user_id → stato running (contiene 'conteggio_flag').
        flag_id: ID del flag da bilanciare.
        quote_flag: dict user_id → quota per quel flag.

    Returns:
        float: varianza normalizzata.
    """
    if not stati:
        return 0.0
    scarti = []
    for uid, s in stati.items():
        quota = quote_flag.get(uid, 1.0)
        valore = s.get('conteggio_flag', {}).get(flag_id, 0)
        scarto = (valore - quota) / max(quota, 1.0)
        scarti.append(scarto)
    n = len(scarti)
    if n == 0:
        return 0.0
    return sum(s ** 2 for s in scarti) / n


def calcola_costo_peso_flag(stati, flag_id, quote_peso_flag):
    """
    Calcola varianza normalizzata per somma pesi turni di un flag specifico.

    Analogo a calcola_costo_flag ma usa peso_per_flag invece di conteggio_flag.

    Args:
        stati: dict user_id → stato running (contiene 'peso_per_flag').
        flag_id: ID del flag da bilanciare.
        quote_peso_flag: dict user_id → quota peso per quel flag.

    Returns:
        float: varianza normalizzata.
    """
    if not stati:
        return 0.0
    scarti = []
    for uid, s in stati.items():
        quota = quote_peso_flag.get(uid, 1.0)
        valore = s.get('peso_per_flag', {}).get(flag_id, 0)
        scarto = (valore - quota) / max(quota, 1.0)
        scarti.append(scarto)
    n = len(scarti)
    if n == 0:
        return 0.0
    return sum(s ** 2 for s in scarti) / n


def calcola_costo_wd(stati_wd, quote_wd=None):
    """
    Calcola varianza normalizzata per soddisfacimento WD.

    stati_wd: dict user_id → {richiesti: int, soddisfatti: int}
    quote_wd: se None, la quota e' 100% (soddisfatti == richiesti).

    Returns:
        float: varianza normalizzata.
    """
    if not stati_wd:
        return 0.0
    scarti = []
    for uid, sw in stati_wd.items():
        richiesti = sw.get('richiesti', 0)
        soddisfatti = sw.get('soddisfatti', 0)
        if richiesti <= 0:
            continue
        # Rapporto soddisfatti/richiesti: ideale = 1.0
        rapporto = soddisfatti / richiesti
        scarti.append(rapporto - 1.0)
    n = len(scarti)
    if n == 0:
        return 0.0
    return sum(s ** 2 for s in scarti) / n


def calcola_costo_totale(stati, pesi, ref_id=None,
                         quote_ore=None, quote_festivi=None,
                         quote_peso=None, quote_flag=None,
                         quote_peso_flag=None,
                         stati_wd=None):
    """
    Calcola il costo totale pesato per l'optimizer.

    Args:
        stati: dict user_id → stato running.
        pesi: dict con chiavi 'ore', 'target', 'festivi', 'peso', 'varieta', 'desiderata'.
        ref_id: flag_turno.id per preset per_flag (None = completo).
        quote_ore: dict user_id → quota ore.
        quote_festivi: dict user_id → quota festivi.
        quote_peso: dict user_id → quota peso turni (globale).
        quote_flag: dict user_id → quota conteggio per il flag target.
        quote_peso_flag: dict user_id → quota peso per il flag target.
        stati_wd: dict user_id → {richiesti, soddisfatti}.

    Returns:
        float: costo totale.
    """
    p = {
        'ore': pesi.get('ore', 1.0),
        'target': pesi.get('target', 1.0),
        'festivi': pesi.get('festivi', 1.0),
        'peso': pesi.get('peso', 1.0),
        'varieta': pesi.get('varieta', 1.0),
        'desiderata': pesi.get('desiderata', 1.0),
    }

    costo = 0.0

    # Ore
    if quote_ore and p['ore'] > 0:
        costo += p['ore'] * calcola_costo_componente(stati, 'ore_mese', quote_ore)

    # Target (flag-based)
    if quote_flag and p['target'] > 0 and ref_id is not None:
        costo += p['target'] * calcola_costo_flag(stati, ref_id, quote_flag)

    # Festivi
    if quote_festivi and p['festivi'] > 0:
        costo += p['festivi'] * calcola_costo_componente(stati, 'festivi_mese', quote_festivi)

    # Peso turni: se ref_id presente usa peso filtrato per flag, altrimenti globale
    if p['peso'] > 0:
        if ref_id is not None and quote_peso_flag:
            costo += p['peso'] * calcola_costo_peso_flag(stati, ref_id, quote_peso_flag)
        elif quote_peso:
            costo += p['peso'] * calcola_costo_componente(stati, 'peso_totale', quote_peso)

    # Desiderata (WD soddisfatti)
    if stati_wd and p['desiderata'] > 0:
        costo += p['desiderata'] * calcola_costo_wd(stati_wd)

    return costo


# ---------------------------------------------------------------------------
# Giorni della settimana (helper per esclusioni manuali)
# ---------------------------------------------------------------------------

def arricchisci_giorni_con_dow(giorni_info, mese, anno):
    """
    Aggiunge il campo 'dow' (day of week, 0=lun..6=dom) a ogni giorno.

    Args:
        giorni_info: lista di dict con 'giorno'.
        mese: mese del calendario.
        anno: anno del calendario.

    Returns:
        lista arricchita (modifica in-place e ritorna).
    """
    import calendar
    for g in giorni_info:
        try:
            dow = calendar.weekday(anno, mese, g['giorno'])
            g['dow'] = dow
        except ValueError:
            g['dow'] = None
    return giorni_info
