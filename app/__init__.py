"""
app/__init__.py — factory dell'applicazione Flask (Turnificator9000).

Crea e configura l'istanza Flask, registra le estensioni (JWT),
i blueprint delle route, il middleware tenant e il teardown del database.

Architettura multi-tenant:
- Il middleware _resolve_tenant estrae il claim 'tenant' dal JWT
  e imposta g.tenant_slug prima di ogni richiesta.
- get_db() usa g.tenant_slug per aprire il DB del tenant corretto.
- Le migrazioni girano su tutti i tenant DB attivi al boot.
"""

import logging
import os
from datetime import datetime, timezone, timedelta

from flask import Flask, g, jsonify
from flask_jwt_extended import (
    JWTManager, get_jwt, get_jwt_identity,
    create_access_token, verify_jwt_in_request
)
from flask_socketio import SocketIO

from app.config import Config
from app.db import close_db, init_db, get_master_db
from app.services.fasce_orarie import (
    DURATA_TURNO_TIPO_DEFAULT_MINUTI, PAUSA_DEFAULT_MINUTI, ricalcola_tutte
)

log = logging.getLogger(__name__)

socketio = SocketIO()

# Concetti root delle fasce orarie: (nome, descrizione, durata netta, pausa).
# Solo turno_tipo porta una durata, perche' non classifica turni ma fa da
# unita' di misura del peso. Gli altri concetti non hanno orari propri: li
# portano le fasce figlie.
CONCETTI_ROOT = [
    ('turno_tipo',  'Turno tipo — unita di misura del peso',
     DURATA_TURNO_TIPO_DEFAULT_MINUTI, PAUSA_DEFAULT_MINUTI),
    ('diurno',      'Turno diurno generico', None, PAUSA_DEFAULT_MINUTI),
    ('notturno',    'Turno notturno',        None, PAUSA_DEFAULT_MINUTI),
    ('guardia_24h', 'Guardia 24 ore',        None, 0),
]

# Fasce orarie default: (nome, concetto padre, descrizione, inizio, fine, pausa).
FASCE_DEFAULT = [
    ('mattina',    'diurno',      'Fascia mattina',    '08:00', '14:20', PAUSA_DEFAULT_MINUTI),
    ('pomeriggio', 'diurno',      'Fascia pomeriggio', '14:00', '20:20', PAUSA_DEFAULT_MINUTI),
    ('lunga',      'diurno',      'Fascia lunga',      '08:00', '20:40', PAUSA_DEFAULT_MINUTI),
    ('notte',      'notturno',    'Fascia notte',      '20:00', '08:40', PAUSA_DEFAULT_MINUTI),
    ('guardia',    'guardia_24h', 'Fascia guardia',    '00:00', '24:00', 0),
]

# Gruppi agganciati a un concetto root vanno spostati sulla fascia
# corrispondente. Per 'diurno' non c'e' una risposta univoca fra mattina,
# pomeriggio e lunga, quindi quei gruppi si segnalano soltanto.
MIGRAZIONE_ROOT_SU_FASCIA = {
    'notturno': 'notte',
    'guardia_24h': 'guardia',
}

# Flag assenza default: (nome, descrizione).
FLAG_ASSENZA = [
    ('ferie',    'Ferie'),
    ('agg',      'Aggiornamento'),
    ('malattia', 'Malattia'),
    ('riposo',   'Riposo'),
    ('permesso', 'Permesso'),
    ('legge',    'Legge'),
]


def create_app(config_class=Config):
    """
    Factory function che crea e restituisce l'istanza Flask configurata.
    """
    app = Flask(
        __name__,
        static_folder='../static',
        static_url_path='/static'
    )

    app.config.from_object(config_class)
    jwt = JWTManager(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode='threading')
    app.teardown_appcontext(close_db)

    # -------------------------------------------------------------------
    # JWT error handlers: restituiscono 401 invece di 500
    # -------------------------------------------------------------------
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({'ok': False, 'errore': 'Token scaduto. Effettua nuovamente il login.'}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return jsonify({'ok': False, 'errore': 'Token non valido.'}), 401

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return jsonify({'ok': False, 'errore': 'Autenticazione richiesta.'}), 401

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        return jsonify({'ok': False, 'errore': 'Token revocato. Effettua nuovamente il login.'}), 401

    # -------------------------------------------------------------------
    # Error handler: CalendarioStateError -> JSON con status appropriato
    # -------------------------------------------------------------------
    from app.services.calendario_state import CalendarioStateError

    @app.errorhandler(CalendarioStateError)
    def _calendario_state_error(e):
        return jsonify({'ok': False, 'errore': e.errore}), e.status

    # -------------------------------------------------------------------
    # Middleware: risolve il tenant dal JWT per ogni richiesta
    # -------------------------------------------------------------------
    @app.before_request
    def _resolve_tenant():
        """
        Estrae il claim 'tenant' dal JWT e imposta g.tenant_slug.

        Questo permette a get_db() di aprire automaticamente il DB
        del tenant corretto per tutta la durata della richiesta.
        Per richieste senza JWT (login, endpoint pubblici) g.tenant_slug
        resta non impostato — sara' la route a impostarlo se necessario.
        """
        try:
            verify_jwt_in_request(optional=True)
            claims = get_jwt()
            if claims and claims.get('tenant'):
                g.tenant_slug = claims['tenant']
        except Exception:
            pass

    # -------------------------------------------------------------------
    # Sliding session: rinnova il token se e' oltre meta' della sua vita
    # -------------------------------------------------------------------
    @app.after_request
    def _refresh_expiring_jwt(response):
        try:
            verify_jwt_in_request(optional=True)
            claims = get_jwt()
            if not claims:
                return response
            exp = datetime.fromtimestamp(claims['exp'], tz=timezone.utc)
            now = datetime.now(timezone.utc)
            ttl = timedelta(seconds=app.config['JWT_ACCESS_TOKEN_EXPIRES'])
            # Rinnova se rimane meno della meta' del TTL
            if exp - now < ttl / 2:
                # Preserva i claim originali (tenant, role) nel token rinnovato
                new_token = create_access_token(
                    identity=get_jwt_identity(),
                    additional_claims={
                        k: v for k, v in claims.items()
                        if k in ('tenant', 'role', 'impersonated_by')
                    }
                )
                response.headers['X-New-Token'] = new_token
        except Exception:
            pass
        return response

    # -------------------------------------------------------------------
    # Registrazione blueprint
    # -------------------------------------------------------------------
    from app.routes.auth    import bp as auth_bp
    from app.routes.admin   import bp as admin_bp
    from app.routes.manager import bp as manager_bp
    from app.routes.basic   import bp as basic_bp
    from app.routes.export  import bp as export_bp
    from app.routes.master  import bp as master_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(manager_bp)
    app.register_blueprint(basic_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(master_bp)

    # -------------------------------------------------------------------
    # Route index: serve il frontend SPA
    # -------------------------------------------------------------------
    from flask import send_from_directory
    from werkzeug.utils import safe_join

    # Documento servito quando il percorso non corrisponde a un file del build
    DOCUMENTO_SPA = 'index.html'

    @app.route('/')
    @app.route('/<path:path>')
    def index(path=''):
        """
        Serve il frontend SPA.

        Il build SvelteKit referenzia i propri asset con percorsi assoluti
        alla radice (/_app/..., /favicon.ico), che non passano dallo static
        handler di Flask montato su /static. Se il percorso richiesto
        corrisponde a un file reale del build lo restituiamo con il suo MIME
        type; altrimenti restituiamo index.html e il routing prosegue lato
        client (deep link come /login o /admin restano funzionanti).

        Args:
            path (str): percorso richiesto, relativo alla cartella static.

        Returns:
            flask.Response: il file richiesto oppure il documento SPA.
        """
        if path:
            # safe_join restituisce None sui tentativi di path traversal
            percorso_file = safe_join(app.static_folder, path)
            if percorso_file is not None and os.path.isfile(percorso_file):
                return send_from_directory(app.static_folder, path)

        return send_from_directory(app.static_folder, DOCUMENTO_SPA)

    # -------------------------------------------------------------------
    # Inizializza schema DB (master + tutti i tenant attivi)
    # -------------------------------------------------------------------
    init_db(app)

    # -------------------------------------------------------------------
    # Migrazioni incrementali per tutti i tenant attivi
    # -------------------------------------------------------------------
    _migra_tutti_i_tenant(app)

    # Registra handler WebSocket (dopo init completo)
    from app.services import websocket as _ws_handlers  # noqa: F401

    return app


# =========================================================================
# Migrazioni multi-tenant
# =========================================================================

def _migra_tutti_i_tenant(app):
    """
    Esegue le migrazioni incrementali su tutti i tenant DB attivi.

    Legge la lista tenant dal master DB e applica le migrazioni
    a ciascun tenant in sequenza.
    """
    with app.app_context():
        master = get_master_db()
        tenants = master.execute(
            "SELECT slug FROM tenants WHERE is_active = 1"
        ).fetchall()

        for row in tenants:
            slug = row['slug']
            try:
                _migra_singolo_tenant(app, slug)
            except Exception as e:
                log.error(
                    "Migrazione tenant '%s' fallita: %s", slug, e
                )


def _migra_singolo_tenant(app, slug):
    """
    Esegue tutte le migrazioni incrementali su un singolo tenant DB.

    Args:
        app: istanza Flask.
        slug: slug del tenant.
    """
    from app.db import get_db

    with app.app_context():
        g.tenant_slug = slug
        db = get_db()

        _migra_colonne(db)
        _migra_flag_e_regole(db)
        _pulisci_style_history(db)

        # Chiudi e pulisci per non interferire con altri tenant
        db.close()
        g.pop('db', None)


def _migra_colonne(db):
    """
    Aggiunge le nuove colonne alle tabelle esistenti in modo sicuro.
    Controlla prima con PRAGMA table_info se la colonna esiste gia'.
    """
    # (tabella, colonna, definizione DDL)
    colonne = [
        ('calendario_turni',   'gruppo_id',           'INTEGER'),
        ('calendario_turni',   'gruppo_sigla',        "TEXT NOT NULL DEFAULT ''"),
        ('calendario_turni',   'gruppo_nome',         "TEXT NOT NULL DEFAULT ''"),
        ('calendario_turni',   'gruppo_ordine',       'INTEGER NOT NULL DEFAULT 0'),
        ('calendario_turni',   'sg_sigla',            "TEXT NOT NULL DEFAULT ''"),
        ('calendario_turni',   'sg_nome',             "TEXT NOT NULL DEFAULT ''"),
        ('calendario_turni',   'sg_ambito',           "TEXT NOT NULL DEFAULT ''"),
        ('calendario_turni',   'sg_ordine',           'INTEGER NOT NULL DEFAULT 0'),
        ('calendario_turni',   'tipi_qualitativi',    "TEXT NOT NULL DEFAULT '[]'"),
        ('assegnazioni_turni', 'conflitti',           "TEXT NOT NULL DEFAULT '[]'"),
        ('sovragruppi',        'ambito',              "TEXT NOT NULL DEFAULT ''"),
        ('sovragruppi',        'style',               "TEXT NOT NULL DEFAULT '{}'"),
        ('gruppi',             'style',               "TEXT NOT NULL DEFAULT '{}'"),
        ('calendario_turni',   'sg_style',            "TEXT NOT NULL DEFAULT '{}'"),
        ('calendario_turni',   'style',               "TEXT NOT NULL DEFAULT '{}'"),
        ('calendari',          'style',               "TEXT NOT NULL DEFAULT '{}'"),
        ('preset_turni',       'style',               "TEXT NOT NULL DEFAULT '{}'"),
        ('calendario_turni',   'turno_style',         "TEXT NOT NULL DEFAULT '{}'"),
        ('calendari',          'regole_snapshot',     "TEXT NOT NULL DEFAULT '[]'"),
        # Parametri ore/peso su flag_turno
        # peso_turno resta dichiarata INTEGER sui DB gia' esistenti: SQLite ha
        # tipizzazione dinamica e l'affinita' INTEGER converte solo quando la
        # conversione e' senza perdita, quindi i pesi frazionari (guardia 24h
        # vale 3.79 turni tipo) si conservano senza migrare il tipo.
        ('flag_turno',         'peso_turno',          'INTEGER DEFAULT NULL'),
        # Fasce orarie: orari, pausa obbligatoria e durate su flag_turno
        ('flag_turno',         'tipo',                "TEXT NOT NULL DEFAULT 'lavorativo'"),
        ('flag_turno',         'orario_inizio',       'TEXT DEFAULT NULL'),
        ('flag_turno',         'orario_fine',         'TEXT DEFAULT NULL'),
        ('flag_turno',         'pausa_minuti',        'INTEGER NOT NULL DEFAULT 10'),
        ('flag_turno',         'durata_netta_minuti', 'INTEGER DEFAULT NULL'),
        ('flag_turno',         'durata_totale_minuti', 'INTEGER DEFAULT NULL'),
        ('flag_turno',         'ore_turno',           'REAL DEFAULT NULL'),
        ('flag_turno',         'ore_primo_giorno',    'REAL DEFAULT NULL'),
        ('flag_turno',         'ore_ultimo_giorno',   'REAL DEFAULT NULL'),
        ('flag_turno',         'mostra_in_struttura', 'INTEGER NOT NULL DEFAULT 1'),
        # Snapshot parametri ore/peso in calendario_turni
        ('calendario_turni',   'peso_turno',          'INTEGER NOT NULL DEFAULT 1'),
        ('calendario_turni',   'ore_turno',           'REAL DEFAULT NULL'),
        ('calendario_turni',   'ore_primo_giorno',    'REAL DEFAULT NULL'),
        ('calendario_turni',   'ore_ultimo_giorno',   'REAL DEFAULT NULL'),
        # flag_nome / flag_id in calendario_turni
        ('calendario_turni',   'flag_nome',           'TEXT DEFAULT NULL'),
        ('calendario_turni',   'flag_id',             'INTEGER'),
        # Descrizione e carico lavoro su tipi_qualitativo
        ('tipi_qualitativo',   'descrizione',         "TEXT NOT NULL DEFAULT ''"),
        ('tipi_qualitativo',   'carico_lavoro',       'INTEGER NOT NULL DEFAULT 0'),
        # Categoria e stile su regole_conflitto
        ('regole_conflitto',   'categoria',           "TEXT NOT NULL DEFAULT 'consigliata'"),
        ('regole_conflitto',   'stile',               "TEXT NOT NULL DEFAULT '{\"backgroundColor\":\"#fff3cd\",\"color\":\"#856404\"}'"),
        # Solver: priorita' e peso su preset_turni e snapshot calendario_turni
        ('preset_turni',       'priorita_solver',     "TEXT NOT NULL DEFAULT 'automatico'"),
        ('preset_turni',       'peso_priorita_solver', 'INTEGER NOT NULL DEFAULT 50'),
        ('calendario_turni',   'priorita_solver',     "TEXT NOT NULL DEFAULT 'automatico'"),
        ('calendario_turni',   'peso_priorita_solver', 'INTEGER NOT NULL DEFAULT 50'),
        # Turno: aperture festivi/superfestivi
        ('preset_turni',       'apri_festivi',        'INTEGER NOT NULL DEFAULT 0'),
        ('preset_turni',       'apri_superfestivi',   'INTEGER NOT NULL DEFAULT 0'),
        ('calendario_turni',   'apri_festivi',        'INTEGER NOT NULL DEFAULT 0'),
        ('calendario_turni',   'apri_superfestivi',   'INTEGER NOT NULL DEFAULT 0'),
        ('calendario_turni',   'aperture_straordinarie', "TEXT NOT NULL DEFAULT '[]'"),
        # Snapshot completo config per calendario
        ('calendari',          'config_snapshot',        'TEXT DEFAULT NULL'),
        # Giorni esclusi per utente (JSON array di day-of-week: 0=Lun..6=Dom)
        ('users',              'giorni_esclusi',         "TEXT NOT NULL DEFAULT '[]'"),
        # Eccezioni figli esenti per esclusioni turno preset
        ('preset_esclusioni_turno_per_utente', 'eccezioni', "TEXT NOT NULL DEFAULT '[]'"),
        # Gestione calendari: flag per manager/admin
        ('users',              'puo_gestire_calendari', 'INTEGER NOT NULL DEFAULT 0'),
        # Preset predefinito per nuovi calendari
        ('struttura_presets',  'is_default',            'INTEGER NOT NULL DEFAULT 0'),
        # Disattivazione/nascondimento turni nel preset
        ('preset_turni',       'is_disabled',           'INTEGER NOT NULL DEFAULT 0'),
        ('preset_turni',       'is_hidden',             'INTEGER NOT NULL DEFAULT 0'),
        # Snapshot disattivazione/nascondimento in calendario_turni
        ('calendario_turni',   'is_disabled',           'INTEGER NOT NULL DEFAULT 0'),
        ('calendario_turni',   'is_hidden',             'INTEGER NOT NULL DEFAULT 0'),
        # Users: sovragruppo appartenenza + privacy desiderata + ordine vista desiderata
        ('users',              'sovragruppo_id',        'INTEGER DEFAULT NULL REFERENCES sovragruppi(id) ON DELETE SET NULL'),
        ('users',              'offusca',               'INTEGER NOT NULL DEFAULT 0'),
        ('users',              'ordine_desiderata',     'INTEGER NOT NULL DEFAULT 0'),
        # Sovragruppi: ordine override per viste desiderata
        ('sovragruppi',        'ordine_desiderata',     'INTEGER DEFAULT NULL'),
    ]

    # Crea tabelle nuove se non esistono (per DB pre-esistenti)
    nuove_tabelle = [
        (
            "CREATE TABLE IF NOT EXISTS flag_turno ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  nome TEXT NOT NULL UNIQUE,"
            "  parent_id INTEGER REFERENCES flag_turno(id),"
            "  descrizione TEXT,"
            "  peso_turno INTEGER DEFAULT NULL,"
            "  ore_turno REAL DEFAULT NULL,"
            "  ore_primo_giorno REAL DEFAULT NULL,"
            "  ore_ultimo_giorno REAL DEFAULT NULL"
            ")"
        ),
        (
            "CREATE TABLE IF NOT EXISTS vincoli_solver ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  tipo TEXT NOT NULL CHECK(tipo IN ('flag','qualitativo')),"
            "  ref_id INTEGER NOT NULL,"
            "  max_n INTEGER NOT NULL DEFAULT 0,"
            "  is_active INTEGER NOT NULL DEFAULT 1,"
            "  descrizione TEXT,"
            "  UNIQUE(tipo, ref_id)"
            ")"
        ),
        (
            "CREATE TABLE IF NOT EXISTS vincoli_solver_utente ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
            "  tipo TEXT NOT NULL CHECK(tipo IN ('flag','qualitativo')),"
            "  ref_id INTEGER NOT NULL,"
            "  max_n INTEGER NOT NULL DEFAULT 0,"
            "  note TEXT,"
            "  UNIQUE(user_id, tipo, ref_id)"
            ")"
        ),
        (
            "CREATE TABLE IF NOT EXISTS manager_accesso_utenti ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  manager_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
            "  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
            "  UNIQUE(manager_id, user_id)"
            ")"
        ),
        (
            "CREATE TABLE IF NOT EXISTS manager_accesso_turni ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  manager_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
            "  preset_turno_id INTEGER NOT NULL REFERENCES preset_turni(id) ON DELETE CASCADE,"
            "  UNIQUE(manager_id, preset_turno_id)"
            ")"
        ),
    ]

    for sql in nuove_tabelle:
        try:
            db.execute(sql)
            db.commit()
        except Exception as e:
            log.warning('Creazione tabella fallita: %s', e)

    # Aggiungi colonne mancanti
    for tabella, colonna, definizione in colonne:
        try:
            cols = [r[1] for r in db.execute(f'PRAGMA table_info({tabella})').fetchall()]
            if colonna not in cols:
                db.execute(f'ALTER TABLE {tabella} ADD COLUMN {colonna} {definizione}')
                db.commit()
        except Exception as e:
            log.warning('Migrazione colonna %s.%s fallita: %s', tabella, colonna, e)

    # Seed dei flag e derivazione dei parametri: dopo le ALTER, perche'
    # inseriscono e leggono le colonne appena aggiunte.
    _rimuovi_concetto_composto(db)
    _inserisci_flag_default(db)
    _nascondi_assenze_dalla_struttura(db)
    _migra_gruppi_su_fasce(db)
    ricalcola_tutte(db)
    _crea_indice_fascia_unica(db)

    # Rinomina peso_solver → peso_priorita_solver
    for tabella in ('preset_turni', 'calendario_turni'):
        try:
            cols = [r[1] for r in db.execute(f'PRAGMA table_info({tabella})').fetchall()]
            if 'peso_solver' in cols and 'peso_priorita_solver' not in cols:
                db.execute(f'ALTER TABLE {tabella} RENAME COLUMN peso_solver TO peso_priorita_solver')
                db.commit()
                log.info('Rinominata colonna %s.peso_solver → peso_priorita_solver', tabella)
        except Exception as e:
            log.warning('Rinomina peso_solver in %s fallita: %s', tabella, e)


def _nascondi_assenze_dalla_struttura(db):
    """
    Riporta a zero la visibilita' in struttura turni di tutti i flag assenza.

    Un'assenza non e' una fascia oraria: non ha orari e non puo' diventare il
    gruppo di un sovragruppo. Le route la scrivono gia' a zero, ma un tenant
    creato prima di questo vincolo puo' avere assenze visibili.

    Idempotente: dopo il primo giro la UPDATE non trova piu' righe.
    """
    try:
        nascoste = db.execute(
            "UPDATE flag_turno SET mostra_in_struttura = 0 "
            "WHERE tipo = 'assenza' AND mostra_in_struttura != 0"
        ).rowcount
        db.commit()

        if nascoste:
            log.info('Tolte dalla struttura turni %d assenze visibili', nascoste)
    except Exception as e:
        db.rollback()
        log.warning('Nascondere le assenze dalla struttura turni e\' fallito: %s', e)


def _rimuovi_concetto_composto(db):
    """
    Elimina il concetto di flag "composto": colonna `entita` e tabella
    `flag_composizione`.

    Feature removal. Un flag composto elencava i flag che lo compongono
    (lunga = mattina + pomeriggio); con le fasce orarie la stessa
    informazione sta negli orari della fascia (lunga e' 08:00-20:40), quindi
    la composizione e' una duplicazione che puo' divergere dagli orari.

    Idempotente: entrambi i passi sono protetti da un controllo di esistenza,
    cosi' l'avvio successivo non trova piu' nulla da fare.
    """
    try:
        db.execute('DROP TABLE IF EXISTS flag_composizione')
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning('Rimozione della tabella flag_composizione fallita: %s', e)

    try:
        colonne = [r[1] for r in db.execute('PRAGMA table_info(flag_turno)').fetchall()]
        if 'entita' in colonne:
            db.execute('ALTER TABLE flag_turno DROP COLUMN entita')
            db.commit()
            log.info('Rimossa la colonna flag_turno.entita')
    except Exception as e:
        db.rollback()
        log.warning('Rimozione della colonna flag_turno.entita fallita: %s', e)


def _inserisci_flag_default(db):
    """
    Inserisce i flag globali default se non esistono.

    Struttura: i concetti root nascosti (turno_tipo, diurno, notturno,
    guardia_24h), le fasce orarie come loro figlie con gli orari concreti,
    e i flag assenza come root.

    Durate, ore e peso non si scrivono qui: li deriva dagli orari
    fasce_orarie.ricalcola_tutte().
    """
    try:
        for nome, descrizione, netta, pausa in CONCETTI_ROOT:
            db.execute(
                "INSERT OR IGNORE INTO flag_turno "
                "(nome, parent_id, descrizione, durata_netta_minuti, "
                " pausa_minuti, mostra_in_struttura, tipo) "
                "VALUES (?, NULL, ?, ?, ?, 0, 'lavorativo')",
                (nome, descrizione, netta, pausa)
            )

        for nome, descrizione in FLAG_ASSENZA:
            db.execute(
                "INSERT OR IGNORE INTO flag_turno "
                "(nome, parent_id, descrizione, mostra_in_struttura, tipo) "
                "VALUES (?, NULL, ?, 0, 'assenza')",
                (nome, descrizione)
            )

        for nome, padre, descrizione, inizio, fine, pausa in FASCE_DEFAULT:
            db.execute(
                "INSERT OR IGNORE INTO flag_turno "
                "(nome, parent_id, descrizione, orario_inizio, orario_fine, "
                " pausa_minuti, tipo) "
                "VALUES (?, (SELECT id FROM flag_turno WHERE nome = ?), "
                "        ?, ?, ?, ?, 'lavorativo')",
                (nome, padre, descrizione, inizio, fine, pausa)
            )

        # I concetti root portano il concetto, non gli orari: ai gruppi si
        # agganciano soltanto le fasce.
        segnaposto = ','.join('?' * len(CONCETTI_ROOT))
        db.execute(
            "UPDATE flag_turno SET mostra_in_struttura = 0 "
            f"WHERE nome IN ({segnaposto})",
            tuple(nome for nome, _, _, _ in CONCETTI_ROOT)
        )

        db.commit()
    except Exception as e:
        db.rollback()
        log.warning('Inserimento flag default fallito: %s', e)

    _applica_orari_default_alle_fasce(db)


def _applica_orari_default_alle_fasce(db):
    """
    Assegna gli orari default alle fasce che ancora non ne hanno.

    Serve ai tenant creati prima delle fasce orarie: mattina, pomeriggio e
    lunga esistono gia', quindi l'INSERT OR IGNORE del seed non le tocca e
    resterebbero senza orari, cioe' senza ore ne' peso derivati.

    Non sovrascrive orari gia' impostati: se l'amministratore ha
    personalizzato una fascia, resta com'e'.
    """
    for nome, _, _, inizio, fine, pausa in FASCE_DEFAULT:
        try:
            aggiornate = db.execute(
                "UPDATE flag_turno "
                "SET orario_inizio = ?, orario_fine = ?, pausa_minuti = ? "
                "WHERE nome = ? "
                "  AND orario_inizio IS NULL AND orario_fine IS NULL",
                (inizio, fine, pausa, nome)
            ).rowcount
            db.commit()

            if aggiornate:
                log.info(
                    "Fascia '%s': applicati gli orari default %s-%s",
                    nome, inizio, fine
                )
        except Exception as e:
            db.rollback()
            log.warning("Orari default per la fascia '%s' falliti: %s", nome, e)


def _migra_gruppi_su_fasce(db):
    """
    Sposta sui rispettivi figli i gruppi agganciati a un concetto root.

    Prima delle fasce orarie un gruppo si agganciava direttamente al concetto
    (flag 'notturno'). I concetti ora sono nascosti e senza orari, quindi un
    gruppo rimasto appeso li' non avrebbe piu' ne' ore ne' peso.

    Non tocca gli snapshot in calendario_turni: sono congelati per
    definizione, e riscriverli cambierebbe le ore di calendari gia' chiusi.
    Il riconoscimento delle notti sugli snapshot vecchi resta garantito dal
    fatto che il concetto root matcha se stesso (fasce_orarie.discende_da).
    """
    for nome_root, nome_fascia in MIGRAZIONE_ROOT_SU_FASCIA.items():
        try:
            # Il NOT EXISTS evita di creare due gruppi della stessa fascia
            # nella stessa struttura: quei casi restano da sanare a mano.
            spostati = db.execute(
                "UPDATE gruppi SET flag_id = "
                "    (SELECT id FROM flag_turno WHERE nome = ?) "
                "WHERE flag_id = (SELECT id FROM flag_turno WHERE nome = ?) "
                "  AND NOT EXISTS ("
                "      SELECT 1 FROM gruppi g2 "
                "      WHERE g2.sovragruppo_id = gruppi.sovragruppo_id "
                "        AND g2.flag_id = "
                "            (SELECT id FROM flag_turno WHERE nome = ?)"
                "  )",
                (nome_fascia, nome_root, nome_fascia)
            ).rowcount
            db.commit()

            if spostati:
                log.info(
                    "Migrati %d gruppi dal concetto '%s' alla fascia '%s'",
                    spostati, nome_root, nome_fascia
                )
        except Exception as e:
            db.rollback()
            log.warning(
                "Migrazione gruppi da '%s' a '%s' fallita: %s",
                nome_root, nome_fascia, e
            )


def _crea_indice_fascia_unica(db):
    """
    Impone che una fascia oraria esista una volta sola per struttura.

    Il gruppo E' l'insieme dei turni di una fascia dentro un sovragruppo:
    definire due volte la mattina dello stesso reparto non ha significato.

    Se il tenant ha gia' duplicati l'indice non e' creabile: li registra nel
    log e prosegue, perche' quale gruppo tenere e' una decisione dell'utente.
    """
    try:
        duplicati = db.execute(
            "SELECT sovragruppo_id, flag_id, COUNT(*) AS quanti FROM gruppi "
            "WHERE flag_id IS NOT NULL "
            "GROUP BY sovragruppo_id, flag_id HAVING quanti > 1"
        ).fetchall()
    except Exception as e:
        log.warning('Verifica duplicati fascia per struttura fallita: %s', e)
        return

    if duplicati:
        log.warning(
            'Vincolo fascia unica per struttura non applicato: %d coppie '
            '(sovragruppo, fascia) duplicate da sanare a mano', len(duplicati)
        )
        return

    try:
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_gruppi_sovragruppo_fascia "
            "ON gruppi(sovragruppo_id, flag_id) WHERE flag_id IS NOT NULL"
        )
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning('Creazione indice fascia unica fallita: %s', e)


def _migra_flag_e_regole(db):
    """
    Migrazione per DB esistenti:
    1. Associa flag ai tipi_richiesta esistenti per sigla/tipo
    2. Inserisce regole conflitto default se non esistono
    3. Migra max_notti_mese → vincoli_solver
    """
    # 1. Associa flag ai tipi_richiesta
    try:
        cols = [r[1] for r in db.execute('PRAGMA table_info(tipi_richiesta)').fetchall()]
        if 'flag_id' in cols:
            mapping_tr = {
                'M': 'mattina', 'P': 'pomeriggio', 'N': 'notturno',
                'L': 'lunga', 'CO': 'ferie', 'CORX': 'ferie',
                'ROMC': 'riposo', 'ROMP': 'riposo', 'AGG': 'agg',
                'PERM': 'permesso', 'LEGGE': 'legge',
            }
            for sigla, nome_flag in mapping_tr.items():
                db.execute(
                    "UPDATE tipi_richiesta SET flag_id = "
                    "(SELECT id FROM flag_turno WHERE nome = ?) "
                    "WHERE sigla = ? AND flag_id IS NULL",
                    (nome_flag, sigla)
                )
            db.commit()
    except Exception as e:
        log.warning('Migrazione flag tipi_richiesta fallita: %s', e)

    # 2. Inserisci regole conflitto default
    try:
        esistenti = db.execute("SELECT id FROM regole_conflitto LIMIT 1").fetchall()
        if not esistenti:
            _inserisci_regole_default_nuove(db)
    except Exception as e:
        log.warning('Check regole_conflitto fallito: %s', e)

    # 3. Migra max_notti_mese → vincoli_solver
    try:
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if 'vincoli_solver' in tables:
            row = db.execute(
                "SELECT valore FROM vincoli_globali WHERE chiave='max_notti_mese'"
            ).fetchone()
            if row:
                flag_nott = db.execute(
                    "SELECT id FROM flag_turno WHERE nome='notturno'"
                ).fetchone()
                if flag_nott:
                    db.execute(
                        "INSERT OR IGNORE INTO vincoli_solver "
                        "(tipo, ref_id, max_n, is_active, descrizione) "
                        "VALUES ('flag', ?, ?, 1, 'Max notti/mese (migrato)')",
                        (flag_nott[0], int(row[0]))
                    )
                db.execute(
                    "DELETE FROM vincoli_globali WHERE chiave='max_notti_mese'"
                )
                db.commit()
                log.info('Migrato max_notti_mese → vincoli_solver')

            db.execute(
                "INSERT OR IGNORE INTO vincoli_globali (chiave, valore, descrizione) "
                "VALUES ('max_n_turni_mese', '0', "
                "'Offset turni/mese rispetto a turni dovuti (0=esatto, +N/-N)')"
            )
            db.commit()
    except Exception as e:
        log.warning('Migrazione vincoli_solver fallita: %s', e)


def _inserisci_regole_default_nuove(db):
    """Inserisce le 4 regole default."""
    try:
        regole = [
            ('No altri turni con notte', 'tipo_vs_tipo', 'notturno', None, 0,
             'critica', '{"backgroundColor":"#ffcdd2","color":"#c62828"}', 0, 8.0),
            ('Riposo post-notte', 'tipo_vs_tipo', 'notturno', 'diurno', 1,
             'critica', '{"backgroundColor":"#ffcdd2","color":"#c62828"}', 0, 8.0),
            ('Assenza bloccante', 'desiderata_assenza_mismatch', None, None, 0,
             'critica', '{"backgroundColor":"#ffcdd2","color":"#c62828"}', 1, 10.0),
            ('Mismatch desiderata', 'desiderata_mismatch', None, None, 0,
             'consigliata', '{"backgroundColor":"#fff3cd","color":"#856404"}', 0, 2.0),
        ]

        for nome, tipo_r, flag_a, flag_b, offset, cat, stile, blocca, peso in regole:
            fa = db.execute(
                "SELECT id FROM flag_turno WHERE nome=?", (flag_a,)
            ).fetchone() if flag_a else None
            fb = db.execute(
                "SELECT id FROM flag_turno WHERE nome=?", (flag_b,)
            ).fetchone() if flag_b else None

            db.execute(
                "INSERT INTO regole_conflitto "
                "(nome, tipo_regola, flag_a_id, flag_b_id, "
                "offset_giorni, categoria, stile, blocca_inserimento, peso_numerico) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (nome, tipo_r, fa[0] if fa else None, fb[0] if fb else None,
                 offset, cat, stile, blocca, peso)
            )

        db.commit()
    except Exception as e:
        log.warning('Inserimento regole default fallito: %s', e)


def _pulisci_style_history(db):
    """
    Rimuove entries orfane da style_history il cui contesto (calendario o preset)
    non esiste piu'.
    """
    try:
        db.execute(
            "DELETE FROM style_history WHERE contesto = 'calendario' "
            "AND contesto_id NOT IN (SELECT id FROM calendari)"
        )
        db.execute(
            "DELETE FROM style_history WHERE contesto = 'preset' "
            "AND contesto_id NOT IN (SELECT id FROM struttura_presets)"
        )
        db.commit()
    except Exception as e:
        log.warning('Pulizia style_history fallita: %s', e)
