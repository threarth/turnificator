"""
app/services/style_history.py — Storico modifiche formattazione (undo).

Ogni entry rappresenta una singola operazione "Applica" nel context menu
di formattazione. Contiene un array JSON di item modificati con before/after.

Cap: 10 entry per (contesto, contesto_id).
"""

import json

from app.db import query_one, query_all, execute_write

MAX_STYLE_HISTORY = 10


def push_style_history(contesto, contesto_id, items):
    """
    Inserisce una nuova entry e mantiene il cap a MAX_STYLE_HISTORY.

    Args:
        contesto: 'preset' | 'calendario'
        contesto_id: ID del preset o calendario
        items: lista di dict con {tipo, id/sigla, campo, tab, style_before, style_after}

    Returns:
        int: numero di entry disponibili per undo
    """
    execute_write(
        "INSERT INTO style_history (contesto, contesto_id, items) VALUES (?,?,?)",
        (contesto, contesto_id, json.dumps(items))
    )

    # Cap: elimina le entry più vecchie oltre il limite
    count = _count(contesto, contesto_id)
    if count > MAX_STYLE_HISTORY:
        execute_write(
            "DELETE FROM style_history WHERE id IN ("
            "  SELECT id FROM style_history "
            "  WHERE contesto=? AND contesto_id=? "
            "  ORDER BY id ASC LIMIT ?"
            ")",
            (contesto, contesto_id, count - MAX_STYLE_HISTORY)
        )

    return min(count, MAX_STYLE_HISTORY)


def pop_style_history(contesto, contesto_id):
    """
    Restituisce e rimuove l'ultima entry (per undo).

    Returns:
        list | None: array di items parsato, o None se vuoto
    """
    row = query_one(
        "SELECT id, items FROM style_history "
        "WHERE contesto=? AND contesto_id=? ORDER BY id DESC LIMIT 1",
        (contesto, contesto_id)
    )
    if not row:
        return None

    execute_write("DELETE FROM style_history WHERE id=?", (row['id'],))
    return json.loads(row['items'])


def count_style_history(contesto, contesto_id):
    """Restituisce il numero di entry disponibili per undo."""
    return _count(contesto, contesto_id)


def _count(contesto, contesto_id):
    row = query_one(
        "SELECT COUNT(*) AS cnt FROM style_history "
        "WHERE contesto=? AND contesto_id=?",
        (contesto, contesto_id)
    )
    return row['cnt'] if row else 0
