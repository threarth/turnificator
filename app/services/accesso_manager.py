"""
Accesso manager — helper per verificare restrizioni manager→utenti e manager→turni.

Modello whitelist lato entità:
- Utente/turno SENZA righe nella tabella accesso = "Tutti" (qualsiasi manager può operare)
- Utente/turno CON righe = solo i manager elencati possono operare
- Sentinel manager_id=0: indica "ristretto a nessun manager" (nessuno può operare)
"""

from app.db import query_all, query_one


def get_turni_accessibili(manager_id):
    """Restituisce set di preset_turno_id accessibili, o None se nessuna restrizione.
    Include turni esplicitamente assegnati a questo manager + turni con 'Tutti' (nessuna riga)."""
    # Turni esplicitamente assegnati a questo manager
    rows_diretti = query_all(
        "SELECT preset_turno_id FROM manager_accesso_turni WHERE manager_id=?",
        (manager_id,)
    )
    if not rows_diretti:
        # Manager senza restrizioni proprie: potrebbe comunque essere bloccato
        # da turni con sentinel. Ma il check puntuale lo fa manager_puo_turno.
        return None
    return {r['preset_turno_id'] for r in rows_diretti}


def get_utenti_accessibili(manager_id):
    """Restituisce set di user_id accessibili, o None se nessuna restrizione.
    Include utenti esplicitamente assegnati a questo manager + utenti con 'Tutti' (nessuna riga)."""
    rows_diretti = query_all(
        "SELECT user_id FROM manager_accesso_utenti WHERE manager_id=?",
        (manager_id,)
    )
    if not rows_diretti:
        return None
    return {r['user_id'] for r in rows_diretti}


def _turno_ristretto_a_nessuno(preset_turno_id):
    """True se il turno ha il sentinel (manager_id=0) = ristretto a nessun manager."""
    row = query_one(
        "SELECT 1 FROM manager_accesso_turni WHERE preset_turno_id=? AND manager_id=0",
        (preset_turno_id,)
    )
    return row is not None


def _utente_ristretto_a_nessuno(user_id):
    """True se l'utente ha il sentinel (manager_id=0) = nessun manager può gestirlo."""
    row = query_one(
        "SELECT 1 FROM manager_accesso_utenti WHERE user_id=? AND manager_id=0",
        (user_id,)
    )
    return row is not None


def _turno_ha_restrizioni(preset_turno_id):
    """True se il turno ha righe nella tabella accesso (non è 'Tutti')."""
    row = query_one(
        "SELECT 1 FROM manager_accesso_turni WHERE preset_turno_id=? LIMIT 1",
        (preset_turno_id,)
    )
    return row is not None


def _utente_ha_restrizioni(user_id):
    """True se l'utente ha righe nella tabella accesso (non è 'Tutti')."""
    row = query_one(
        "SELECT 1 FROM manager_accesso_utenti WHERE user_id=? LIMIT 1",
        (user_id,)
    )
    return row is not None


def manager_puo_turno(manager_id, preset_turno_id):
    """True se il manager può operare su questo turno (preset_turno_id)."""
    # Check lato turno: sentinel = nessun manager può operare
    if _turno_ristretto_a_nessuno(preset_turno_id):
        return False
    # Turno senza restrizioni ("Tutti") → qualsiasi manager può operare
    if not _turno_ha_restrizioni(preset_turno_id):
        return True
    # Turno con restrizioni → check se questo manager è nella lista
    row = query_one(
        "SELECT 1 FROM manager_accesso_turni WHERE preset_turno_id=? AND manager_id=?",
        (preset_turno_id, manager_id)
    )
    return row is not None


def manager_puo_utente(manager_id, user_id):
    """True se il manager può operare su questo utente."""
    # Check lato utente: sentinel = nessun manager può operare
    if _utente_ristretto_a_nessuno(user_id):
        return False
    # Utente senza restrizioni ("Tutti") → qualsiasi manager può operare
    if not _utente_ha_restrizioni(user_id):
        return True
    # Utente con restrizioni → check se questo manager è nella lista
    row = query_one(
        "SELECT 1 FROM manager_accesso_utenti WHERE user_id=? AND manager_id=?",
        (user_id, manager_id)
    )
    return row is not None
