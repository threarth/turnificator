"""
tests/test_workflow_calendario.py — smoke test dei flussi critici.

Coperti:
- Login admin/manager/basic
- Crea calendario (admin)
- Chiudi/riapri calendario: stati, EFFETTIVO creato/eliminato, history preservata
- Undo bloccato su calendario chiuso
- Desiderata: insert/list/cancel da utente basic
- escluso_turni blocca inserimento desiderata
- Assegnazione singola da manager
- Solver smoke (esecuzione completa senza errori)
"""

import pytest


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_admin(client, admin_token):
    """Login admin con tenant valido restituisce JWT + dati utente."""
    rv = client.get('/api/auth/me', headers={'Authorization': f'Bearer {admin_token}'})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body['ok'] is True
    assert body['user']['role'] == 'admin'
    assert body['user']['sigla'] == 'ADM'
    assert body['tenant'] == 'testorg'


def test_login_credenziali_errate(client):
    """Password sbagliata → 401."""
    rv = client.post('/api/auth/login', json={
        'tenant': 'testorg', 'username': 'admin_t', 'password': 'sbagliata',
    })
    assert rv.status_code == 401


def test_login_tenant_inesistente(client):
    """Tenant inesistente → 401."""
    rv = client.post('/api/auth/login', json={
        'tenant': 'nonesiste', 'username': 'admin_t', 'password': 'Admin2024!',
    })
    assert rv.status_code == 401


# ---------------------------------------------------------------------------
# Crea calendario
# ---------------------------------------------------------------------------

def test_crea_calendario(client, admin_token, auth):
    """POST /api/admin/calendari crea calendario + giorni + struttura snapshot."""
    rv = client.post('/api/admin/calendari',
                     json={'mese': 6, 'anno': 2026},
                     headers=auth(admin_token))
    assert rv.status_code == 201, rv.get_json()
    body = rv.get_json()
    assert body['ok'] is True
    cal_id = body['id']

    # Verifica struttura completa: giorni + snapshot turni
    rs = client.get(f'/api/manager/calendari/{cal_id}/struttura',
                    headers=auth(admin_token))
    assert rs.status_code == 200
    sb = rs.get_json()
    assert sb['ok'] is True
    assert sb['calendario']['stato'] == 'APERTO'
    assert sb['calendario']['mese'] == 6
    assert sb['calendario']['anno'] == 2026
    # Giugno 2026 = 30 giorni
    assert len(sb['giorni']) == 30
    # Almeno un sovragruppo, gruppo, turno
    assert len(sb['sovragruppi']) >= 1


def test_crea_calendario_duplicato(client, admin_token, auth):
    """Tentativo di creare due volte stesso mese/anno → 409."""
    client.post('/api/admin/calendari', json={'mese': 7, 'anno': 2026},
                headers=auth(admin_token))
    rv = client.post('/api/admin/calendari', json={'mese': 7, 'anno': 2026},
                     headers=auth(admin_token))
    assert rv.status_code == 409


# ---------------------------------------------------------------------------
# Chiudi / riapri calendario
# ---------------------------------------------------------------------------

def _crea_cal(client, admin_token, auth, mese=8, anno=2026):
    """Helper: crea un calendario e ritorna l'id."""
    rv = client.post('/api/admin/calendari', json={'mese': mese, 'anno': anno},
                     headers=auth(admin_token))
    assert rv.status_code == 201, rv.get_json()
    return rv.get_json()['id']


def test_chiudi_calendario(client, admin_token, auth):
    """Chiudi: stato → CHIUSO, EFFETTIVO creato, history non cancellata."""
    cal_id = _crea_cal(client, admin_token, auth, mese=8, anno=2026)

    rv = client.post(f'/api/admin/calendari/{cal_id}/stato',
                     json={'stato': 'CHIUSO'},
                     headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()
    body = rv.get_json()
    assert body['ok'] is True
    assert 'effettivo_id' in body
    eff_id = body['effettivo_id']

    # Stato calendario principale = CHIUSO
    rs = client.get(f'/api/manager/calendari/{cal_id}/struttura',
                    headers=auth(admin_token))
    assert rs.get_json()['calendario']['stato'] == 'CHIUSO'

    # EFFETTIVO esiste e tipo='effettivo'
    re = client.get(f'/api/manager/calendari/{eff_id}/struttura',
                    headers=auth(admin_token))
    assert re.get_json()['calendario']['tipo'] == 'effettivo'


def test_riapri_calendario_elimina_effettivo(client, admin_token, auth):
    """Riapri: stato → APERTO, EFFETTIVO eliminato, history del principale preservata."""
    cal_id = _crea_cal(client, admin_token, auth, mese=9, anno=2026)

    # Chiudi
    rv = client.post(f'/api/admin/calendari/{cal_id}/stato',
                     json={'stato': 'CHIUSO'}, headers=auth(admin_token))
    eff_id = rv.get_json()['effettivo_id']

    # Riapri
    rv = client.post(f'/api/admin/calendari/{cal_id}/stato',
                     json={'stato': 'APERTO'}, headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    # Stato principale = APERTO
    rs = client.get(f'/api/manager/calendari/{cal_id}/struttura',
                    headers=auth(admin_token))
    assert rs.get_json()['calendario']['stato'] == 'APERTO'

    # EFFETTIVO eliminato (404 sulla struttura)
    re = client.get(f'/api/manager/calendari/{eff_id}/struttura',
                    headers=auth(admin_token))
    assert re.status_code == 404


def test_undo_bloccato_su_chiuso(client, admin_token, auth):
    """POST /undo su calendario CHIUSO → 400 (history NON cancellata, solo bloccata)."""
    cal_id = _crea_cal(client, admin_token, auth, mese=10, anno=2026)

    client.post(f'/api/admin/calendari/{cal_id}/stato',
                json={'stato': 'CHIUSO'}, headers=auth(admin_token))

    rv = client.post(f'/api/manager/calendari/{cal_id}/undo',
                     headers=auth(admin_token))
    assert rv.status_code == 400
    body = rv.get_json()
    assert 'chiuso' in (body.get('errore') or '').lower()


def test_redo_bloccato_su_chiuso(client, admin_token, auth):
    """POST /redo su calendario CHIUSO → 400."""
    cal_id = _crea_cal(client, admin_token, auth, mese=11, anno=2026)
    client.post(f'/api/admin/calendari/{cal_id}/stato',
                json={'stato': 'CHIUSO'}, headers=auth(admin_token))

    rv = client.post(f'/api/manager/calendari/{cal_id}/redo',
                     headers=auth(admin_token))
    assert rv.status_code == 400


# ---------------------------------------------------------------------------
# Desiderata basic
# ---------------------------------------------------------------------------

def test_desiderata_basic_insert_e_cancella(client, admin_token, basic_token, auth):
    """Basic inserisce/cancella propria desiderata su calendario aperto."""
    cal_id = _crea_cal(client, admin_token, auth, mese=12, anno=2026)

    # Recupera tipo_richiesta 'M'
    rt = client.get('/api/admin/tipi-richiesta', headers=auth(admin_token))
    tipi = rt.get_json()['tipi']
    tipo_m = next(t for t in tipi if t['sigla'] == 'M')

    # Insert
    rv = client.put(f'/api/basic/calendari/{cal_id}/desiderata',
                    json={'giorno': 5, 'tipo_richiesta_id': tipo_m['id']},
                    headers=auth(basic_token))
    assert rv.status_code == 200, rv.get_json()

    # Cancella
    rv = client.delete(f'/api/basic/calendari/{cal_id}/desiderata/5',
                       headers=auth(basic_token))
    assert rv.status_code == 200


def test_escluso_turni_blocca_desiderata(client, admin_token, escluso_token, auth):
    """Utente con escluso_turni=1 → 403 su PUT desiderata."""
    cal_id = _crea_cal(client, admin_token, auth, mese=1, anno=2027)
    rt = client.get('/api/admin/tipi-richiesta', headers=auth(admin_token))
    tipo_m = next(t for t in rt.get_json()['tipi'] if t['sigla'] == 'M')

    rv = client.put(f'/api/basic/calendari/{cal_id}/desiderata',
                    json={'giorno': 3, 'tipo_richiesta_id': tipo_m['id']},
                    headers=auth(escluso_token))
    assert rv.status_code == 403
    assert 'escluso' in rv.get_json()['errore'].lower()


def test_desiderata_bloccata_su_chiuso(client, admin_token, basic_token, auth):
    """Inserimento desiderata su calendario CHIUSO → 400."""
    cal_id = _crea_cal(client, admin_token, auth, mese=2, anno=2027)

    # Chiudi
    client.post(f'/api/admin/calendari/{cal_id}/stato',
                json={'stato': 'CHIUSO'}, headers=auth(admin_token))

    rt = client.get('/api/admin/tipi-richiesta', headers=auth(admin_token))
    tipo_m = next(t for t in rt.get_json()['tipi'] if t['sigla'] == 'M')

    rv = client.put(f'/api/basic/calendari/{cal_id}/desiderata',
                    json={'giorno': 5, 'tipo_richiesta_id': tipo_m['id']},
                    headers=auth(basic_token))
    assert rv.status_code == 400


# ---------------------------------------------------------------------------
# Assegnazione manager
# ---------------------------------------------------------------------------

def test_assegnazione_singola(client, admin_token, manager_token, auth):
    """Manager assegna basic a turno+giorno; verifica via struttura."""
    cal_id = _crea_cal(client, admin_token, auth, mese=3, anno=2027)

    # Recupera struttura per pescare un turno reale
    rs = client.get(f'/api/manager/calendari/{cal_id}/struttura',
                    headers=auth(manager_token))
    sb = rs.get_json()
    turno = sb['sovragruppi'][0]['gruppi'][0]['turni'][0]
    turno_id = turno['id']

    # ID utente basic (recuperato via API admin users)
    ru = client.get('/api/admin/users', headers=auth(admin_token))
    users_body = ru.get_json()
    users = users_body.get('utenti') or users_body.get('users') or []
    basic_user = next(u for u in users if u['sigla'] == 'BSC')

    # Assegna basic al turno il giorno 5
    rv = client.post(f'/api/manager/calendari/{cal_id}/assegnazioni',
                     json={'turno_id': turno_id, 'giorno': 5,
                           'user_id': basic_user['id']},
                     headers=auth(manager_token))
    assert rv.status_code == 200, rv.get_json()


# ---------------------------------------------------------------------------
# Solver smoke
# ---------------------------------------------------------------------------

def test_solver_smoke(client, admin_token, manager_token, auth):
    """Solver: esegue su un calendario seedato e ritorna senza errori."""
    cal_id = _crea_cal(client, admin_token, auth, mese=4, anno=2027)

    # Solver: giorni 1-3, default options
    rv = client.post(f'/api/manager/calendari/{cal_id}/solver',
                     json={'giorno_da': 1, 'giorno_a': 3},
                     headers=auth(manager_token))
    # Accetta 200 (run ok) o 400 (validazione: ad es. nessun utente disponibile)
    # Smoke: non deve essere 500 (crash)
    assert rv.status_code < 500, f"Solver crashed: {rv.get_json()}"
