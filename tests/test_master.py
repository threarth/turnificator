"""
tests/test_master.py — smoke test del flusso master multi-tenant.

Coperti:
- Login master admin
- Lista tenant
- Crea nuovo tenant (provisioning DB + chiave + admin seed)
- Login admin del nuovo tenant con password ritornata
- Isolamento: i dati del tenant 'testorg' non sono visibili dal nuovo tenant
"""


def test_master_login(client, master_token):
    """Login master admin → JWT con ruolo master_admin."""
    rv = client.get('/api/auth/me',
                    headers={'Authorization': f'Bearer {master_token}'})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body['ok'] is True
    assert body['user']['role'] == 'master_admin'
    assert body['tenant'] is None


def test_master_lista_tenants(client, master_token, auth):
    """GET /api/master/tenants → almeno il tenant test."""
    rv = client.get('/api/master/tenants', headers=auth(master_token))
    assert rv.status_code == 200
    body = rv.get_json()
    assert body['ok'] is True
    slugs = [t['slug'] for t in body['tenants']]
    assert 'testorg' in slugs


def test_master_crea_tenant_e_login(client, master_token, auth):
    """
    Crea un nuovo tenant via API master, poi verifica:
    - tenant registrato in lista
    - login admin del nuovo tenant funziona con la password ritornata
    - dati del tenant test originale non sono visibili nel nuovo (isolamento)
    """
    # 1. Recupera il template_id registrato dal fixture
    rt = client.get('/api/master/templates', headers=auth(master_token))
    assert rt.status_code == 200, rt.get_json()
    templates = rt.get_json()['templates']
    assert len(templates) >= 1
    template_id = templates[0]['id']

    # 2. Crea tenant da template (schema già pronto)
    rv = client.post('/api/master/tenants',
                     json={'slug': 'altrotenant', 'nome': 'Altro Tenant',
                           'template_id': template_id},
                     headers=auth(master_token))
    assert rv.status_code == 201, rv.get_json()
    body = rv.get_json()
    assert body['ok'] is True
    assert body['tenant']['slug'] == 'altrotenant'
    admin_password = body['admin_password']
    assert len(admin_password) > 0
    # L'amministratore porta il numero del tenant: admin1, admin2, ...
    assert body['admin_username'].startswith('admin')

    # 2. Login admin del nuovo tenant con le credenziali ritornate
    rv = client.post('/api/auth/login', json={
        'tenant':   'altrotenant',
        'username': body['admin_username'],
        'password': admin_password,
    })
    assert rv.status_code == 200, rv.get_json()
    new_admin_token = rv.get_json()['token']

    # 3. Isolamento: il nuovo tenant NON vede gli utenti del tenant originale
    ru = client.get('/api/admin/users', headers=auth(new_admin_token))
    assert ru.status_code == 200
    ub = ru.get_json()
    users = ub.get('utenti') or ub.get('users') or []
    sigle = [u['sigla'] for u in users]
    # Il nuovo tenant ha solo 'ADM' (admin seedato), NON 'MGR/BSC/ESC' del testorg
    assert 'ADM' in sigle
    assert 'MGR' not in sigle
    assert 'BSC' not in sigle


def test_master_crea_tenant_slug_invalido(client, master_token, auth):
    """Slug troppo corto o con caratteri invalidi → 400."""
    rv = client.post('/api/master/tenants',
                     json={'slug': 'AB', 'nome': 'Troppo corto'},
                     headers=auth(master_token))
    assert rv.status_code == 400


def test_master_crea_tenant_slug_duplicato(client, master_token, auth):
    """Slug gia' esistente → 409."""
    rv = client.post('/api/master/tenants',
                     json={'slug': 'testorg', 'nome': 'Duplicato'},
                     headers=auth(master_token))
    assert rv.status_code == 409


def test_master_solo_admin(client, admin_token, auth):
    """Tenant admin (non master) non puo' accedere alle route master → 403."""
    rv = client.get('/api/master/tenants', headers=auth(admin_token))
    assert rv.status_code == 403


def test_master_crea_tenant_da_schema(client, master_token, auth):
    """
    Crea tenant SENZA template_id (fresh init da init_db.sql).
    Verifica login admin con password generata (lock-in del fix:
    init_db.sql forward FK + master.py crea_tenant DELETE+INSERT admin).
    """
    rv = client.post('/api/master/tenants',
                     json={'slug': 'freshtenant', 'nome': 'Fresh Tenant'},
                     headers=auth(master_token))
    assert rv.status_code == 201, rv.get_json()
    body = rv.get_json()
    admin_password = body['admin_password']
    assert admin_password

    # Login con le credenziali generate
    rv = client.post('/api/auth/login', json={
        'tenant':   'freshtenant',
        'username': body['admin_username'],
        'password': admin_password,
    })
    assert rv.status_code == 200, rv.get_json()
