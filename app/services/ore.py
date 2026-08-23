"""
app/services/ore.py — calcolo ore lavorative mensili e statistiche annuali.

Fornisce:
- calcola_ore_mensili(): conteggio ore per ogni lavoratore in un dato calendario
- calcola_statistiche_annuali(): riepilogo annuale per lavoratore

Logica ore:
    Ore lavorate effettive:
        Somma delle ore_lavorative di ogni giorno in cui il lavoratore
        è assegnato nella tabella assegnazioni_turni.

    Ore giustificate:
        Somma delle ore_lavorative di ogni giorno in cui il lavoratore
        ha una richiesta assenza con counting_flag=TRUE nei working_desiderata.

    Ore ROMC (Recupero Ore Mese Corrente):
        Non contano (counting_flag=FALSE).

    Totale ore contabilizzate = Ore lavorate + Ore giustificate

    Giorni festivi lavorati:
        Giorni in cui il lavoratore è assegnato E il giorno ha tipo='festivo'
        o tipo='superfestivo'.
"""

from app.db import query_all, query_one


# ---------------------------------------------------------------------------
# Ore mensili per singolo lavoratore
# ---------------------------------------------------------------------------

def calcola_ore_mensili(calendario_id):
    """
    Calcola il riepilogo ore mensile per tutti i lavoratori di un calendario.

    Per ogni lavoratore attivo con ruolo 'basic' restituisce:
        - ore_lavorate: ore dai turni effettivamente assegnati
        - ore_giustificate: ore da richieste assenza con counting_flag=TRUE
        - ore_totali: somma dei due
        - giorni_lavorati: numero di giorni con assegnazione turno
        - giorni_giustificati: numero di giorni con richiesta assenza counting=TRUE
        - giorni_festivi_lavorati: giorni festivi/superfestivi con assegnazione
        - giorni_superfestivi_lavorati: solo superfestivi con assegnazione

    Args:
        calendario_id (int): ID del calendario mensile.

    Returns:
        list[dict]: un dict per ogni lavoratore, con le chiavi descritte sopra
                    e in aggiunta 'user_id' e 'sigla'.
    """
    # Recupera parametri calendario
    cal = query_one(
        "SELECT ore_giornaliere_default FROM calendari WHERE id = ?",
        (calendario_id,)
    )
    if not cal:
        return []

    ore_default = cal['ore_giornaliere_default']

    # Tutti i lavoratori Basic attivi
    lavoratori = query_all(
        "SELECT id, sigla FROM users WHERE role = 'basic' AND is_active = 1",
        ()
    )

    # Tutti i giorni del calendario con le loro ore
    giorni = query_all(
        "SELECT giorno, is_lavorativo, ore_lavorative, tipo "
        "FROM giorni_calendario WHERE calendario_id = ?",
        (calendario_id,)
    )
    # Indicizza per accesso rapido: giorno → record
    mappa_giorni = {g['giorno']: g for g in giorni}
    num_giorni = max(mappa_giorni.keys()) if mappa_giorni else 0

    risultati = []

    for lav in lavoratori:
        uid = lav['id']

        # --- Ore da turni assegnati (con parametri per-turno dallo snapshot) ---
        assegnazioni = query_all(
            """
            SELECT at.giorno, ct.peso_turno, ct.ore_turno,
                   ct.ore_primo_giorno, ct.ore_ultimo_giorno
            FROM assegnazioni_turni at
            JOIN calendario_turni ct ON at.turno_id = ct.id
            WHERE at.calendario_id = ? AND at.user_id = ?
            """,
            (calendario_id, uid)
        )

        ore_lavorate = 0.0
        turni_lavorati = 0
        giorni_con_turno = set()
        giorni_festivi_lavorati = 0
        giorni_superfestivi_lavorati = 0

        for a in assegnazioni:
            giorno = a['giorno']
            g = mappa_giorni.get(giorno)
            if not g:
                continue

            # Peso turno (es. notte=2)
            peso = a['peso_turno'] if a['peso_turno'] is not None else 1
            turni_lavorati += peso

            # Ore: primo/ultimo giorno override, poi ore_turno, poi fallback giornaliero
            if giorno == 1 and a['ore_primo_giorno'] is not None:
                ore_g = a['ore_primo_giorno']
            elif giorno == num_giorni and a['ore_ultimo_giorno'] is not None:
                ore_g = a['ore_ultimo_giorno']
            elif a['ore_turno'] is not None:
                ore_g = a['ore_turno']
            else:
                ore_g = g['ore_lavorative'] if g['ore_lavorative'] is not None else ore_default
            ore_lavorate += ore_g

            # Conteggio giorni festivi (solo una volta per giorno)
            if giorno not in giorni_con_turno:
                giorni_con_turno.add(giorno)
                if g['tipo'] == 'festivo':
                    giorni_festivi_lavorati += 1
                elif g['tipo'] == 'superfestivo':
                    giorni_festivi_lavorati += 1
                    giorni_superfestivi_lavorati += 1

        # --- Ore da richieste assenza con counting_flag=TRUE ---
        wd_contabili = query_all(
            """
            SELECT wd.giorno
            FROM working_desiderata wd
            JOIN tipi_richiesta tr ON wd.tipo_richiesta_id = tr.id
            WHERE wd.calendario_id = ?
              AND wd.user_id = ?
              AND tr.tipo = 'assenza'
              AND tr.counting_flag = 1
            """,
            (calendario_id, uid)
        )

        ore_giustificate = 0.0
        giorni_giustificati = 0

        for wd in wd_contabili:
            g = mappa_giorni.get(wd['giorno'])
            if not g:
                continue
            ore_g = g['ore_lavorative'] if g['ore_lavorative'] is not None else ore_default
            ore_giustificate += ore_g
            giorni_giustificati += 1

        risultati.append({
            'user_id':                    uid,
            'sigla':                      lav['sigla'],
            'ore_lavorate':               round(ore_lavorate, 2),
            'ore_giustificate':           round(ore_giustificate, 2),
            'ore_totali':                 round(ore_lavorate + ore_giustificate, 2),
            'turni_lavorati':             turni_lavorati,
            'giorni_lavorati':            len(giorni_con_turno),
            'giorni_giustificati':        giorni_giustificati,
            'giorni_festivi_lavorati':    giorni_festivi_lavorati,
            'giorni_superfestivi_lavorati': giorni_superfestivi_lavorati,
        })

    return risultati


# ---------------------------------------------------------------------------
# Statistiche annuali
# ---------------------------------------------------------------------------

def calcola_statistiche_annuali(anno, escludi_ids=None):
    """
    Calcola le statistiche aggregate per tutti i lavoratori nell'anno indicato.

    Aggrega i dati di tutti i calendari (mesi) dell'anno specificato,
    escludendo quelli con ID in escludi_ids.

    Per ogni lavoratore restituisce:
        - ore_totali_anno: somma ore contabilizzate su tutti i mesi
        - giorni_festivi_anno: totale giorni festivi+superfestivi lavorati
        - giorni_superfestivi_anno: totale giorni superfestivi lavorati
        - mesi_dettaglio: lista con il dettaglio per ogni mese

    Args:
        anno (int): anno di cui calcolare le statistiche (es. 2026).
        escludi_ids (list[int]|None): ID calendari da escludere dal conteggio.

    Returns:
        list[dict]: un dict per ogni lavoratore attivo con le chiavi
                    descritte sopra, ordinati per sigla.
    """
    calendari = query_all(
        "SELECT id, mese FROM calendari WHERE anno = ? "
        "ORDER BY mese",
        (anno,)
    )

    if escludi_ids:
        escludi_set = set(escludi_ids)
        calendari = [c for c in calendari if c['id'] not in escludi_set]

    if not calendari:
        return []

    # Tutti i lavoratori
    lavoratori = query_all(
        "SELECT id, sigla FROM users WHERE role = 'basic' AND is_active = 1 "
        "ORDER BY sigla",
        ()
    )

    # Calcola ore per ogni calendario e aggrega
    aggregato = {
        lav['id']: {
            'user_id':               lav['id'],
            'sigla':                 lav['sigla'],
            'ore_totali_anno':       0.0,
            'giorni_festivi_anno':   0,
            'giorni_superfestivi_anno': 0,
            'mesi_dettaglio':        []
        }
        for lav in lavoratori
    }

    for cal in calendari:
        mese_dati = calcola_ore_mensili(cal['id'])
        for m in mese_dati:
            uid = m['user_id']
            if uid not in aggregato:
                continue
            aggregato[uid]['ore_totali_anno'] += m['ore_totali']
            aggregato[uid]['giorni_festivi_anno'] += m['giorni_festivi_lavorati']
            aggregato[uid]['giorni_superfestivi_anno'] += m['giorni_superfestivi_lavorati']
            aggregato[uid]['mesi_dettaglio'].append({
                'mese':            cal['mese'],
                'ore_totali':      m['ore_totali'],
                'giorni_lavorati': m['giorni_lavorati'],
            })

    risultati = list(aggregato.values())
    for r in risultati:
        r['ore_totali_anno'] = round(r['ore_totali_anno'], 2)

    return risultati
