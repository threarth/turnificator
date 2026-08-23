"""
tests/conftest.py — fixture pytest per Turnificator9000 (smoke test).

Setup multi-tenant isolato:
- Crea master DB + 1 tenant DB + 1 template DB in directory temporanea.
- Pre-popola master con tenant 'testorg' + master admin 'master_t' / 'Master2024!'.
- Avvia create_app() puntando alle directory temp via env var.
- Seed tenant con: 1 admin, 1 manager, 1 basic, 1 basic escluso_turni,
  1 sovragruppo, 1 gruppo (flag mattina), 1 turno, 1 preset default.
- Snapshot del tenant DB seedato, ripristinato prima di ogni test
  per garantire isolamento tra test.

Convenzioni credenziali (test only, mai usare in produzione):
  master:    master_t   / Master2024!
  admin:     admin_t    / Admin2024!
  manager:   manager_t  / Manager2024!
  basic:     basic_t    / Basic2024!
  escluso:   escluso_t  / Escluso2024!
"""

import json
import os
import secrets
import shutil
import sys

import bcrypt
import pytest

# Path repo per import diretti senza installare il pacchetto
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

try:
    import sqlcipher3 as _sqlcipher
except ImportError as e:
    raise ImportError(
        "sqlcipher3 non trovato. Installa libsqlcipher-dev e poi: "
        "pip install -r requirements-dev.txt"
    ) from e


# Costanti test
TENANT_SLUG = 'testorg'
TENANT_NOME = 'Test Organization'
TENANT_DB_FILENAME = f'tenant_{TENANT_SLUG}.db'
TEMPLATE_DB_FILENAME = 'template_test.db'
TEMPLATE_KEY_NAME = '_template_test'

CREDENZIALI = {
    'master':  ('master_t',  'Master2024!'),
    'admin':   ('admin_t',   'Admin2024!'),
    'manager': ('manager_t', 'Manager2024!'),
    'basic':   ('basic_t',   'Basic2024!'),
    'escluso': ('escluso_t', 'Escluso2024!'),
}


def _bcrypt_hash(password):
    """Genera hash bcrypt come decoded string (formato uguale a app/auth.py)."""
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt(rounds=4)  # rounds bassi: test veloci
    ).decode('utf-8')


def _open_sqlcipher(path, key):
    """Apre connessione SQLCipher con PRAGMA standard."""
    conn = _sqlcipher.connect(path)
    conn.execute(f"PRAGMA key='{key}'")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = _sqlcipher.Row
    return conn


# ---------------------------------------------------------------------------
# Setup ambiente test (session-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def _test_env(tmp_path_factory):
    """
    Crea un ambiente test isolato:
      - directory temp con master/tenants/templates
      - tenant_keys.json con chiavi generate
      - master DB con tenant 'testorg' + master admin registrati
      - tenant DB e template DB vuoti (init schema fatto da create_app)
      - env var puntate ai path temp

    Yield: dict con path e chiavi (per fixture seed/snapshot).
    """
    base = tmp_path_factory.mktemp('turnificator_test', numbered=False)
    master_path   = str(base / 'master.db')
    tenant_dir    = str(base / 'tenants')
    template_dir  = str(base / 'templates')
    keys_path     = str(base / 'tenant_keys.json')
    os.makedirs(tenant_dir,   exist_ok=True)
    os.makedirs(template_dir, exist_ok=True)

    master_key   = secrets.token_hex(32)
    tenant_key   = secrets.token_hex(32)
    template_key = secrets.token_hex(32)

    # tenant_keys.json
    with open(keys_path, 'w', encoding='utf-8') as f:
        json.dump({
            TENANT_SLUG: tenant_key,
            TEMPLATE_KEY_NAME: template_key,
        }, f)

    # Master DB: schema + seed
    master_schema = os.path.join(_PROJECT_ROOT, 'migrations', 'init_master_db.sql')
    mc = _open_sqlcipher(master_path, master_key)
    with open(master_schema, 'r', encoding='utf-8') as f:
        mc.executescript(f.read())
    # Tenant
    mc.execute(
        "INSERT INTO tenants (slug, nome, db_filename, is_active, visibile_login) "
        "VALUES (?, ?, ?, 1, 1)",
        (TENANT_SLUG, TENANT_NOME, TENANT_DB_FILENAME)
    )
    # Master admin
    master_user, master_pwd = CREDENZIALI['master']
    mc.execute(
        "INSERT INTO master_users (username, password_hash, role, is_active) "
        "VALUES (?, ?, 'master_admin', 1)",
        (master_user, _bcrypt_hash(master_pwd))
    )
    # Template
    mc.execute(
        "INSERT INTO tenant_templates (nome, descrizione, db_filename) "
        "VALUES ('Test', 'Template test', ?)",
        (TEMPLATE_DB_FILENAME,)
    )
    mc.commit()
    mc.close()

    # Applica lo schema tenant ai DB tenant + template (init_db.sql)
    tenant_schema = os.path.join(_PROJECT_ROOT, 'migrations', 'init_db.sql')
    with open(tenant_schema, 'r', encoding='utf-8') as f:
        schema_sql = f.read()

    tenant_path   = os.path.join(tenant_dir,   TENANT_DB_FILENAME)
    template_path = os.path.join(template_dir, TEMPLATE_DB_FILENAME)
    for path, key in [(tenant_path, tenant_key), (template_path, template_key)]:
        c = _open_sqlcipher(path, key)
        c.executescript(schema_sql)
        c.commit()
        c.close()

    # Env var
    env_originali = {}
    nuovi_env = {
        'MASTER_DB_PATH':   master_path,
        'MASTER_DB_KEY':    master_key,
        'TENANT_DB_DIR':    tenant_dir,
        'TEMPLATE_DB_DIR':  template_dir,
        'TENANT_KEYS_PATH': keys_path,
        'JWT_SECRET_KEY':   'test-jwt-secret-' + secrets.token_hex(8),
        'SECRET_KEY':       'test-flask-secret-' + secrets.token_hex(8),
        'FLASK_DEBUG':      '0',
    }
    for k, v in nuovi_env.items():
        env_originali[k] = os.environ.get(k)
        os.environ[k] = v

    yield {
        'master_path':   master_path,
        'master_key':    master_key,
        'tenant_path':   tenant_path,
        'tenant_key':    tenant_key,
        'tenant_slug':   TENANT_SLUG,
        'template_path': template_path,
        'keys_path':     keys_path,
    }

    # Ripristina env (cleanup)
    for k, original in env_originali.items():
        if original is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = original


# ---------------------------------------------------------------------------
# App Flask (session-scoped) — esegue init_db che crea schema su tenant
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def _app_seeded(_test_env):
    """
    Avvia create_app() che inizializza schema + migrazioni su tenant test.
    Successivamente seed dati base sul tenant DB.
    Salva snapshot del file tenant DB per restore tra test.
    """
    # Importa qui (dopo set env var) cosi config legge i valori giusti
    from app import create_app
    app = create_app()
    app.config['TESTING'] = True

    # Seed dati base sul tenant DB direttamente (bypass route)
    _seed_tenant_dati_base(_test_env)

    # Snapshot post-seed: copia file tenant DB
    snapshot_path = _test_env['tenant_path'] + '.snapshot'
    shutil.copy2(_test_env['tenant_path'], snapshot_path)

    yield app, snapshot_path


def _seed_tenant_dati_base(env):
    """
    Inserisce i dati base nel tenant test DB:
    - 4 utenti (admin, manager, basic, escluso_turni)
    - 1 tipo_richiesta lavorativo (sigla 'M', flag mattina)
    - 1 tipo_richiesta assenza   (sigla 'F', flag ferie)
    - 1 preset 'PresetTest' (default)
    - 1 sovragruppo 'TST' → 1 gruppo 'MAT' (flag mattina) → 1 turno 'AMB'
    """
    c = _open_sqlcipher(env['tenant_path'], env['tenant_key'])
    try:
        # Rimuovi l'admin di default seedato da init_db.sql (sigla='ADM')
        c.execute("DELETE FROM users WHERE sigla='ADM'")

        # Utenti
        utenti = [
            (CREDENZIALI['admin'][0],   CREDENZIALI['admin'][1],   'admin',   'ADM', 0),
            (CREDENZIALI['manager'][0], CREDENZIALI['manager'][1], 'manager', 'MGR', 0),
            (CREDENZIALI['basic'][0],   CREDENZIALI['basic'][1],   'basic',   'BSC', 0),
            (CREDENZIALI['escluso'][0], CREDENZIALI['escluso'][1], 'basic',   'ESC', 1),
        ]
        for username, password, role, sigla, escluso in utenti:
            c.execute(
                "INSERT INTO users (username, password_hash, role, sigla, is_active, escluso_turni) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (username, _bcrypt_hash(password), role, sigla, escluso)
            )

        # tipi_richiesta: lo schema seeda gia' M (lavorativo) e CO (assenza/ferie).
        # Aggiorniamo flag_id sui sigle esistenti.
        flag_m = c.execute("SELECT id FROM flag_turno WHERE nome='mattina'").fetchone()['id']
        flag_f = c.execute("SELECT id FROM flag_turno WHERE nome='ferie'").fetchone()['id']
        c.execute("UPDATE tipi_richiesta SET flag_id=? WHERE sigla='M'", (flag_m,))
        c.execute("UPDATE tipi_richiesta SET flag_id=? WHERE sigla='CO'", (flag_f,))

        # Preset + struttura
        cur = c.execute(
            "INSERT INTO struttura_presets (nome, is_default) VALUES ('PresetTest', 1)"
        )
        preset_id = cur.lastrowid

        cur = c.execute(
            "INSERT INTO sovragruppi (preset_id, sigla, nome, ordine) VALUES (?, 'TST', 'Test SG', 1)",
            (preset_id,)
        )
        sg_id = cur.lastrowid

        cur = c.execute(
            "INSERT INTO gruppi (sovragruppo_id, sigla, nome, flag_id, ordine) "
            "VALUES (?, 'MAT', 'Mattina', ?, 1)",
            (sg_id, flag_m)
        )
        gruppo_id = cur.lastrowid

        c.execute(
            "INSERT INTO preset_turni (gruppo_id, sigla, nome, ordine) "
            "VALUES (?, 'AMB', 'Ambulatorio', 1)",
            (gruppo_id,)
        )

        # tenant_slug nel config (necessario per consistenza)
        c.execute(
            "INSERT OR IGNORE INTO config (chiave, valore) VALUES ('tenant_slug', ?)",
            (env['tenant_slug'],)
        )

        c.commit()
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Restore per-test: snapshot tenant DB rispristinato prima di ogni test
# ---------------------------------------------------------------------------

@pytest.fixture
def app(_app_seeded, _test_env):
    """
    App Flask + restore tenant DB allo stato seed prima di ogni test.
    """
    flask_app, snapshot_path = _app_seeded
    # Restore: copia snapshot sopra il tenant DB
    shutil.copy2(snapshot_path, _test_env['tenant_path'])
    return flask_app


@pytest.fixture
def client(app):
    """Test client Flask."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Helper login
# ---------------------------------------------------------------------------

def _login(client, ruolo, slug=TENANT_SLUG):
    """Esegue login tenant e restituisce token JWT."""
    username, password = CREDENZIALI[ruolo]
    rv = client.post('/api/auth/login', json={
        'tenant':   slug,
        'username': username,
        'password': password,
    })
    assert rv.status_code == 200, f"Login {ruolo} fallito: {rv.get_json()}"
    return rv.get_json()['token']


def _login_master(client):
    """Esegue login master e restituisce token."""
    username, password = CREDENZIALI['master']
    rv = client.post('/api/master/auth/login', json={
        'username': username,
        'password': password,
    })
    assert rv.status_code == 200, f"Login master fallito: {rv.get_json()}"
    return rv.get_json()['token']


def _auth(token):
    """Header Authorization per richieste autenticate."""
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def admin_token(client):
    return _login(client, 'admin')


@pytest.fixture
def manager_token(client):
    return _login(client, 'manager')


@pytest.fixture
def basic_token(client):
    return _login(client, 'basic')


@pytest.fixture
def escluso_token(client):
    return _login(client, 'escluso')


@pytest.fixture
def master_token(client):
    return _login_master(client)


@pytest.fixture
def auth():
    """Helper: builder header per token."""
    return _auth
