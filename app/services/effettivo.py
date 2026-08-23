"""
app/services/effettivo.py — Servizio copia calendari per workflow CHIUSO/EFFETTIVO.

Fornisce:
- crea_copia_calendario(): copia generica di un calendario con tutte le tabelle dipendenti
- crea_copia_effettivo(): crea EFFETTIVO da un calendario CHIUSO (con originale_user_id)
- effettivo_ha_modifiche(): controlla se l'EFFETTIVO ha assegnazioni diverse dall'originale
"""

from app.db import query_one, query_all, execute_write, execute_many


def crea_copia_calendario(cal_id, tipo_dest, stato_dest, set_originale=False,
                          versione_override=None):
    """
    Crea una copia completa di un calendario con tutte le tabelle dipendenti.

    Args:
        cal_id: ID del calendario sorgente
        tipo_dest: 'programmato' o 'effettivo'
        stato_dest: stato iniziale del nuovo calendario
        set_originale: se True, copia user_id → originale_user_id nelle assegnazioni
        versione_override: se specificato, usa questa versione invece di quella sorgente

    Returns:
        int: ID del nuovo calendario
    """
    cal = query_one("SELECT * FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        raise ValueError(f"Calendario {cal_id} non trovato")

    versione = versione_override if versione_override is not None else cal['versione']

    # Inserisci nuovo calendario
    cur = execute_write(
        """INSERT INTO calendari
           (mese, anno, stato, ore_giornaliere_default, deadline_globale,
            desiderata_congelati, preset_id, style, regole_snapshot,
            config_snapshot, esclusioni_manuali, celle_bloccate,
            chiuso_il, versione, tipo, parent_id, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (cal['mese'], cal['anno'], stato_dest,
         cal['ore_giornaliere_default'], cal['deadline_globale'],
         cal['desiderata_congelati'], cal['preset_id'],
         cal['style'], cal['regole_snapshot'],
         cal['config_snapshot'], cal['esclusioni_manuali'],
         cal['celle_bloccate'], cal['chiuso_il'],
         versione, tipo_dest, cal_id, cal['created_by'])
    )
    new_cal_id = cur.lastrowid

    # Copia calendario_turni e costruisci mappa old_id → new_id
    turni = query_all(
        "SELECT * FROM calendario_turni WHERE calendario_id=?", (cal_id,))
    turno_map = {}
    for t in turni:
        cur = execute_write(
            """INSERT INTO calendario_turni
               (calendario_id, local_id, sigla, nome, flag_nome, flag_id,
                tipi_qualitativi, gruppo_id, gruppo_sigla, gruppo_nome,
                gruppo_ordine, sg_sigla, sg_nome, sg_ambito, sg_ordine,
                sg_style, ordine, style, turno_style,
                peso_turno, ore_turno, ore_primo_giorno, ore_ultimo_giorno,
                priorita_solver, peso_priorita_solver,
                apri_festivi, apri_superfestivi,
                is_disabled, is_hidden)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (new_cal_id, t['local_id'], t['sigla'], t['nome'],
             t['flag_nome'], t['flag_id'], t['tipi_qualitativi'],
             t['gruppo_id'], t['gruppo_sigla'], t['gruppo_nome'],
             t['gruppo_ordine'], t['sg_sigla'], t['sg_nome'],
             t['sg_ambito'], t['sg_ordine'], t['sg_style'],
             t['ordine'], t['style'], t['turno_style'],
             t['peso_turno'], t['ore_turno'],
             t['ore_primo_giorno'], t['ore_ultimo_giorno'],
             t['priorita_solver'], t['peso_priorita_solver'],
             t['apri_festivi'], t['apri_superfestivi'],
             t.get('is_disabled', 0), t.get('is_hidden', 0))
        )
        turno_map[t['id']] = cur.lastrowid

    # Copia assegnazioni_turni con rimappatura turno_id
    assegnazioni = query_all(
        "SELECT * FROM assegnazioni_turni WHERE calendario_id=?", (cal_id,))
    for a in assegnazioni:
        new_turno_id = turno_map.get(a['turno_id'])
        if not new_turno_id:
            continue
        originale = a['user_id'] if set_originale else a.get('originale_user_id')
        execute_write(
            """INSERT INTO assegnazioni_turni
               (calendario_id, turno_id, giorno, user_id, originale_user_id,
                forza_inserimento, forza_note, conflitto, conflitti,
                updated_at, updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (new_cal_id, new_turno_id, a['giorno'], a['user_id'],
             originale, a['forza_inserimento'], a['forza_note'],
             a['conflitto'], a['conflitti'],
             a['updated_at'], a['updated_by'])
        )

    # Copia giorni_calendario
    giorni = query_all(
        "SELECT * FROM giorni_calendario WHERE calendario_id=?", (cal_id,))
    for g in giorni:
        execute_write(
            """INSERT INTO giorni_calendario
               (calendario_id, giorno, is_lavorativo, tipo)
               VALUES (?,?,?,?)""",
            (new_cal_id, g['giorno'], g['is_lavorativo'], g['tipo'])
        )

    # Copia working_desiderata
    wds = query_all(
        "SELECT * FROM working_desiderata WHERE calendario_id=?", (cal_id,))
    for w in wds:
        execute_write(
            """INSERT INTO working_desiderata
               (calendario_id, user_id, giorno, tipo_richiesta_id, note)
               VALUES (?,?,?,?,?)""",
            (new_cal_id, w['user_id'], w['giorno'],
             w['tipo_richiesta_id'], w['note'])
        )

    # Inizializza history_ptr e wd_history_ptr
    execute_write(
        "INSERT OR IGNORE INTO history_ptr (calendario_id, current_step, max_step) "
        "VALUES (?,0,0)", (new_cal_id,))
    execute_write(
        "INSERT OR IGNORE INTO wd_history_ptr (calendario_id, current_step, max_step) "
        "VALUES (?,0,0)", (new_cal_id,))

    return new_cal_id


def crea_copia_effettivo(cal_principale_id):
    """Crea un calendario EFFETTIVO da un calendario principale chiuso."""
    return crea_copia_calendario(
        cal_principale_id, 'effettivo', 'APERTO', set_originale=True)


def effettivo_ha_modifiche(effettivo_id):
    """Controlla se l'EFFETTIVO ha assegnazioni diverse dall'originale."""
    row = query_one(
        """SELECT COUNT(*) AS cnt FROM assegnazioni_turni
           WHERE calendario_id=?
             AND (
                 (user_id IS NOT NULL AND originale_user_id IS NULL)
                 OR (user_id IS NULL AND originale_user_id IS NOT NULL)
                 OR (user_id != originale_user_id)
             )""",
        (effettivo_id,))
    return (row['cnt'] or 0) > 0
