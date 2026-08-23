"""
app/services/history.py — sistema di history per undo/redo per calendario.

Ogni modifica a desiderata, working_desiderata o assegnazioni_turni viene
registrata come uno step nella tabella history, associato al calendario.

Il puntatore corrente (current_step) è in history_ptr.
- Nuova modifica: aggiunge step N+1, cancella tutti i redo (step > N),
  aggiorna max_step se necessario. Se si supera MAX_HISTORY_STEPS,
  cancella il passo più vecchio e riscala.

- Undo: ripristina dati_precedenti dello step current_step, decrementa ptr.
- Redo: incrementa ptr, applica dati_nuovi dello step current_step+1.
"""

import json
from flask import current_app

from app.db import query_one, query_all, execute_write


# ---------------------------------------------------------------------------
# Helpers puntatore
# ---------------------------------------------------------------------------

def _get_ptr(calendario_id):
    """
    Restituisce il puntatore history corrente per il calendario.

    Se non esiste ancora, lo crea con step 0.

    Args:
        calendario_id (int): ID del calendario.

    Returns:
        dict: con chiavi 'current_step' e 'max_step'.
    """
    ptr = query_one(
        "SELECT current_step, max_step FROM history_ptr WHERE calendario_id = ?",
        (calendario_id,)
    )
    if not ptr:
        execute_write(
            "INSERT INTO history_ptr (calendario_id, current_step, max_step) VALUES (?,0,0)",
            (calendario_id,)
        )
        ptr = {'current_step': 0, 'max_step': 0}
    return ptr


def _set_ptr(calendario_id, current_step, max_step):
    """
    Aggiorna il puntatore history per il calendario.

    Args:
        calendario_id (int): ID del calendario.
        current_step (int): step corrente dopo l'operazione.
        max_step (int): step massimo disponibile (utile per redo).
    """
    execute_write(
        """
        INSERT INTO history_ptr (calendario_id, current_step, max_step)
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

def aggiungi_step(calendario_id, tabella, record_id, dati_precedenti,
                  dati_nuovi, user_id):
    """
    Registra una modifica nella history del calendario.

    Operazioni eseguite:
    1. Cancella tutti gli step 'redo' (> current_step): ogni nuova modifica
       invalida la storia futura.
    2. Aggiunge il nuovo step (current_step + 1).
    3. Se il numero totale di step supera MAX_HISTORY_STEPS, cancella il
       più vecchio e riscala tutti gli step (-1).
    4. Aggiorna il puntatore.

    Args:
        calendario_id (int): ID del calendario mensile.
        tabella (str): nome della tabella modificata
                       ('desiderata'|'working_desiderata'|'assegnazioni_turni').
        record_id (int): ID del record modificato.
        dati_precedenti (dict): snapshot del record PRIMA della modifica.
        dati_nuovi (dict): snapshot del record DOPO la modifica.
        user_id (int): ID dell'utente che ha effettuato la modifica.
    """
    max_steps = int(current_app.config.get('MAX_HISTORY_STEPS', 500))
    ptr = _get_ptr(calendario_id)
    current = ptr['current_step']

    # 1. Cancella redo (step futuri invalidati dalla nuova modifica)
    execute_write(
        "DELETE FROM history WHERE calendario_id = ? AND step > ?",
        (calendario_id, current)
    )

    # 2. Inserisce nuovo step
    nuovo_step = current + 1
    execute_write(
        """
        INSERT INTO history
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

    # 3. Gestione limite step: se superato, cancella il più vecchio
    count = query_one(
        "SELECT COUNT(*) AS n FROM history WHERE calendario_id = ?",
        (calendario_id,)
    )['n']

    if count > max_steps:
        # Trova e cancella lo step minimo
        min_step = query_one(
            "SELECT MIN(step) AS s FROM history WHERE calendario_id = ?",
            (calendario_id,)
        )['s']
        execute_write(
            "DELETE FROM history WHERE calendario_id = ? AND step = ?",
            (calendario_id, min_step)
        )
        # Riscala: aggiorna tutti gli step rimanenti
        # (sostituisce step con rank progressivo per mantenere la sequenza)
        tutti = query_all(
            "SELECT id FROM history WHERE calendario_id = ? ORDER BY step ASC",
            (calendario_id,)
        )
        for i, row in enumerate(tutti, start=1):
            execute_write(
                "UPDATE history SET step = ? WHERE id = ?",
                (i, row['id'])
            )
        nuovo_step = len(tutti)

    # 4. Aggiorna puntatore
    _set_ptr(calendario_id, nuovo_step, nuovo_step)


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

def undo(calendario_id, user_id):
    """
    Annulla l'ultima modifica del calendario (ripristina dati_precedenti).

    Recupera lo step corrente, ripristina i dati_precedenti nel record
    corrispondente e decrementa il puntatore.

    Args:
        calendario_id (int): ID del calendario mensile.
        user_id (int): ID dell'utente che richiede l'undo (solo per log).

    Returns:
        dict: con chiavi:
            - 'ok' (bool): True se undo eseguito con successo.
            - 'messaggio' (str): descrizione dell'operazione.
            - 'errore' (str): presente solo se ok=False.
    """
    ptr = _get_ptr(calendario_id)
    current = ptr['current_step']

    if current <= 0:
        return {'ok': False, 'errore': 'Nessuna operazione da annullare.'}

    step_row = query_one(
        "SELECT * FROM history WHERE calendario_id = ? AND step = ?",
        (calendario_id, current)
    )
    if not step_row:
        return {'ok': False, 'errore': f'Step {current} non trovato nella history.'}

    dati = json.loads(step_row['dati_precedenti'])
    dati_nuovi = json.loads(step_row['dati_nuovi'])
    _applica_dati(step_row['tabella'], step_row['record_id'], dati)

    _set_ptr(calendario_id, current - 1, ptr['max_step'])

    return {
        'ok': True,
        'messaggio': f'Undo step {current} completato (tabella: {step_row["tabella"]}).',
        'tabella': step_row['tabella'],
        'dati_applicati': dati,
        'dati_precedenti_step': dati_nuovi,
    }


# ---------------------------------------------------------------------------
# Redo
# ---------------------------------------------------------------------------

def redo(calendario_id, user_id):
    """
    Ripete l'ultima operazione annullata (applica dati_nuovi).

    Incrementa il puntatore e applica i dati_nuovi dello step successivo.

    Args:
        calendario_id (int): ID del calendario mensile.
        user_id (int): ID dell'utente che richiede il redo.

    Returns:
        dict: con chiavi:
            - 'ok' (bool): True se redo eseguito con successo.
            - 'messaggio' (str): descrizione dell'operazione.
            - 'errore' (str): presente solo se ok=False.
    """
    ptr = _get_ptr(calendario_id)
    current = ptr['current_step']
    max_s   = ptr['max_step']

    if current >= max_s:
        return {'ok': False, 'errore': 'Nessuna operazione da ripetere.'}

    prossimo = current + 1
    step_row = query_one(
        "SELECT * FROM history WHERE calendario_id = ? AND step = ?",
        (calendario_id, prossimo)
    )
    if not step_row:
        return {'ok': False, 'errore': f'Step {prossimo} non trovato nella history.'}

    dati = json.loads(step_row['dati_nuovi'])
    dati_prec = json.loads(step_row['dati_precedenti'])
    _applica_dati(step_row['tabella'], step_row['record_id'], dati)

    _set_ptr(calendario_id, prossimo, max_s)

    return {
        'ok': True,
        'messaggio': f'Redo step {prossimo} completato (tabella: {step_row["tabella"]}).',
        'tabella': step_row['tabella'],
        'dati_applicati': dati,
        'dati_precedenti_step': dati_prec,
    }


# ---------------------------------------------------------------------------
# Applicazione dati
# ---------------------------------------------------------------------------

def _applica_dati(tabella, record_id, dati):
    """
    Applica un dizionario di dati a un record esistente nella tabella indicata.

    Usato internamente da undo() e redo() per ripristinare o riapplicare
    uno stato precedente di un record. Se dati è None o vuoto, il record
    viene cancellato (ripristino di un inserimento).

    Args:
        tabella (str): nome della tabella ('desiderata', 'working_desiderata',
                       'assegnazioni_turni').
        record_id (int): ID del record da aggiornare.
        dati (dict | None): dizionario colonna→valore da applicare.
                            None = cancella il record (undo di un inserimento).
    """
    tabelle_ammesse = {'desiderata', 'working_desiderata', 'assegnazioni_turni', 'swap', 'solver', 'azzera', 'posti_fissi', 'optimizer', 'incolla'}
    if tabella not in tabelle_ammesse:
        raise ValueError(f'Tabella non ammessa per history: {tabella}')

    # Batch: dati è una lista di { tabella, record_id, dati }
    if tabella in ('swap', 'solver', 'azzera', 'posti_fissi', 'optimizer', 'incolla'):
        for op in (dati or []):
            _applica_dati(op['tabella'], op['record_id'], op.get('dati'))
        return

    if not dati:
        # Il record non esisteva prima: cancellalo
        execute_write(f"DELETE FROM {tabella} WHERE id = ?", (record_id,))
        return

    # Costruisce UPDATE dinamico escludendo 'id'
    campi = {k: v for k, v in dati.items() if k != 'id'}
    if not campi:
        return

    set_clause = ', '.join(f"{k} = ?" for k in campi)
    valori = list(campi.values()) + [record_id]
    execute_write(
        f"UPDATE {tabella} SET {set_clause} WHERE id = ?",
        valori
    )


# ---------------------------------------------------------------------------
# Info history
# ---------------------------------------------------------------------------

def get_info_history(calendario_id):
    """
    Restituisce informazioni sullo stato corrente della history per un calendario.

    Args:
        calendario_id (int): ID del calendario.

    Returns:
        dict: con chiavi:
            - 'current_step' (int): step corrente
            - 'max_step' (int): step massimo disponibile (per redo)
            - 'can_undo' (bool): True se è possibile fare undo
            - 'can_redo' (bool): True se è possibile fare redo
            - 'total_steps' (int): numero totale di step salvati
    """
    ptr = _get_ptr(calendario_id)
    total = query_one(
        "SELECT COUNT(*) AS n FROM history WHERE calendario_id = ?",
        (calendario_id,)
    )['n']

    return {
        'current_step': ptr['current_step'],
        'max_step':     ptr['max_step'],
        'can_undo':     ptr['current_step'] > 0,
        'can_redo':     ptr['current_step'] < ptr['max_step'],
        'total_steps':  total,
    }
