"""
app/services/auto_close.py — Auto-chiusura calendari EFFETTIVO dopo il 7° giorno del mese successivo.

Chiamato in modalità check-on-access (quando si caricano calendari o strutture).
"""

import time
from datetime import datetime, date
from app.db import query_all, execute_write

_last_check = 0
_CHECK_INTERVAL_SEC = 300  # controlla al massimo ogni 5 minuti


def controlla_auto_chiusura_effettivi():
    """
    Chiude automaticamente i calendari EFFETTIVO aperti il cui mese di riferimento
    è passato da almeno 7 giorni (configurabile).

    Es. calendario effettivo mese=3, anno=2026:
    - Il mese successivo è aprile 2026
    - Se oggi >= 7 aprile 2026 → chiudi

    La history dell'effettivo viene preservata: alla chiusura le scritture
    sono già bloccate dalle guard di route, ma i record di history restano
    disponibili in caso di riapertura manuale.
    """
    global _last_check
    now = time.time()
    if now - _last_check < _CHECK_INTERVAL_SEC:
        return
    _last_check = now

    oggi = date.today()

    effettivi_aperti = query_all(
        "SELECT id, mese, anno FROM calendari "
        "WHERE tipo='effettivo' AND stato='APERTO'"
    )

    for eff in effettivi_aperti:
        mese = eff['mese']
        anno = eff['anno']

        # Calcola il primo giorno del mese successivo
        if mese == 12:
            mese_succ, anno_succ = 1, anno + 1
        else:
            mese_succ, anno_succ = mese + 1, anno

        # Giorno limite: 7° giorno del mese successivo
        deadline = date(anno_succ, mese_succ, 7)

        if oggi >= deadline:
            chiuso_il = datetime.utcnow().isoformat()
            execute_write(
                "UPDATE calendari SET stato='CHIUSO', chiuso_il=? WHERE id=?",
                (chiuso_il, eff['id']))
