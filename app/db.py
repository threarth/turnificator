"""
app/db.py — gestione connessione ai database SQLCipher (multi-tenant).

Architettura:
- Master DB: registro tenant, master admin, template, config globale
- Tenant DB: un file SQLCipher per organizzazione, schema identico
- Template DB: file SQLCipher con config di partenza per nuovi tenant

Fornisce:
- get_db(): connessione al DB del tenant corrente (risolto da g.tenant_slug)
- get_master_db(): connessione al master DB
- Helper per query di lettura e scrittura (invariati rispetto a single-tenant)
- Inizializzazione schema per master e tenant DB

Requisiti di sistema per SQLCipher:
    Ubuntu/Debian: sudo apt-get install libsqlcipher-dev
    pip:           pip install sqlcipher3
"""

import json
import os
import time
from flask import g, current_app

try:
    import sqlcipher3 as sqlite3_cipher
except ImportError:
    raise ImportError(
        "sqlcipher3 non trovato. Installa libsqlcipher-dev e poi: pip install sqlcipher3"
    )


# ---------------------------------------------------------------------------
# Connessione generica
# ---------------------------------------------------------------------------

def _open_db(db_path, db_key):
    """
    Apre un database SQLCipher e applica le configurazioni standard.

    Args:
        db_path (str): percorso del file .db.
        db_key (str): chiave di cifratura AES-256.

    Returns:
        sqlite3_cipher.Connection: connessione pronta all'uso.

    Raises:
        sqlcipher3.DatabaseError: se la chiave e' errata o il file e' corrotto.
    """
    conn = sqlite3_cipher.connect(db_path)
    conn.execute(f"PRAGMA key='{db_key}'")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3_cipher.Row
    return conn


# ---------------------------------------------------------------------------
# Connessione Master DB
# ---------------------------------------------------------------------------

def get_master_db():
    """
    Restituisce la connessione al master database per la richiesta corrente.

    Il master DB contiene il registro tenant, gli utenti master admin,
    i template e la configurazione globale del sistema multi-tenant.

    Returns:
        sqlite3_cipher.Connection: connessione al master DB.
    """
    if 'master_db' not in g:
        g.master_db = _open_db(
            current_app.config['MASTER_DB_PATH'],
            current_app.config['MASTER_DB_KEY']
        )
    return g.master_db


# ---------------------------------------------------------------------------
# Connessione Tenant DB
# ---------------------------------------------------------------------------

_tenant_keys_cache = {}


def _get_tenant_key(slug):
    """
    Legge la chiave di cifratura del tenant dal file tenant_keys.json.

    Le chiavi vengono cachate in memoria per evitare letture ripetute
    del file durante la stessa istanza del processo.

    Args:
        slug (str): slug del tenant.

    Returns:
        str: chiave di cifratura AES-256 del tenant.

    Raises:
        RuntimeError: se la chiave non e' trovata per lo slug dato.
        FileNotFoundError: se il file tenant_keys.json non esiste.
    """
    if slug not in _tenant_keys_cache:
        keys_path = current_app.config['TENANT_KEYS_PATH']
        with open(keys_path, 'r', encoding='utf-8') as f:
            keys = json.load(f)
        _tenant_keys_cache.update(keys)

    if slug not in _tenant_keys_cache:
        raise RuntimeError(
            f"Chiave di cifratura non trovata per tenant '{slug}'. "
            f"Verificare il file {current_app.config['TENANT_KEYS_PATH']}."
        )
    return _tenant_keys_cache[slug]


def _open_tenant_db(slug):
    """
    Apre il database SQLCipher del tenant specificato.

    Il file DB viene cercato nella directory TENANT_DB_DIR con il nome
    tenant_<slug>.db. La chiave viene letta da tenant_keys.json.

    Args:
        slug (str): slug del tenant.

    Returns:
        sqlite3_cipher.Connection: connessione al DB del tenant.

    Raises:
        RuntimeError: se lo slug e' vuoto o la chiave non e' trovata.
        FileNotFoundError: se il file DB del tenant non esiste.
    """
    db_path = os.path.join(
        current_app.config['TENANT_DB_DIR'],
        f"tenant_{slug}.db"
    )
    db_key = _get_tenant_key(slug)
    return _open_db(db_path, db_key)


def get_db():
    """
    Restituisce la connessione al database del tenant corrente.

    Il tenant viene identificato dal valore g.tenant_slug, impostato
    dal middleware _resolve_tenant in __init__.py a partire dal claim
    JWT 'tenant'.

    Returns:
        sqlite3_cipher.Connection: connessione al DB del tenant corrente.

    Raises:
        RuntimeError: se g.tenant_slug non e' impostato (nessun contesto tenant).
    """
    if 'db' not in g:
        slug = g.get('tenant_slug')
        if not slug:
            raise RuntimeError(
                "Nessun contesto tenant per questa richiesta. "
                "Verificare che il JWT contenga il claim 'tenant'."
            )
        g.db = _open_tenant_db(slug)
    return g.db


def close_db(e=None):
    """
    Chiude le connessioni al database al termine della richiesta HTTP.

    Chiude sia la connessione tenant che quella master, se aperte.
    Viene registrata come teardown_appcontext in create_app().

    Args:
        e: eventuale eccezione (ignorata, richiesta da Flask).
    """
    for key in ('db', 'master_db'):
        db = g.pop(key, None)
        if db is not None:
            db.close()


# ---------------------------------------------------------------------------
# Helper query (invariati — operano sul tenant DB via get_db())
# ---------------------------------------------------------------------------

def query_one(sql, params=()):
    """
    Esegue una query SELECT e restituisce la prima riga risultante.

    Args:
        sql (str): istruzione SQL con placeholder '?'.
        params (tuple): parametri da legare ai placeholder.

    Returns:
        dict | None: riga come dizionario, o None se nessun risultato.
    """
    db = get_db()
    row = db.execute(sql, params).fetchone()
    return dict(row) if row else None


def query_all(sql, params=()):
    """
    Esegue una query SELECT e restituisce tutte le righe risultanti.

    Args:
        sql (str): istruzione SQL con placeholder '?'.
        params (tuple): parametri da legare ai placeholder.

    Returns:
        list[dict]: lista di righe come dizionari (lista vuota se nessun risultato).
    """
    db = get_db()
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def execute_write(sql, params=(), max_retries=5, base_wait=0.1):
    """
    Esegue una query di scrittura (INSERT / UPDATE / DELETE) con retry
    automatico in caso di 'database is locked'.

    Args:
        sql (str): istruzione SQL con placeholder '?'.
        params (tuple): parametri da legare ai placeholder.
        max_retries (int): numero massimo di tentativi (default 5).
        base_wait (float): attesa base in secondi tra i tentativi (default 0.1).

    Returns:
        sqlite3_cipher.Cursor: cursore dopo l'esecuzione riuscita.

    Raises:
        sqlcipher3.OperationalError: se dopo max_retries il DB e' ancora locked.
        sqlcipher3.Error: per qualsiasi altro errore SQL.
    """
    db = get_db()
    last_error = None

    for attempt in range(max_retries):
        try:
            cursor = db.execute(sql, params)
            db.commit()
            return cursor
        except sqlite3_cipher.OperationalError as e:
            last_error = e
            if 'database is locked' in str(e) and attempt < max_retries - 1:
                wait = base_wait * (attempt + 1)
                time.sleep(wait)
            else:
                raise

    raise last_error


def execute_many(sql, params_list, max_retries=5, base_wait=0.1):
    """
    Esegue una query di scrittura su piu' righe in una singola transazione,
    con retry automatico in caso di database locked.

    Args:
        sql (str): istruzione SQL con placeholder '?'.
        params_list (list[tuple]): lista di tuple di parametri.
        max_retries (int): numero massimo di tentativi (default 5).
        base_wait (float): attesa base in secondi (default 0.1).

    Returns:
        sqlite3_cipher.Cursor: cursore dopo l'esecuzione riuscita.

    Raises:
        sqlcipher3.OperationalError: se dopo max_retries il DB e' ancora locked.
    """
    db = get_db()
    last_error = None

    for attempt in range(max_retries):
        try:
            cursor = db.executemany(sql, params_list)
            db.commit()
            return cursor
        except sqlite3_cipher.OperationalError as e:
            last_error = e
            if 'database is locked' in str(e) and attempt < max_retries - 1:
                time.sleep(base_wait * (attempt + 1))
            else:
                raise

    raise last_error


# ---------------------------------------------------------------------------
# Inizializzazione schema
# ---------------------------------------------------------------------------

def _run_schema(db, schema_path):
    """
    Esegue un file SQL di schema su una connessione DB aperta.

    Args:
        db: connessione SQLCipher aperta.
        schema_path (str): percorso del file .sql.
    """
    with open(schema_path, 'r', encoding='utf-8') as f:
        db.executescript(f.read())
    db.commit()


def init_master_db(app):
    """
    Inizializza il master database (registro tenant, master admin, ecc.).

    Idempotente: puo' essere chiamata piu' volte senza duplicare i dati.

    Args:
        app (Flask): istanza dell'applicazione Flask.
    """
    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'migrations', 'init_master_db.sql'
    )

    with app.app_context():
        db = get_master_db()
        _run_schema(db, schema_path)


def init_tenant_db(app, slug):
    """
    Inizializza il database di un singolo tenant.

    Esegue lo schema init_db.sql e le migrazioni incrementali.
    Idempotente.

    Args:
        app (Flask): istanza dell'applicazione Flask.
        slug (str): slug del tenant da inizializzare.
    """
    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'migrations', 'init_db.sql'
    )

    with app.app_context():
        g.tenant_slug = slug
        db = get_db()

        _run_schema(db, schema_path)

        # Migrazioni incrementali
        _migrate_posti_fissi_manager_id(db)
        _migrate_posti_fissi_cascade(db)
        _migrate_calendari_solver_fields(db)

        # Chiudi e pulisci per non interferire con altre init
        db.close()
        g.pop('db', None)


def init_all_tenant_dbs(app):
    """
    Inizializza i database di tutti i tenant attivi registrati nel master DB.

    Legge la lista tenant dal master DB e esegue init_tenant_db per ciascuno.

    Args:
        app (Flask): istanza dell'applicazione Flask.
    """
    with app.app_context():
        master = get_master_db()
        tenants = master.execute(
            "SELECT slug FROM tenants WHERE is_active = 1"
        ).fetchall()

        for row in tenants:
            try:
                init_tenant_db(app, row['slug'])
            except Exception as e:
                app.logger.error(
                    f"Errore inizializzazione tenant '{row['slug']}': {e}"
                )


def init_db(app):
    """
    Inizializza tutti i database del sistema multi-tenant.

    1. Inizializza il master DB (schema + seed)
    2. Inizializza tutti i tenant DB attivi (schema + migrazioni)

    Questa funzione sostituisce la vecchia init_db single-tenant.

    Args:
        app (Flask): istanza dell'applicazione Flask.
    """
    init_master_db(app)
    init_all_tenant_dbs(app)


# ---------------------------------------------------------------------------
# Migrazioni incrementali tenant (invariate)
# ---------------------------------------------------------------------------

def _migrate_posti_fissi_manager_id(db):
    """Aggiunge manager_id a posti_fissi se mancante, ricrea con nuovo UNIQUE."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(posti_fissi)").fetchall()]
    if 'manager_id' in cols:
        return

    db.executescript("""
        CREATE TABLE IF NOT EXISTS _pfu_backup AS SELECT * FROM posti_fissi_utenti;
        DROP TABLE IF EXISTS posti_fissi_utenti;
        ALTER TABLE posti_fissi RENAME TO _posti_fissi_old;

        CREATE TABLE posti_fissi (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            preset_id        INTEGER NOT NULL REFERENCES struttura_presets(id) ON DELETE CASCADE,
            manager_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            nome             TEXT    NOT NULL DEFAULT '',
            preset_turno_id  INTEGER NOT NULL REFERENCES preset_turni(id) ON DELETE CASCADE,
            giorno_settimana INTEGER NOT NULL CHECK(giorno_settimana BETWEEN 0 AND 6),
            is_active        INTEGER NOT NULL DEFAULT 1,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
            created_by       INTEGER REFERENCES users(id),
            UNIQUE(preset_id, preset_turno_id, giorno_settimana, manager_id)
        );

        INSERT INTO posti_fissi (id, preset_id, manager_id, nome, preset_turno_id,
                                  giorno_settimana, is_active, created_at, created_by)
        SELECT id, preset_id, created_by, nome, preset_turno_id,
               giorno_settimana, is_active, created_at, created_by
        FROM _posti_fissi_old;

        DROP TABLE _posti_fissi_old;

        CREATE TABLE posti_fissi_utenti (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            posto_fisso_id INTEGER NOT NULL REFERENCES posti_fissi(id) ON DELETE CASCADE,
            user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            ordine         INTEGER NOT NULL DEFAULT 0,
            UNIQUE(posto_fisso_id, user_id)
        );

        INSERT INTO posti_fissi_utenti SELECT * FROM _pfu_backup;
        DROP TABLE _pfu_backup;
    """)
    db.commit()


def _migrate_posti_fissi_cascade(db):
    """Ricrea posti_fissi_utenti per pulire trigger FK corrotti dopo RENAME."""
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='posti_fissi_utenti'"
    ).fetchone()
    if not row or not row[0]:
        return
    done = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='_pf_cascade_done'"
    ).fetchone()
    if done:
        return

    db.executescript("""
        CREATE TABLE IF NOT EXISTS _pfu_backup AS SELECT * FROM posti_fissi_utenti;
        DROP TABLE IF EXISTS posti_fissi_utenti;
        ALTER TABLE posti_fissi RENAME TO _posti_fissi_old2;

        CREATE TABLE posti_fissi (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            preset_id        INTEGER NOT NULL REFERENCES struttura_presets(id) ON DELETE CASCADE,
            manager_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            nome             TEXT    NOT NULL DEFAULT '',
            preset_turno_id  INTEGER NOT NULL REFERENCES preset_turni(id) ON DELETE CASCADE,
            giorno_settimana INTEGER NOT NULL CHECK(giorno_settimana BETWEEN 0 AND 6),
            is_active        INTEGER NOT NULL DEFAULT 1,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
            created_by       INTEGER REFERENCES users(id),
            UNIQUE(preset_id, preset_turno_id, giorno_settimana, manager_id)
        );

        INSERT INTO posti_fissi SELECT * FROM _posti_fissi_old2;
        DROP TABLE _posti_fissi_old2;

        CREATE TABLE posti_fissi_utenti (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            posto_fisso_id INTEGER NOT NULL REFERENCES posti_fissi(id) ON DELETE CASCADE,
            user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            ordine         INTEGER NOT NULL DEFAULT 0,
            UNIQUE(posto_fisso_id, user_id)
        );

        INSERT INTO posti_fissi_utenti SELECT * FROM _pfu_backup;
        DROP TABLE _pfu_backup;

        CREATE TABLE _pf_cascade_done (x INTEGER);
    """)
    db.commit()


def _migrate_calendari_solver_fields(db):
    """Aggiunge esclusioni_manuali e celle_bloccate a calendari se mancanti."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(calendari)").fetchall()]
    if 'esclusioni_manuali' not in cols:
        db.execute(
            "ALTER TABLE calendari ADD COLUMN esclusioni_manuali TEXT NOT NULL DEFAULT '[]'"
        )
        db.commit()
    if 'celle_bloccate' not in cols:
        db.execute(
            "ALTER TABLE calendari ADD COLUMN celle_bloccate TEXT NOT NULL DEFAULT '[]'"
        )
        db.commit()
