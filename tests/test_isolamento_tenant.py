"""
tests/test_isolamento_tenant.py — un tenant non vede niente dell'altro.

L'isolamento non e' una convenzione applicata alle query: ogni tenant e' un
file SQLCipher separato, con una chiave sua, e il tenant di una richiesta si
decide **solo** dal claim firmato nel token. Non esiste una query che
attraversi due tenant, e non c'e' modo di chiederne un altro dall'esterno.

Questi test fissano le tre cose da cui dipende:

- il perimetro dei dati: utenti, vocabolario, configurazione e calendari di
  un tenant non compaiono nell'altro, nemmeno chiedendoli;
- il perimetro dell'autorita': un amministratore di tenant non entra nel
  master, e la sessione di un tenant non si sposta sull'altro;
- il perimetro sul disco: la chiave di un tenant non apre il file dell'altro.

Il secondo tenant si crea passando dalle API del master, cosi' il test copre
anche il provisioning vero.
"""

import json
import os

import pytest

from tests.conftest import _bcrypt_hash, _open_sqlcipher


# Il secondo tenant, con dentro cose riconoscibili: se una di queste compare
# nel primo tenant, il test lo vede.
SLUG_B = 'altraorg'
NOME_B = 'Altra Organizzazione'
PASSWORD_B = 'PasswordDiB2027!'
FASCIA_B = 'fascia_riservatissima_di_b'
TIPOLOGIA_B = 'tipologia_solo_di_b'


@pytest.fixture
def tenant_b(client, master_token, auth, _test_env):
    """
    Un secondo tenant, creato dal master come in produzione.

    Returns:
        dict: slug, credenziali dell'admin e percorso del suo database.
    """
    rv = client.post('/api/master/tenants',
                     json={'slug': SLUG_B, 'nome': NOME_B},
                     headers=auth(master_token))

    # 201 la prima volta, 409 nei test successivi: il file resta.
    assert rv.status_code in (201, 409), rv.get_json()

    percorso = os.path.join(_test_env['tenant_path'].rsplit(os.sep, 1)[0],
                            f'tenant_{SLUG_B}.db')
    chiave = _chiave_tenant(_test_env, SLUG_B)

    # Password nota per l'admin generato, cosi' il login non dipende da quale
    # dei due admin il reset password vada a colpire.
    db = _open_sqlcipher(percorso, chiave)
    admin = db.execute(
        "SELECT username FROM users WHERE role='admin' ORDER BY id LIMIT 1"
    ).fetchone()
    db.execute("UPDATE users SET password_hash=? WHERE username=?",
               (_bcrypt_hash(PASSWORD_B), admin['username']))
    db.commit()

    return {
        'slug': SLUG_B, 'username': admin['username'], 'password': PASSWORD_B,
        'path': percorso, 'chiave': chiave,
    }


def _chiave_tenant(env, slug):
    """La chiave di cifratura di un tenant, dal file delle chiavi."""
    with open(env['keys_path'], encoding='utf-8') as f:
        return json.load(f)[slug]


def _token_di_b(client, tenant_b):
    """Login come amministratore del secondo tenant."""
    rv = client.post('/api/auth/login', json={
        'tenant': tenant_b['slug'],
        'username': tenant_b['username'],
        'password': tenant_b['password'],
    })
    assert rv.status_code == 200, rv.get_json()

    return rv.get_json()['token']


# ---------------------------------------------------------------------------
# Il perimetro dei dati
# ---------------------------------------------------------------------------

# Le persone del primo tenant. L'admin non c'e': quello lo crea il
# provisioning in ogni tenant, e trovarlo in entrambi non dice niente.
PERSONE_DI_A = {'MGR', 'BSC', 'ESC'}


def test_gli_utenti_di_un_tenant_non_compaiono_nell_altro(client, admin_token, auth, tenant_b):
    """Le persone sono del posto: nessuna attraversa il confine."""
    token_b = _token_di_b(client, tenant_b)

    sigle_a = {u['sigla'] for u in
               client.get('/api/admin/users', headers=auth(admin_token)).get_json()['utenti']}
    sigle_b = {u['sigla'] for u in
               client.get('/api/admin/users', headers=auth(token_b)).get_json()['utenti']}

    assert PERSONE_DI_A <= sigle_a, 'il primo tenant deve avere le sue persone'
    assert not (PERSONE_DI_A & sigle_b), 'una persona del primo tenant si vede nel secondo'


def test_il_vocabolario_creato_in_un_tenant_resta_li(client, admin_token, auth, tenant_b):
    """Una fascia nuova nel secondo tenant non compare nel primo."""
    token_b = _token_di_b(client, tenant_b)

    rv = client.post('/api/admin/flag-turno',
                     json={'nome': FASCIA_B, 'orario_inizio': '09:00',
                           'orario_fine': '15:00'},
                     headers=auth(token_b))
    assert rv.status_code in (201, 409), rv.get_json()

    nomi_a = {f['nome'] for f in
              client.get('/api/admin/flag-turno', headers=auth(admin_token)).get_json()['flags']}

    assert FASCIA_B not in nomi_a


def test_le_tipologie_non_attraversano_il_confine(client, admin_token, auth, tenant_b):
    """Vale per ogni parte della configurazione, non solo per le fasce."""
    token_b = _token_di_b(client, tenant_b)

    client.post('/api/admin/tipi-qualitativo', json={'nome': TIPOLOGIA_B},
                headers=auth(token_b))

    nomi_a = {t['nome'] for t in
              client.get('/api/admin/tipi-qualitativo', headers=auth(admin_token))
              .get_json().get('tipi', [])}

    assert TIPOLOGIA_B not in nomi_a


def test_i_calendari_di_un_tenant_non_si_vedono_dall_altro(client, admin_token, auth, tenant_b):
    """
    Gli id dei calendari ripartono da uno in ogni tenant: chiedere un id con
    il token dell'altro deve dare il proprio calendario, o niente — mai
    quello del vicino.
    """
    token_b = _token_di_b(client, tenant_b)

    rv = client.post('/api/admin/calendari', json={'mese': 11, 'anno': 2027},
                     headers=auth(admin_token))
    assert rv.status_code == 201, rv.get_json()
    cal_a = rv.get_json()['id']

    lista_b = client.get('/api/admin/calendari', headers=auth(token_b)).get_json()
    assert (11, 2027) not in {(c['mese'], c['anno']) for c in lista_b['calendari']}

    rv = client.get(f'/api/manager/calendari/{cal_a}/struttura', headers=auth(token_b))
    if rv.status_code == 200:
        cal = rv.get_json()['calendario']
        assert (cal['mese'], cal['anno']) != (11, 2027)
    else:
        assert rv.status_code == 404


def test_il_tenant_chiesto_fuori_dal_token_viene_ignorato(client, admin_token, auth, tenant_b):
    """
    Il tenant si decide solo dal claim firmato: chiederne un altro nella
    query string, nel body o in un header non sposta la sessione.
    """
    token_b = _token_di_b(client, tenant_b)
    client.post('/api/admin/flag-turno',
                json={'nome': FASCIA_B, 'orario_inizio': '09:00', 'orario_fine': '15:00'},
                headers=auth(token_b))

    tentativi = [
        client.get(f'/api/admin/flag-turno?tenant={SLUG_B}', headers=auth(admin_token)),
        client.get('/api/admin/flag-turno',
                   headers={**auth(admin_token), 'X-Tenant': SLUG_B}),
        client.get('/api/admin/flag-turno',
                   headers={**auth(admin_token), 'X-Tenant-Slug': SLUG_B}),
    ]

    for rv in tentativi:
        assert rv.status_code == 200, rv.get_json()
        assert FASCIA_B not in {f['nome'] for f in rv.get_json()['flags']}


def test_le_credenziali_di_un_tenant_non_aprono_l_altro(client, tenant_b):
    """
    Lo stesso nome utente puo' esistere in due tenant: sono due persone
    diverse, e la password dell'una non vale per l'altra.
    """
    from tests.conftest import CREDENZIALI, TENANT_SLUG

    username, password = CREDENZIALI['admin']

    rv = client.post('/api/auth/login', json={
        'tenant': tenant_b['slug'], 'username': username, 'password': password,
    })
    assert rv.status_code == 401

    # E la password dell'admin di B non apre A.
    rv = client.post('/api/auth/login', json={
        'tenant': TENANT_SLUG,
        'username': tenant_b['username'], 'password': tenant_b['password'],
    })
    assert rv.status_code == 401


# ---------------------------------------------------------------------------
# Il perimetro dell'autorita'
# ---------------------------------------------------------------------------

def test_un_amministratore_di_tenant_non_entra_nel_master(client, admin_token, auth):
    """
    L'admin e' il vertice **dentro** il suo tenant. Il registro dei tenant
    sta un livello sopra, e da li' non si vede.
    """
    for percorso in ('/api/master/tenants', '/api/master/config',
                     '/api/master/impersonation-log', '/api/master/templates'):
        rv = client.get(percorso, headers=auth(admin_token))
        assert rv.status_code == 403, f'{percorso} → {rv.status_code}'


def test_nessuna_route_del_tenant_legge_il_registro_dei_tenant():
    """
    Il master DB e' l'unico posto dove i tenant si vedono tutti insieme:
    nessuna route di tenant deve aprirlo. E' una garanzia strutturale, e si
    verifica sul codice.
    """
    import pathlib

    for nome in ('admin.py', 'manager.py', 'basic.py', 'export.py'):
        sorgente = pathlib.Path('app/routes') / nome
        assert 'get_master_db' not in sorgente.read_text(encoding='utf-8'), (
            f'{nome} apre il master DB: da li si vedono tutti i tenant'
        )


def test_il_token_di_impersonation_non_torna_nel_master(client, master_token, auth, tenant_b):
    """
    Il master puo' operare come admin di un tenant, ma quel token vale solo
    li': non riapre le porte del master.
    """
    elenco = client.get('/api/master/tenants', headers=auth(master_token)).get_json()
    tid = next(t['id'] for t in elenco['tenants'] if t['slug'] == SLUG_B)

    rv = client.post(f'/api/master/tenants/{tid}/impersonate',
                     json={'motivo': 'prova di isolamento'},
                     headers=auth(master_token))
    assert rv.status_code == 200, rv.get_json()
    token_imp = rv.get_json()['token']

    assert client.get('/api/master/tenants', headers=auth(token_imp)).status_code == 403
    assert client.get('/api/admin/users', headers=auth(token_imp)).status_code == 200


def test_l_impersonation_lascia_traccia(client, master_token, auth, tenant_b):
    """Non e' un accesso silenzioso: resta nel log e il tenant lo vede."""
    elenco = client.get('/api/master/tenants', headers=auth(master_token)).get_json()
    tid = next(t['id'] for t in elenco['tenants'] if t['slug'] == SLUG_B)

    client.post(f'/api/master/tenants/{tid}/impersonate',
                json={'motivo': 'prova di isolamento'},
                headers=auth(master_token))

    log = client.get('/api/master/impersonation-log', headers=auth(master_token)).get_json()
    assert any(r['tenant_slug'] == SLUG_B for r in log['log'])


# ---------------------------------------------------------------------------
# Il perimetro sul disco
# ---------------------------------------------------------------------------

def test_ogni_tenant_ha_la_sua_chiave(_test_env, tenant_b):
    """Due tenant, due chiavi: non e' una chiave sola per l'installazione."""
    with open(_test_env['keys_path'], encoding='utf-8') as f:
        chiavi = json.load(f)

    assert chiavi[SLUG_B] != chiavi[_test_env['tenant_slug']]
    assert len(chiavi[SLUG_B]) >= 64, 'chiave troppo corta per AES-256'


def test_la_chiave_di_un_tenant_non_apre_il_file_dell_altro(_test_env, tenant_b):
    """
    L'isolamento e' anche sul disco: chi mettesse le mani sul file dell'altro
    tenant, senza la sua chiave, non ne caverebbe niente.
    """
    from sqlcipher3 import dbapi2

    with pytest.raises(dbapi2.DatabaseError):
        sbagliata = _open_sqlcipher(tenant_b['path'], _test_env['tenant_key'])
        sbagliata.execute('SELECT COUNT(*) FROM users').fetchone()


def test_lo_slug_di_un_tenant_non_puo_uscire_dalla_sua_cartella(client, master_token, auth):
    """
    Il percorso del database si costruisce dallo slug: uno slug con dentro un
    percorso aprirebbe file fuori posto. La validazione lo impedisce prima.
    """
    for slug in ('../master', 'a/../../etc/passwd', 'con.spazi', 'ab'):
        rv = client.post('/api/master/tenants',
                         json={'slug': slug, 'nome': 'Tentativo'},
                         headers=auth(master_token))
        assert rv.status_code == 400, f'slug {slug!r} accettato'


# ---------------------------------------------------------------------------
# Il tempo reale
# ---------------------------------------------------------------------------

def test_le_room_websocket_portano_il_tenant():
    """
    Gli id dei calendari si ripetono fra tenant: senza il prefisso, due
    manager di organizzazioni diverse si vedrebbero le modifiche a vicenda.
    """
    from app.services.websocket import _room_name

    assert _room_name('orgA', 7) != _room_name('orgB', 7)
    assert _room_name('orgA', 7).startswith('orgA')


# ---------------------------------------------------------------------------
# Nessuna porta di servizio
# ---------------------------------------------------------------------------

# L'admin che lo schema semina, con la password scritta in init_db.sql e nel
# README. Va bene per l'installazione dimostrativa; in un tenant creato dal
# master sarebbe una porta aperta a chiunque conosca lo slug.
UTENTE_SEED_SCHEMA = 'admin1'


def test_un_tenant_nuovo_non_nasce_con_una_password_nota(client, tenant_b):
    """
    Il provisioning genera una password forte per l'amministratore. Se accanto
    resta l'admin di serie dello schema, quella password non protegge niente:
    per entrare basta conoscere lo slug del tenant, che il menu del login
    mostra a tutti.
    """
    rv = client.post('/api/auth/login', json={
        'tenant': tenant_b['slug'],
        'username': UTENTE_SEED_SCHEMA,
        'password': UTENTE_SEED_SCHEMA,
    })

    assert rv.status_code == 401, (
        'un tenant creato dal master accetta ancora la password di serie '
        'dello schema: chiunque conosca lo slug entra come amministratore'
    )


def test_un_tenant_nuovo_ha_un_solo_amministratore(client, tenant_b, _test_env):
    """
    «Il solo account admin, nessuna persona»: se ne sopravvive un secondo, la
    password generata al provisioning non e' l'unica via d'ingresso.
    """
    db = _open_sqlcipher(tenant_b['path'], tenant_b['chiave'])
    admin = [r['username'] for r in db.execute(
        "SELECT username FROM users WHERE role='admin' AND is_active=1"
    )]

    assert len(admin) == 1, f'amministratori nel tenant nuovo: {admin}'
    # Il nome porta il numero del tenant: admin1 per il primo, admin2 per il
    # secondo. Qui il numero dipende da quanti ne sono stati creati.
    assert admin[0].startswith('admin') and admin[0][len('admin'):].isdigit()


def test_l_ultimo_amministratore_non_si_puo_togliere(client, admin_token, auth):
    """
    Ora che il ruolo si cambia dalla configurazione guidata, l'errore piu'
    facile e' togliersi l'amministrazione da soli: dopo, il tenant non si
    riconfigura piu' da dentro.
    """
    utenti = client.get('/api/admin/users', headers=auth(admin_token)).get_json()['utenti']
    admin = [u for u in utenti if u['role'] == 'admin' and u['is_active']]
    assert len(admin) == 1, 'il tenant di prova deve avere un solo amministratore'

    rv = client.put(f"/api/admin/users/{admin[0]['id']}",
                    json={'role': 'manager'}, headers=auth(admin_token))
    assert rv.status_code == 409, rv.get_json()
    assert 'unico amministratore' in rv.get_json()['errore']

    rv = client.put(f"/api/admin/users/{admin[0]['id']}",
                    json={'is_active': 0}, headers=auth(admin_token))
    assert rv.status_code == 409, rv.get_json()


def test_un_amministratore_si_puo_togliere_se_ce_n_e_un_altro(client, admin_token, auth):
    """Il vincolo protegge l'ultimo, non impedisce di cambiare le persone."""
    utenti = client.get('/api/admin/users', headers=auth(admin_token)).get_json()['utenti']
    admin = next(u for u in utenti if u['role'] == 'admin' and u['is_active'])
    manager = next(u for u in utenti if u['sigla'] == 'MGR')

    rv = client.put(f"/api/admin/users/{manager['id']}",
                    json={'role': 'admin'}, headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    rv = client.put(f"/api/admin/users/{admin['id']}",
                    json={'role': 'manager'}, headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()
