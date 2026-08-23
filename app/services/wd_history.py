"""
app/services/wd_history.py — history parallela per working_desiderata.

Stesso pattern di history.py ma usa tabelle wd_history / wd_history_ptr,
indipendente dalla history della griglia turni.
"""

import json
from flask import current_app

from app.db import query_one, query_all, execute_write


# ---------------------------------------------------------------------------
# Helpers puntatore
# ---------------------------------------------------------------------------

def _get_ptr(calendario_id):
    ptr = query_one(
        "SELECT current_step, max_step FROM wd_history_ptr WHERE calendario_id = ?",
        (calendario_id,)
    )
    if not ptr:
        execute_write(
            "INSERT INTO wd_history_ptr (calendario_id, current_step, max_step) VALUES (?,0,0)",
            (calendario_id,)
        )
        ptr = {'current_step': 0, 'max_step': 0}
    return ptr


def _set_ptr(calendario_id, current_step, max_step):
    execute_write(
        """
        INSERT INTO wd_history_ptr (calendario_id, current_step, max_step)
        VALUES (?,?,?)
        ON CONFLICT(calendario_id) DO UPDATE SET
            current_step = excluded.current_step,
            max_step     = excluded.max_step
        """,
        (calendario_id, current_step, max_step)
    )


# ---------------------------------------------------------------------------
# Aggiunta step
# ---------------------------------------------------------------------------

def wd_aggiungi_step(calendario_id, tabella, record_id, dati_precedenti,
                     dati_nuovi, user_id):
    max_steps = int(current_app.config.get('MAX_HISTORY_STEPS', 500))
    ptr = _get_ptr(calendario_id)
    current = ptr['current_step']

    execute_write(
        "DELETE FROM wd_history WHERE calendario_id = ? AND step > ?",
        (calendario_id, current)
    )

    nuovo_step = current + 1
    execute_write(
        """
        INSERT INTO wd_history
            (calendario_id, step, tabella, record_id,
             dati_precedenti, dati_nuovi, user_id)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            calendario_id, nuovo_step, tabella, record_id,
            json.dumps(dati_precedenti), json.dumps(dati_nuovi),
            user_id
        )
    )

    count = query_one(
        "SELECT COUNT(*) AS n FROM wd_history WHERE calendario_id = ?",
        (calendario_id,)
    )['n']

    if count > max_steps:
        min_step = query_one(
            "SELECT MIN(step) AS s FROM wd_history WHERE calendario_id = ?",
            (calendario_id,)
        )['s']
        execute_write(
            "DELETE FROM wd_history WHERE calendario_id = ? AND step = ?",
            (calendario_id, min_step)
        )
        tutti = query_all(
            "SELECT id FROM wd_history WHERE calendario_id = ? ORDER BY step ASC",
            (calendario_id,)
        )
        for i, row in enumerate(tutti, start=1):
            execute_write(
                "UPDATE wd_history SET step = ? WHERE id = ?",
                (i, row['id'])
            )
        nuovo_step = len(tutti)

    _set_ptr(calendario_id, nuovo_step, nuovo_step)


# ---------------------------------------------------------------------------
# Applica dati
# ---------------------------------------------------------------------------

def _applica_dati(tabella, record_id, dati, calendario_id=None):
    # Batch: dati è una lista di { tabella, record_id, dati }
    if tabella == 'ricarica_wd':
        # Ricarica: sostituzione totale — DELETE all + re-insert snapshot
        if calendario_id:
            execute_write("DELETE FROM working_desiderata WHERE calendario_id = ?",
                          (calendario_id,))
        for op in (dati or []):
            if op.get('dati'):
                _upsert_wd(op['dati'])
        return

    if tabella in ('azzera_wd', 'incolla_wd'):
        # Batch delete/restore: applica singolarmente (delete o upsert per ogni cella)
        for op in (dati or []):
            if op.get('dati'):
                _upsert_wd(op['dati'])
            else:
                # dati None/vuoto = la cella va cancellata (usa chiave naturale)
                c = op.get('calendario_id')
                u = op.get('user_id')
                g = op.get('giorno')
                if c and u and g:
                    execute_write(
                        "DELETE FROM working_desiderata "
                        "WHERE calendario_id=? AND user_id=? AND giorno=?",
                        (c, u, g))
        return

    if tabella != 'working_desiderata':
        raise ValueError(f'Tabella non ammessa per wd_history: {tabella} '
                         '(ammesse: working_desiderata, azzera_wd, incolla_wd, ricarica_wd)')

    if not dati:
        execute_write("DELETE FROM working_desiderata WHERE id = ?", (record_id,))
        return

    _upsert_wd(dati)


def _upsert_wd(dati):
    """Inserisce o aggiorna un record working_desiderata dallo snapshot history."""
    campi = {k: v for k, v in dati.items() if k != 'id'}
    if not campi:
        return
    cols = ', '.join(campi.keys())
    placeholders = ', '.join(['?'] * len(campi))
    set_parts = ', '.join(f"{k} = excluded.{k}" for k in campi
                          if k not in ('calendario_id', 'user_id', 'giorno'))
    execute_write(
        f"""INSERT INTO working_desiderata ({cols}) VALUES ({placeholders})
            ON CONFLICT(calendario_id, user_id, giorno) DO UPDATE SET {set_parts}""",
        list(campi.values())
    )


# ---------------------------------------------------------------------------
# Undo / Redo
# ---------------------------------------------------------------------------

def wd_undo(calendario_id, user_id):
    ptr = _get_ptr(calendario_id)
    current = ptr['current_step']

    if current <= 0:
        return {'ok': False, 'errore': 'Nessuna operazione da annullare.'}

    step_row = query_one(
        "SELECT * FROM wd_history WHERE calendario_id = ? AND step = ?",
        (calendario_id, current)
    )
    if not step_row:
        return {'ok': False, 'errore': f'Step {current} non trovato.'}

    dati = json.loads(step_row['dati_precedenti'])
    _applica_dati(step_row['tabella'], step_row['record_id'], dati,
                  calendario_id=calendario_id)

    _set_ptr(calendario_id, current - 1, ptr['max_step'])

    return {
        'ok': True,
        'messaggio': f'Undo WD step {current} completato.',
        'tabella': step_row['tabella'],
    }


def wd_redo(calendario_id, user_id):
    ptr = _get_ptr(calendario_id)
    current = ptr['current_step']
    max_s = ptr['max_step']

    if current >= max_s:
        return {'ok': False, 'errore': 'Nessuna operazione da ripetere.'}

    prossimo = current + 1
    step_row = query_one(
        "SELECT * FROM wd_history WHERE calendario_id = ? AND step = ?",
        (calendario_id, prossimo)
    )
    if not step_row:
        return {'ok': False, 'errore': f'Step {prossimo} non trovato.'}

    dati = json.loads(step_row['dati_nuovi'])
    _applica_dati(step_row['tabella'], step_row['record_id'], dati,
                  calendario_id=calendario_id)

    _set_ptr(calendario_id, prossimo, max_s)

    return {
        'ok': True,
        'messaggio': f'Redo WD step {prossimo} completato.',
        'tabella': step_row['tabella'],
    }


# ---------------------------------------------------------------------------
# Info
# ---------------------------------------------------------------------------

def wd_get_info_history(calendario_id):
    ptr = _get_ptr(calendario_id)
    total = query_one(
        "SELECT COUNT(*) AS n FROM wd_history WHERE calendario_id = ?",
        (calendario_id,)
    )['n']

    return {
        'current_step': ptr['current_step'],
        'max_step':     ptr['max_step'],
        'can_undo':     ptr['current_step'] > 0,
        'can_redo':     ptr['current_step'] < ptr['max_step'],
        'total_steps':  total,
    }
