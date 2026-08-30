"""
tests/test_etichetta_struttura.py — la parola con cui il tenant chiama le sue
strutture.

"Sovragruppo" e' il termine interno del modello. L'utente sceglie il proprio
— reparto, ambulatorio, presidio — nella procedura guidata, e la scelta
finisce in `config`. La pagina manager non puo' leggere `config`, riservata
all'admin, quindi la parola le arriva insieme alla struttura del calendario.
"""

def _crea_calendario(client, token, auth, mese=7, anno=2026):
    """Crea un calendario e ne restituisce l'id."""
    rv = client.post('/api/admin/calendari', json={'mese': mese, 'anno': anno},
                     headers=auth(token))
    assert rv.status_code == 201, rv.get_json()

    return rv.get_json()['id']


def _etichetta_dalla_struttura(client, token, auth, cal_id):
    """Legge l'etichetta dalla risposta che riceve la pagina manager."""
    rv = client.get(f'/api/manager/calendari/{cal_id}/struttura', headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    return rv.get_json()['etichetta_struttura']


def test_senza_scelta_resta_il_termine_interno(client, admin_token, auth):
    """Finche' nessuno sceglie, singolare e plurale sono quelli di serie."""
    cal_id = _crea_calendario(client, admin_token, auth)

    assert _etichetta_dalla_struttura(client, admin_token, auth, cal_id) == {
        'singolare': 'Sovragruppo', 'plurale': 'Sovragruppi',
    }


def test_la_parola_scelta_arriva_al_manager(client, admin_token, auth):
    """La scelta salvata in config raggiunge la pagina manager."""
    cal_id = _crea_calendario(client, admin_token, auth)

    rv = client.put('/api/admin/config',
                    json={'etichetta_struttura': 'Reparto', 'etichetta_strutture': 'Reparti'},
                    headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    assert _etichetta_dalla_struttura(client, admin_token, auth, cal_id) == {
        'singolare': 'Reparto', 'plurale': 'Reparti',
    }


def test_senza_plurale_si_ripiega_sul_singolare(client, admin_token, auth):
    """Meglio ripetere il singolare che mostrare il termine interno."""
    cal_id = _crea_calendario(client, admin_token, auth)

    rv = client.put('/api/admin/config', json={'etichetta_struttura': 'Presidio'},
                    headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    assert _etichetta_dalla_struttura(client, admin_token, auth, cal_id) == {
        'singolare': 'Presidio', 'plurale': 'Presidio',
    }
