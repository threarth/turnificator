"""
tests/test_configurazioni.py — configurazioni salvate e commutabili.

Una configurazione e' l'intera impostazione del tenant congelata sotto un
nome. Attivarla riporta le tabelle a quello stato, conservando gli id perche'
gruppi, tipi richiesta e calendari chiusi vi puntano.
"""

import json

import pytest


@pytest.fixture
def tenant(app):
    """Contesto di richiesta sul tenant di prova, con la sua connessione."""
    with app.test_request_context('/'):
        from flask import g
        from app.db import get_db
        g.tenant_slug = 'testorg'
        yield get_db()


def _orari_mattina(db):
    """Gli orari della fascia mattina, che i test usano come sonda."""
    return db.execute(
        "SELECT orario_inizio, orario_fine FROM flag_turno WHERE nome = 'mattina'"
    ).fetchone()


# ---------------------------------------------------------------------------
# Gli invarianti
# ---------------------------------------------------------------------------

def test_una_configurazione_senza_concetti_strutturali_e_rifiutata(app):
    """turno_tipo, notturno e diurno sono l'impalcatura: non possono mancare."""
    from app.services.configurazioni import ConfigurazioneNonValida, verifica_invarianti

    with pytest.raises(ConfigurazioneNonValida) as errore:
        verifica_invarianti({'flag_turno': [{'nome': 'mattina'}]})

    assert 'turno_tipo' in str(errore.value)


def test_gli_invarianti_passano_se_i_concetti_ci_sono(app):
    """Il controllo guarda i nomi, non l'ordine ne' il resto della riga."""
    from app.services.configurazioni import verifica_invarianti

    verifica_invarianti({'flag_turno': [
        {'nome': 'diurno'}, {'nome': 'notturno'},
        {'nome': 'turno_tipo'}, {'nome': 'mattina'},
    ]})


# ---------------------------------------------------------------------------
# Salvare e riattivare
# ---------------------------------------------------------------------------

def test_riattivare_riporta_indietro_una_modifica(tenant):
    """Il caso d'uso: provo una configurazione diversa e torno alla prima."""
    from app.services.configurazioni import attiva_configurazione, salva_configurazione

    orari_iniziali = tuple(_orari_mattina(tenant))

    cfg_id = salva_configurazione(tenant, 'prova')

    tenant.execute(
        "UPDATE flag_turno SET orario_inizio='05:00', orario_fine='11:00' "
        "WHERE nome='mattina'"
    )
    tenant.commit()
    assert tenant.execute(
        "SELECT orario_inizio FROM flag_turno WHERE nome='mattina'"
    ).fetchone()[0] == '05:00'

    attiva_configurazione(tenant, cfg_id)

    assert tuple(_orari_mattina(tenant)) == orari_iniziali


def test_gli_id_dei_flag_non_cambiano(tenant):
    """gruppi.flag_id e gli snapshot dei calendari puntano a quegli id."""
    from app.services.configurazioni import attiva_configurazione, salva_configurazione

    id_prima = {r[0]: r[1] for r in tenant.execute("SELECT nome, id FROM flag_turno")}

    cfg_id = salva_configurazione(tenant, 'stabile')
    attiva_configurazione(tenant, cfg_id)

    id_dopo = {r[0]: r[1] for r in tenant.execute("SELECT nome, id FROM flag_turno")}
    assert id_dopo == id_prima


def test_salvare_due_volte_lo_stesso_nome_aggiorna(tenant):
    """La procedura guidata riaggiorna la sua, non ne accumula copie."""
    from app.services.configurazioni import salva_configurazione

    primo = salva_configurazione(tenant, 'unica')
    secondo = salva_configurazione(tenant, 'unica')

    assert primo == secondo
    assert tenant.execute(
        "SELECT COUNT(*) FROM configurazioni WHERE nome='unica'"
    ).fetchone()[0] == 1


def test_una_sola_configurazione_resta_attiva(tenant):
    """Il selettore globale ne accende una e spegne l'altra."""
    from app.services.configurazioni import attiva_configurazione, salva_configurazione

    a = salva_configurazione(tenant, 'alfa')
    b = salva_configurazione(tenant, 'beta')

    attiva_configurazione(tenant, a)
    attiva_configurazione(tenant, b)

    attive = tenant.execute(
        "SELECT nome FROM configurazioni WHERE is_attiva = 1"
    ).fetchall()
    assert [r[0] for r in attive] == ['beta']


def test_attivare_una_configurazione_inesistente_e_un_errore(tenant):
    """Meglio un errore parlante che un ripristino a vuoto."""
    from app.services.configurazioni import ConfigurazioneNonValida, attiva_configurazione

    with pytest.raises(ConfigurazioneNonValida):
        attiva_configurazione(tenant, 9999)
