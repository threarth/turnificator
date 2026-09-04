"""
tests/test_preferenza_struttura.py — la preferenza per la propria struttura.

Di default il solver ignora la struttura del lavoratore: Tizio di Radiologia
finisce indifferentemente in Radiologia o altrove. Alzando il vincolo globale
`preferenza_struttura` chi lavora dove appartiene riceve un vantaggio nel
punteggio di scelta — un vantaggio, non un divieto: se serve, il solver lo
manda comunque altrove.

Il punteggio e' un rapporto in cui vince il piu' basso, quindi il vantaggio
e' uno sconto.
"""

import pytest


STRUTTURA_A = 1
STRUTTURA_B = 2


@pytest.fixture
def vantaggio(app):
    from app.services.solver import _vantaggio_struttura
    return _vantaggio_struttura


def test_senza_peso_la_struttura_non_conta(vantaggio):
    """E' il comportamento di sempre: assegnazione indifferente."""
    stato = {'sovragruppo_id': STRUTTURA_A}

    assert vantaggio(stato, STRUTTURA_A, 0) == 0.0
    assert vantaggio(stato, STRUTTURA_B, 0) == 0.0


def test_chi_e_di_casa_riceve_lo_sconto(vantaggio):
    stato = {'sovragruppo_id': STRUTTURA_A}
    assert vantaggio(stato, STRUTTURA_A, 0.5) == 0.5


def test_chi_viene_da_fuori_non_riceve_nulla(vantaggio):
    """Non e' una penalita': e' l'assenza del vantaggio."""
    stato = {'sovragruppo_id': STRUTTURA_A}
    assert vantaggio(stato, STRUTTURA_B, 0.5) == 0.0


def test_chi_non_ha_struttura_non_e_ne_favorito_ne_penalizzato(vantaggio):
    assert vantaggio({'sovragruppo_id': None}, STRUTTURA_A, 0.5) == 0.0


def test_un_turno_senza_struttura_non_attiva_la_preferenza(vantaggio):
    stato = {'sovragruppo_id': STRUTTURA_A}
    assert vantaggio(stato, None, 0.5) == 0.0


def test_il_vincolo_globale_di_serie_e_indifferente(client, admin_token, auth):
    """Chi aggiorna non deve trovarsi il comportamento cambiato sotto i piedi."""
    rv = client.get('/api/admin/vincoli-globali', headers=auth(admin_token))
    assert rv.status_code == 200

    preferenza = next(
        (v for v in rv.get_json()['vincoli'] if v['chiave'] == 'preferenza_struttura'),
        None
    )
    assert preferenza is not None
    assert int(preferenza['valore']) == 0


# ---------------------------------------------------------------------------
# Sospendere un'intera struttura dal riempimento automatico
# ---------------------------------------------------------------------------

def test_di_serie_nessuna_struttura_e_sospesa(app):
    from app.services.solver import _strutture_escluse_dal_solver

    with app.test_request_context('/'):
        from flask import g
        g.tenant_slug = 'testorg'
        assert _strutture_escluse_dal_solver() == set()


def test_una_struttura_sospesa_viene_riconosciuta(app):
    """Il solver non deve nemmeno considerare chi vi appartiene."""
    from app.db import execute_write, query_one
    from app.services.solver import _strutture_escluse_dal_solver

    with app.test_request_context('/'):
        from flask import g
        g.tenant_slug = 'testorg'

        sg = query_one("SELECT id FROM sovragruppi LIMIT 1")
        execute_write("UPDATE sovragruppi SET escluso_solver = 1 WHERE id = ?", (sg['id'],))

        assert _strutture_escluse_dal_solver() == {sg['id']}
