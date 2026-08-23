"""
app/services/calendario_state.py — helper per controlli stato calendario.

Centralizza il pattern duplicato:
    cal = query_one("SELECT ... FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404
    if cal['stato'] != 'APERTO':
        return jsonify({'ok': False, 'errore': 'Calendario chiuso ...'}), 400

Pattern post-refactor:
    from app.services.calendario_state import ottieni_calendario_aperto
    cal = ottieni_calendario_aperto(cal_id, "id, stato, tipo")  # solleva su 404/400

Errore tipato (CalendarioStateError) gestito da error handler in app/__init__.py.
"""

from app.db import query_one


class CalendarioStateError(Exception):
    """Errore di stato calendario per route HTTP. Convertito in JSON dal
    handler registrato in app/__init__.py."""

    def __init__(self, status, errore):
        super().__init__(errore)
        self.status = status
        self.errore = errore


def ottieni_calendario_aperto(cal_id, campi='id, stato'):
    """
    Carica un calendario verificando esistenza e stato APERTO.

    Args:
        cal_id (int): ID del calendario.
        campi (str): elenco campi SQL separati da virgola da includere nel
            SELECT. Deve sempre includere 'stato' (necessario per il check).
            Default: 'id, stato'.

    Returns:
        dict: il record del calendario.

    Raises:
        CalendarioStateError: 404 se non trovato, 400 se stato != 'APERTO'.
    """
    cal = query_one(f"SELECT {campi} FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        raise CalendarioStateError(404, 'Calendario non trovato.')
    if cal['stato'] != 'APERTO':
        raise CalendarioStateError(400, 'Calendario chiuso, modifiche non permesse.')
    return cal


def ottieni_calendario_o_404(cal_id, campi='id, stato'):
    """
    Carica un calendario verificando solo l'esistenza (no check stato).

    Usato dalle route che operano su calendari in qualsiasi stato (es. lettura,
    chiudi/riapri).

    Raises:
        CalendarioStateError: 404 se non trovato.
    """
    cal = query_one(f"SELECT {campi} FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        raise CalendarioStateError(404, 'Calendario non trovato.')
    return cal
