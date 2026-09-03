-- =============================================================================
-- Turnificator9000 — Schema database SQLCipher
-- =============================================================================
-- Tutte le istruzioni sono idempotenti (IF NOT EXISTS / OR IGNORE).
-- =============================================================================

-- Nota: PRAGMA foreign_keys e' impostata a livello di connessione (vedi
-- app/db.py::_open_db). Non e' impostata qui per evitare che fresh init via
-- executescript fallisca su forward FK references (es. users.sovragruppo_id
-- riferisce sovragruppi creata dopo): durante l'esecuzione del file, le FK
-- restano off finche' lo script non finisce e la connessione le riattiva.

-- =============================================================================
-- TABELLA: users
-- =============================================================================
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK(role IN ('admin', 'manager', 'basic')),
    sigla         TEXT    NOT NULL UNIQUE,
    is_active      INTEGER NOT NULL DEFAULT 1,
    escluso_turni  INTEGER NOT NULL DEFAULT 0,
    giorni_esclusi TEXT    NOT NULL DEFAULT '[]',  -- JSON array day-of-week (0=Lun..6=Dom)
    puo_gestire_calendari INTEGER NOT NULL DEFAULT 0,  -- solo manager/admin: crea/elimina calendari
    sovragruppo_id INTEGER REFERENCES sovragruppi(id) ON DELETE SET NULL,
    offusca        INTEGER NOT NULL DEFAULT 0 CHECK(offusca IN (0,1,2)),
    -- 0=nessuno, 1=offusca ragioni assenze (X), 2=offusca tutto
    ordine_desiderata INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    created_by     INTEGER REFERENCES users(id)
);

-- =============================================================================
-- TABELLA: flag_turno
-- Registro globale dei flag semantici con gerarchia parent.
-- Usato per classificare turni e desiderata. Unico vocabolario condiviso.
--
-- Struttura:
--   Concetti root, nascosti perche' non agganciabili ai gruppi:
--       turno_tipo   unita' di misura del peso (durata netta 6h20)
--       diurno       → fasce mattina, pomeriggio, lunga
--       notturno     → fascia notte
--       guardia_24h  → fascia guardia
--   Le fasce orarie sono i figli dei concetti: portano gli orari concreti
--   e sono le sole agganciabili ai gruppi. Possono essere rinominate: il
--   riferimento stabile per il codice e' il nome del concetto root.
--   Assenza: ferie, agg, malattia, riposo, permesso, legge (root)
--
-- Campi derivati, ricalcolati all'avvio da app/services/fasce_orarie.py e mai
-- digitati dall'utente: durata_netta_minuti, durata_totale_minuti, ore_turno,
-- peso_turno. L'utente compila solo orari e pausa.
-- =============================================================================
CREATE TABLE IF NOT EXISTS flag_turno (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nome              TEXT    NOT NULL UNIQUE,
    parent_id         INTEGER REFERENCES flag_turno(id),
    descrizione       TEXT,
    orario_inizio     TEXT    DEFAULT NULL,  -- 'HH:MM', NULL sui concetti root
    orario_fine       TEXT    DEFAULT NULL,  -- 'HH:MM'; = inizio significa 24 ore
    pausa_minuti      INTEGER NOT NULL DEFAULT 10,  -- pausa obbligatoria, si somma alla netta
    durata_netta_minuti  INTEGER DEFAULT NULL,  -- lavoro effettivo, dagli orari
    durata_totale_minuti INTEGER DEFAULT NULL,  -- netta + pausa
    peso_turno        REAL    DEFAULT NULL,  -- netta / netta del turno tipo
    ore_turno         REAL    DEFAULT NULL,  -- durata totale in ore decimali
    ore_primo_giorno  REAL    DEFAULT NULL,
    ore_ultimo_giorno REAL    DEFAULT NULL,
    mostra_in_struttura INTEGER NOT NULL DEFAULT 1,
    -- Il riempimento automatico non usa la fascia di sua iniziativa: la
    -- mette solo dove il lavoratore l'ha chiesta. E' il caso della lunga.
    solo_su_richiesta   INTEGER NOT NULL DEFAULT 0,
    tipo              TEXT    NOT NULL DEFAULT 'lavorativo' CHECK(tipo IN ('lavorativo', 'assenza'))
);

-- Flag default — concetti root lavorativi.
-- Non portano orari: quelli stanno sulle fasce figlie. Fa eccezione
-- turno_tipo, che non classifica nulla ed esiste solo come unita' di misura
-- del peso: 380 minuti = 6h20 di lavoro effettivo.
INSERT OR IGNORE INTO flag_turno
    (nome, parent_id, descrizione, durata_netta_minuti, pausa_minuti,
     mostra_in_struttura, tipo) VALUES
    ('turno_tipo',  NULL, 'Turno tipo — unita di misura del peso', 380,  10, 0, 'lavorativo'),
    ('diurno',      NULL, 'Turno diurno generico',                 NULL, 10, 0, 'lavorativo'),
    ('notturno',    NULL, 'Turno notturno',                        NULL, 10, 0, 'lavorativo'),
    ('guardia_24h', NULL, 'Guardia 24 ore',                        NULL,  0, 0, 'lavorativo');

-- Flag default — assenze (root, mostra_in_struttura=0)
INSERT OR IGNORE INTO flag_turno (nome, parent_id, descrizione, tipo, mostra_in_struttura) VALUES
    ('ferie',    NULL, 'Ferie',          'assenza', 0),
    ('agg',      NULL, 'Aggiornamento',  'assenza', 0),
    ('malattia', NULL, 'Malattia',       'assenza', 0),
    ('riposo',   NULL, 'Riposo',         'assenza', 0),
    ('permesso', NULL, 'Permesso',       'assenza', 0),
    ('legge',    NULL, 'Legge',          'assenza', 0);

-- Flag default — fasce orarie: i figli dei concetti, con gli orari concreti.
-- Durate, ore e peso non si scrivono qui: li deriva il ricalcolo all'avvio.
INSERT OR IGNORE INTO flag_turno
    (nome, parent_id, descrizione, orario_inizio, orario_fine, pausa_minuti) VALUES
    ('mattina',    (SELECT id FROM flag_turno WHERE nome='diurno'),      'Fascia mattina',    '08:00', '14:20', 10),
    ('pomeriggio', (SELECT id FROM flag_turno WHERE nome='diurno'),      'Fascia pomeriggio', '14:00', '20:20', 10),
    ('lunga',      (SELECT id FROM flag_turno WHERE nome='diurno'),      'Fascia lunga',      '08:00', '20:40', 10),
    ('notte',      (SELECT id FROM flag_turno WHERE nome='notturno'),    'Fascia notte',      '20:00', '08:40', 10),
    ('guardia',    (SELECT id FROM flag_turno WHERE nome='guardia_24h'), 'Fascia guardia',    '00:00', '24:00',  0);
-- Nascondi da struttura turni i concetti root: si agganciano le fasce orarie,
-- mai i concetti. (I flag assenza hanno gia' mostra_in_struttura=0 nel seed.)
UPDATE flag_turno SET mostra_in_struttura = 0
 WHERE nome IN ('turno_tipo', 'diurno', 'notturno', 'guardia_24h');

-- =============================================================================
-- TABELLA: configurazioni
-- Una configurazione salvata: l'intera impostazione del tenant congelata in
-- uno snapshot, piu' la struttura turni che le corrisponde. Attivarne una
-- riporta le tabelle di configurazione allo stato che avevano.
--
-- I nomi strutturali (turno_tipo, notturno, diurno) restano invarianti fra
-- una configurazione e l'altra: sono l'impalcatura su cui il codice ragiona.
-- =============================================================================
CREATE TABLE IF NOT EXISTS configurazioni (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nome       TEXT    NOT NULL UNIQUE,
    snapshot   TEXT    NOT NULL,                 -- JSON, come config_snapshot
    preset_id  INTEGER REFERENCES struttura_presets(id) ON DELETE SET NULL,
    is_attiva  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Una sola configurazione attiva per volta.
CREATE UNIQUE INDEX IF NOT EXISTS idx_configurazioni_attiva
    ON configurazioni(is_attiva) WHERE is_attiva = 1;

-- =============================================================================
-- TABELLA: proposte_configurazione
-- Il master non impone una configurazione: la deposita qui, e
-- l'amministratore del tenant la confronta con quella in uso e decide.
-- Sta nel database del tenant perche' cosi' si legge e si accetta anche
-- quando il master e' irraggiungibile.
--
-- La proposta contiene solo le parti trasferibili fra reparti: fasce orarie
-- e assenze, tipologie turno, tipi richiesta, regole di conflitto.
-- =============================================================================
CREATE TABLE IF NOT EXISTS proposte_configurazione (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT    NOT NULL,               -- come il master la chiama
    proposta    TEXT    NOT NULL,               -- JSON delle quattro parti
    proposta_da TEXT    NOT NULL,               -- master admin che l'ha inviata
    note        TEXT,                           -- perche' la propone
    stato       TEXT    NOT NULL DEFAULT 'in_attesa'
                    CHECK(stato IN ('in_attesa', 'accettata', 'rifiutata', 'ritirata')),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    decisa_at   TEXT,
    decisa_da   TEXT                            -- admin del tenant che ha deciso
);

-- Una proposta in attesa per volta: due contemporanee metterebbero
-- l'amministratore a scegliere fra cose che non ha chiesto.
CREATE UNIQUE INDEX IF NOT EXISTS idx_proposte_in_attesa
    ON proposte_configurazione(stato) WHERE stato = 'in_attesa';

-- =============================================================================
-- TABELLA: flag_composizione
-- Quali fasce, messe insieme, soddisfano la richiesta di un'altra: chi chiede
-- la lunga puo' ricevere mattina + pomeriggio.
--
-- Serve SOLO a questo. Durata, ore e peso restano derivati dagli orari e non
-- si leggono mai da qui: e' la confusione fra le due cose che aveva reso
-- questa tabella una fonte di divergenze, la prima volta che e' esistita.
-- =============================================================================
CREATE TABLE IF NOT EXISTS flag_composizione (
    flag_id            INTEGER NOT NULL REFERENCES flag_turno(id) ON DELETE CASCADE,
    componente_flag_id INTEGER NOT NULL REFERENCES flag_turno(id) ON DELETE CASCADE,
    PRIMARY KEY (flag_id, componente_flag_id)
);

-- =============================================================================
-- TABELLA: struttura_presets
-- Preset riutilizzabili per la struttura turni (sovragruppi→gruppi→turni).
-- =============================================================================
CREATE TABLE IF NOT EXISTS struttura_presets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT    NOT NULL UNIQUE,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    created_by      INTEGER REFERENCES users(id),
    last_used_at    TEXT,   -- aggiornato alla creazione di un calendario con questo preset
    is_default      INTEGER NOT NULL DEFAULT 0,  -- preset predefinito per nuovi calendari
    appearance      TEXT    -- JSON: festivi_bg, superfestivi_bg, prima_riga_bg, cella_bordo_*, bordo_esterno_*
);

-- =============================================================================
-- TABELLA: tipi_richiesta
-- Tipi di richiesta desiderata. Ogni tipo ha un flag semantico globale.
-- Globali (un set per tenant).
-- =============================================================================
CREATE TABLE IF NOT EXISTS tipi_richiesta (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    sigla                 TEXT    NOT NULL UNIQUE,
    descrizione           TEXT    NOT NULL,
    tipo                  TEXT    NOT NULL CHECK(tipo IN ('lavorativo','assenza')),
    flag_id               INTEGER REFERENCES flag_turno(id),
    counting_flag         INTEGER NOT NULL DEFAULT 1,
    ore_default           REAL    DEFAULT NULL,
    ordine                INTEGER NOT NULL DEFAULT 0,
    is_active             INTEGER NOT NULL DEFAULT 1
);

-- =============================================================================
-- TABELLA: calendari
-- preset_id: riferimento al preset sorgente (informativo, nullable).
-- =============================================================================
CREATE TABLE IF NOT EXISTS calendari (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    mese                    INTEGER NOT NULL CHECK(mese BETWEEN 1 AND 12),
    anno                    INTEGER NOT NULL,
    stato                   TEXT    NOT NULL DEFAULT 'APERTO'
                                CHECK(stato IN ('APERTO','CHIUSO')),
    ore_giornaliere_default REAL    NOT NULL DEFAULT 6.5,
    deadline_globale        TEXT    DEFAULT NULL,
    desiderata_congelati    INTEGER NOT NULL DEFAULT 0,
    preset_id               INTEGER REFERENCES struttura_presets(id) ON DELETE SET NULL,
    style                   TEXT    NOT NULL DEFAULT '{}',
    regole_snapshot         TEXT    NOT NULL DEFAULT '[]',
    config_snapshot         TEXT    DEFAULT NULL,
    appearance_snapshot     TEXT    DEFAULT NULL,
    esclusioni_manuali      TEXT    NOT NULL DEFAULT '[]',
    celle_bloccate          TEXT    NOT NULL DEFAULT '[]',
    chiuso_il               TEXT    DEFAULT NULL,
    versione                INTEGER NOT NULL DEFAULT 0,
    tipo                    TEXT    NOT NULL DEFAULT 'programmato'
                                CHECK(tipo IN ('programmato','effettivo')),
    parent_id               INTEGER DEFAULT NULL REFERENCES calendari(id) ON DELETE CASCADE,
    created_by              INTEGER REFERENCES users(id),
    created_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(mese, anno, tipo, versione)
);

-- =============================================================================
-- TABELLA: versioni_calendario
-- Log storico di chiusure e riaperture di un calendario.
-- =============================================================================
CREATE TABLE IF NOT EXISTS versioni_calendario (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    calendario_id INTEGER NOT NULL REFERENCES calendari(id) ON DELETE CASCADE,
    versione      INTEGER NOT NULL,
    chiuso_il     TEXT    NOT NULL,
    riaperto_il   TEXT    DEFAULT NULL,
    UNIQUE(calendario_id, versione)
);

-- =============================================================================
-- TABELLA: calendario_turni
-- Snapshot completo e autosufficiente dei turni per ogni calendario.
-- Contiene tutta la gerarchia SG→Gruppo→Turno copiata al momento della creazione.
-- Nessuna dipendenza da preset/gruppi/sovragruppi dopo la creazione.
-- Usata come FK da assegnazioni_turni.
--
-- Campi criterio (snapshot):
--   flag_nome          → nome del flag semantico del gruppo (es. "notturno", "diurno")
--   flag_id            → ID del flag turno
--   tipi_qualitativi   → JSON array dei criteri qualitativi del turno
--   sg_ambito          → ambito operativo del sovragruppo (es. "Radiologia")
-- =============================================================================
CREATE TABLE IF NOT EXISTS calendario_turni (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    calendario_id   INTEGER NOT NULL REFERENCES calendari(id) ON DELETE CASCADE,
    local_id        TEXT    NOT NULL,
    sigla           TEXT    NOT NULL,
    nome            TEXT    NOT NULL DEFAULT '',
    flag_nome       TEXT    DEFAULT NULL,
    flag_id         INTEGER,
    tipi_qualitativi TEXT   NOT NULL DEFAULT '[]',
    gruppo_id       INTEGER,
    gruppo_sigla    TEXT    NOT NULL DEFAULT '',
    gruppo_nome     TEXT    NOT NULL DEFAULT '',
    gruppo_ordine   INTEGER NOT NULL DEFAULT 0,
    sg_id           INTEGER,
    sg_sigla        TEXT    NOT NULL DEFAULT '',
    sg_nome         TEXT    NOT NULL DEFAULT '',
    sg_ambito       TEXT    NOT NULL DEFAULT '',
    sg_ordine       INTEGER NOT NULL DEFAULT 0,
    sg_style        TEXT    NOT NULL DEFAULT '{}',
    ordine            INTEGER NOT NULL DEFAULT 0,
    style             TEXT    NOT NULL DEFAULT '{}',
    turno_style       TEXT    NOT NULL DEFAULT '{}',
    peso_turno        INTEGER NOT NULL DEFAULT 1,
    ore_turno         REAL    DEFAULT NULL,
    ore_primo_giorno  REAL    DEFAULT NULL,
    ore_ultimo_giorno REAL    DEFAULT NULL,
    priorita_solver   TEXT    NOT NULL DEFAULT 'automatico'
                          CHECK(priorita_solver IN ('indispensabile','automatico','manuale')),
    peso_priorita_solver       INTEGER NOT NULL DEFAULT 50,
    apri_festivi         INTEGER NOT NULL DEFAULT 0,
    apri_superfestivi    INTEGER NOT NULL DEFAULT 0,
    aperture_straordinarie TEXT NOT NULL DEFAULT '[]',
    is_disabled          INTEGER NOT NULL DEFAULT 0,
    is_hidden            INTEGER NOT NULL DEFAULT 0,
    UNIQUE(calendario_id, local_id)
);

-- =============================================================================
-- TABELLA: giorni_calendario
-- =============================================================================
CREATE TABLE IF NOT EXISTS giorni_calendario (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    calendario_id  INTEGER NOT NULL REFERENCES calendari(id) ON DELETE CASCADE,
    giorno         INTEGER NOT NULL CHECK(giorno BETWEEN 1 AND 31),
    is_lavorativo  INTEGER NOT NULL DEFAULT 1,
    ore_lavorative REAL    DEFAULT NULL,
    tipo           TEXT    NOT NULL DEFAULT 'normale'
                       CHECK(tipo IN ('normale','festivo','superfestivo')),
    UNIQUE(calendario_id, giorno)
);

-- =============================================================================
-- TABELLA: deadline_utenti
-- =============================================================================
CREATE TABLE IF NOT EXISTS deadline_utenti (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    calendario_id INTEGER NOT NULL REFERENCES calendari(id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    deadline      TEXT    NOT NULL,
    UNIQUE(calendario_id, user_id)
);

-- =============================================================================
-- TABELLA: desiderata
-- =============================================================================
CREATE TABLE IF NOT EXISTS desiderata (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    calendario_id     INTEGER NOT NULL REFERENCES calendari(id) ON DELETE CASCADE,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    giorno            INTEGER NOT NULL CHECK(giorno BETWEEN 1 AND 31),
    tipo_richiesta_id INTEGER REFERENCES tipi_richiesta(id),
    note              TEXT    DEFAULT NULL,
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_by        INTEGER REFERENCES users(id),
    UNIQUE(calendario_id, user_id, giorno)
);

-- =============================================================================
-- TABELLA: working_desiderata
-- =============================================================================
CREATE TABLE IF NOT EXISTS working_desiderata (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    calendario_id     INTEGER NOT NULL REFERENCES calendari(id) ON DELETE CASCADE,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    giorno            INTEGER NOT NULL CHECK(giorno BETWEEN 1 AND 31),
    tipo_richiesta_id INTEGER REFERENCES tipi_richiesta(id),
    note              TEXT    DEFAULT NULL,
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_by        INTEGER REFERENCES users(id),
    UNIQUE(calendario_id, user_id, giorno)
);

-- =============================================================================
-- TABELLA: assegnazioni_turni
-- turno_id → calendario_turni.id (FK per-calendario)
-- =============================================================================
CREATE TABLE IF NOT EXISTS assegnazioni_turni (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    calendario_id    INTEGER NOT NULL REFERENCES calendari(id) ON DELETE CASCADE,
    turno_id         INTEGER NOT NULL REFERENCES calendario_turni(id) ON DELETE CASCADE,
    giorno           INTEGER NOT NULL CHECK(giorno BETWEEN 1 AND 31),
    user_id          INTEGER REFERENCES users(id),
    originale_user_id INTEGER DEFAULT NULL,
    forza_inserimento INTEGER NOT NULL DEFAULT 0,
    forza_note       TEXT    DEFAULT NULL,
    conflitto        TEXT    NOT NULL DEFAULT 'free'
                         CHECK(conflitto IN
                             ('free','match','mismatch','forced',
                              'notte_same','notte_rest','empty')),
    conflitti        TEXT    NOT NULL DEFAULT '[]',
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_by       INTEGER REFERENCES users(id),
    UNIQUE(calendario_id, turno_id, giorno)
);

-- =============================================================================
-- TABELLA: history
-- =============================================================================
CREATE TABLE IF NOT EXISTS history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    calendario_id    INTEGER NOT NULL REFERENCES calendari(id) ON DELETE CASCADE,
    step             INTEGER NOT NULL,
    tabella          TEXT    NOT NULL,
    record_id        INTEGER NOT NULL,
    dati_precedenti  TEXT    NOT NULL,
    dati_nuovi       TEXT    NOT NULL,
    timestamp        TEXT    NOT NULL DEFAULT (datetime('now')),
    user_id          INTEGER REFERENCES users(id),
    UNIQUE(calendario_id, step)
);

-- =============================================================================
-- TABELLA: history_ptr
-- =============================================================================
CREATE TABLE IF NOT EXISTS history_ptr (
    calendario_id INTEGER PRIMARY KEY REFERENCES calendari(id) ON DELETE CASCADE,
    current_step  INTEGER NOT NULL DEFAULT 0,
    max_step      INTEGER NOT NULL DEFAULT 0
);

-- =============================================================================
-- TABELLA: wd_history  (history parallela per working_desiderata)
-- =============================================================================
CREATE TABLE IF NOT EXISTS wd_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    calendario_id    INTEGER NOT NULL REFERENCES calendari(id) ON DELETE CASCADE,
    step             INTEGER NOT NULL,
    tabella          TEXT    NOT NULL,
    record_id        INTEGER NOT NULL,
    dati_precedenti  TEXT    NOT NULL,
    dati_nuovi       TEXT    NOT NULL,
    timestamp        TEXT    NOT NULL DEFAULT (datetime('now')),
    user_id          INTEGER REFERENCES users(id),
    UNIQUE(calendario_id, step)
);

-- =============================================================================
-- TABELLA: wd_history_ptr
-- =============================================================================
CREATE TABLE IF NOT EXISTS wd_history_ptr (
    calendario_id INTEGER PRIMARY KEY REFERENCES calendari(id) ON DELETE CASCADE,
    current_step  INTEGER NOT NULL DEFAULT 0,
    max_step      INTEGER NOT NULL DEFAULT 0
);

-- =============================================================================
-- TABELLA: config
-- =============================================================================
CREATE TABLE IF NOT EXISTS config (
    chiave      TEXT PRIMARY KEY,
    valore      TEXT NOT NULL,
    descrizione TEXT
);

-- =============================================================================
-- DATI DEFAULT — config
-- =============================================================================
INSERT OR IGNORE INTO config (chiave, valore, descrizione) VALUES
    ('max_history_steps', '500',  'Numero massimo step history per calendario'),
    ('ore_giornaliere',   '6.5',  'Ore lavorative giornaliere default (decimale)'),
    ('conteggi_context',  '[{"id":"notti","label":"Notti","flag_nome":"notturno","giorno_settimana":null,"negato":false,"attivo":true},{"id":"notti_sab","label":"Notti Sab","flag_nome":"notturno","giorno_settimana":6,"negato":false,"attivo":true},{"id":"notti_dom","label":"Notti Dom","flag_nome":"notturno","giorno_settimana":0,"negato":false,"attivo":true},{"id":"no_notti_sab","label":"Turni Sab","flag_nome":"notturno","giorno_settimana":6,"negato":true,"attivo":true},{"id":"no_notti_dom","label":"Turni Dom","flag_nome":"notturno","giorno_settimana":0,"negato":true,"attivo":true}]', 'Conteggi visibili nel context menu lavoratore (JSON)'),
    ('modalita_ordinamento_desiderata', 'alfabetico_intragruppo', 'Modalità ordinamento foglio desiderata: manuale | alfabetico_globale | alfabetico_intragruppo'),
    ('giorni_lavorativi_settimana', '0,1,2,3,4,5',
     'Giorni della settimana lavorativi (0=lunedi .. 6=domenica)'),
    ('versione',          '4.0',  'Versione schema database');

-- =============================================================================
-- DATI DEFAULT — tipi richiesta (globali, senza preset)
-- =============================================================================
-- I tipi richiesta di serie li inserisce la migrazione all'avvio, da
-- TIPI_RICHIESTA_DEFAULT in app/__init__.py: una sorgente sola.

-- =============================================================================
-- TABELLA: sovragruppi
-- Livello 1 della gerarchia turni. Raggruppa i gruppi per unità organizzativa.
-- =============================================================================
CREATE TABLE IF NOT EXISTS sovragruppi (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    preset_id INTEGER NOT NULL REFERENCES struttura_presets(id) ON DELETE CASCADE,
    sigla     TEXT    NOT NULL,
    nome      TEXT    NOT NULL,
    ambito    TEXT    NOT NULL DEFAULT '',
    ordine    INTEGER NOT NULL DEFAULT 0,
    ordine_desiderata INTEGER DEFAULT NULL,  -- override ordine per viste desiderata (NULL = usa "ordine")
    style     TEXT    NOT NULL DEFAULT '{}'
);

-- =============================================================================
-- TABELLA: gruppi
-- Livello 2 della gerarchia turni. Un gruppo E' l'insieme dei turni di una
-- stessa fascia oraria dentro una stessa struttura, quindi la coppia
-- (sovragruppo_id, flag_id) e' unica: la mattina di un reparto si definisce
-- una volta sola.
--
-- L'indice che lo impone e' creato da app/__init__.py e non qui, perche' su
-- un tenant con duplicati preesistenti fallirebbe abortendo l'intero schema.
-- =============================================================================
CREATE TABLE IF NOT EXISTS gruppi (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sovragruppo_id INTEGER NOT NULL REFERENCES sovragruppi(id) ON DELETE CASCADE,
    sigla          TEXT    NOT NULL,
    nome           TEXT    NOT NULL,
    flag_id        INTEGER REFERENCES flag_turno(id),
    ordine         INTEGER NOT NULL DEFAULT 0,
    style          TEXT    NOT NULL DEFAULT '{}'
);

-- =============================================================================
-- TABELLA: preset_turni
-- Livello 3 della gerarchia turni. I singoli turni dentro un gruppo.
-- =============================================================================
CREATE TABLE IF NOT EXISTS preset_turni (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    gruppo_id        INTEGER NOT NULL REFERENCES gruppi(id) ON DELETE CASCADE,
    sigla            TEXT    NOT NULL,
    nome             TEXT    NOT NULL DEFAULT '',
    ordine           INTEGER NOT NULL DEFAULT 0,
    style            TEXT    NOT NULL DEFAULT '{}',
    priorita_solver  TEXT    NOT NULL DEFAULT 'automatico'
                         CHECK(priorita_solver IN ('indispensabile','automatico','manuale')),
    peso_priorita_solver      INTEGER NOT NULL DEFAULT 50,
    apri_festivi      INTEGER NOT NULL DEFAULT 0,
    apri_superfestivi INTEGER NOT NULL DEFAULT 0,
    is_disabled       INTEGER NOT NULL DEFAULT 0,  -- turno disattivato (non inseribile)
    is_hidden         INTEGER NOT NULL DEFAULT 0   -- turno nascosto (implica disattivato)
);

-- =============================================================================
-- TABELLA: tipi_qualitativo
-- Criterio QUALITATIVO: classifica i turni in base all'attività svolta.
-- Globale (un set per tenant).
-- =============================================================================
CREATE TABLE IF NOT EXISTS tipi_qualitativo (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nome           TEXT    NOT NULL UNIQUE,
    descrizione    TEXT    NOT NULL DEFAULT '',
    carico_lavoro  INTEGER NOT NULL DEFAULT 0,
    ordine         INTEGER NOT NULL DEFAULT 0,
    is_active      INTEGER NOT NULL DEFAULT 1
);

-- =============================================================================
-- TABELLA: preset_turni_qualitativo
-- Relazione M:N tra turni e criteri qualitativi.
-- =============================================================================
CREATE TABLE IF NOT EXISTS preset_turni_qualitativo (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    preset_turno_id     INTEGER NOT NULL REFERENCES preset_turni(id) ON DELETE CASCADE,
    tipo_qualitativo_id INTEGER NOT NULL REFERENCES tipi_qualitativo(id) ON DELETE CASCADE,
    UNIQUE(preset_turno_id, tipo_qualitativo_id)
);

-- =============================================================================
-- TABELLA: regole_conflitto
-- Regole configurabili per conflitti turni. Globali (un set per tenant).
--
-- tipo_regola:
--   'tipo_vs_tipo'                  — conflitto turno A vs turno B
--   'desiderata_mismatch'           — flag richiesto ≠ flag assegnato
--   'desiderata_assenza_mismatch'   — assegnato con richiesta assenza
--
-- Match per flag con risalita gerarchia parent (max 2 livelli):
--   flag_a_id/flag_b_id = NULL → qualsiasi turno
-- =============================================================================
CREATE TABLE IF NOT EXISTS regole_conflitto (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                TEXT    NOT NULL,
    tipo_regola         TEXT    NOT NULL CHECK(tipo_regola IN (
                            'tipo_vs_tipo',
                            'desiderata_mismatch',
                            'desiderata_assenza_mismatch'
                        )),
    flag_a_id           INTEGER REFERENCES flag_turno(id),
    flag_b_id           INTEGER REFERENCES flag_turno(id),
    offset_giorni       INTEGER NOT NULL DEFAULT 0,
    categoria           TEXT    NOT NULL DEFAULT 'consigliata',
    stile               TEXT    NOT NULL DEFAULT '{"backgroundColor":"#fff3cd","color":"#856404"}',
    blocca_inserimento  INTEGER NOT NULL DEFAULT 0,
    peso_numerico       REAL    NOT NULL DEFAULT 1.0,
    is_active           INTEGER NOT NULL DEFAULT 1
);

-- =============================================================================
-- DATI DEFAULT — regole conflitto
-- Vengono inserite dalla migrazione in app/__init__.py per poter risolvere
-- le FK ai flag_turno con subquery dopo che le colonne esistono.
-- =============================================================================

-- =============================================================================
-- TABELLA: style_history
-- Storico delle modifiche di formattazione (per undo).
-- =============================================================================
CREATE TABLE IF NOT EXISTS style_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contesto    TEXT    NOT NULL,
    contesto_id INTEGER NOT NULL,
    items       TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- =============================================================================
-- TABELLA: vincoli_globali
-- Vincoli per il solver automatico turni (key-value, simile a config).
-- =============================================================================
CREATE TABLE IF NOT EXISTS vincoli_globali (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chiave      TEXT NOT NULL UNIQUE,
    valore      TEXT NOT NULL,
    descrizione TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1
);

-- Vincoli globali default
INSERT OR IGNORE INTO vincoli_globali (chiave, valore, descrizione) VALUES
    ('max_giorni_consecutivi', '6',  'Max giorni lavorativi consecutivi'),
    ('max_turni_giorno',       '1',  'Max turni per persona al giorno'),
    ('max_ore_mese',           '0',  'Max ore mese (0=illimitato)'),
    ('max_festivi_mese',       '4',  'Max turni in giorni festivi al mese'),
    ('max_n_turni_mese',       '0',  'Offset turni/mese rispetto a turni dovuti (0=esatto, +N/-N)');

-- =============================================================================
-- TABELLA: vincoli_utente
-- Override per-utente dei vincoli globali.
-- =============================================================================
CREATE TABLE IF NOT EXISTS vincoli_utente (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chiave  TEXT NOT NULL,
    valore  TEXT NOT NULL,
    note    TEXT,
    UNIQUE(user_id, chiave)
);

-- =============================================================================
-- TABELLA: solver_esecuzioni
-- Log delle esecuzioni del solver automatico.
-- =============================================================================
CREATE TABLE IF NOT EXISTS solver_esecuzioni (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    calendario_id   INTEGER NOT NULL REFERENCES calendari(id) ON DELETE CASCADE,
    stato           TEXT NOT NULL DEFAULT 'completato',
    celle_totali    INTEGER NOT NULL DEFAULT 0,
    celle_riempite  INTEGER NOT NULL DEFAULT 0,
    celle_fallite   INTEGER NOT NULL DEFAULT 0,
    dettaglio       TEXT NOT NULL DEFAULT '[]',
    durata_ms       INTEGER,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- =============================================================================
-- TABELLA: vincoli_solver
-- Vincoli solver basati su flag turno o tipo qualitativo.
-- Limita il numero massimo di turni al mese per un dato flag o tipo.
-- Multi-entry: si possono avere più vincoli con flag/tipo diversi.
-- =============================================================================
CREATE TABLE IF NOT EXISTS vincoli_solver (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo        TEXT NOT NULL CHECK(tipo IN ('flag','qualitativo')),
    ref_id      INTEGER NOT NULL,
    max_n       INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1,
    descrizione TEXT,
    UNIQUE(tipo, ref_id)
);

-- =============================================================================
-- TABELLA: vincoli_solver_utente
-- Override per-utente dei vincoli solver (flag/tipo qualitativo).
-- =============================================================================
CREATE TABLE IF NOT EXISTS vincoli_solver_utente (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tipo    TEXT NOT NULL CHECK(tipo IN ('flag','qualitativo')),
    ref_id  INTEGER NOT NULL,
    max_n   INTEGER NOT NULL DEFAULT 0,
    note    TEXT,
    UNIQUE(user_id, tipo, ref_id)
);

-- =============================================================================
-- TABELLA: manager_accesso_utenti
-- Restrizioni accesso manager→utenti. Se un manager ha righe in questa tabella,
-- può gestire SOLO gli utenti elencati. Nessuna riga = accesso completo.
-- =============================================================================
CREATE TABLE IF NOT EXISTS manager_accesso_utenti (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(manager_id, user_id)
);

-- =============================================================================
-- TABELLA: manager_accesso_turni
-- Restrizioni accesso manager→turni (preset). Se un manager ha righe in questa
-- tabella, può gestire SOLO i turni elencati. Nessuna riga = accesso completo.
-- =============================================================================
CREATE TABLE IF NOT EXISTS manager_accesso_turni (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    preset_turno_id INTEGER NOT NULL REFERENCES preset_turni(id) ON DELETE CASCADE,
    UNIQUE(manager_id, preset_turno_id)
);

-- =============================================================================
-- TABELLA: preset_esclusioni_turno_per_utente
-- Esclusione di un utente da un turno, gruppo o sovragruppo specifico del preset.
-- Usata dal solver e snapshotata nel config_snapshot del calendario.
-- =============================================================================
CREATE TABLE IF NOT EXISTS preset_esclusioni_turno_per_utente (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    preset_id  INTEGER NOT NULL REFERENCES struttura_presets(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tipo       TEXT    NOT NULL CHECK(tipo IN ('turno', 'gruppo', 'sovragruppo')),
    target_id  INTEGER NOT NULL,
    eccezioni  TEXT    NOT NULL DEFAULT '[]',  -- JSON array di target_id figli esenti
    UNIQUE(preset_id, user_id, tipo, target_id)
);

-- =============================================================================
-- TABELLA: posti_fissi
-- Template di assegnazioni ricorrenti (es. "ogni giovedì, turno RM_POM → utente X").
-- Associati al preset struttura, riutilizzabili tra calendari diversi.
-- =============================================================================
CREATE TABLE IF NOT EXISTS posti_fissi (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    preset_id        INTEGER NOT NULL REFERENCES struttura_presets(id) ON DELETE CASCADE,
    manager_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nome             TEXT    NOT NULL DEFAULT '',
    preset_turno_id  INTEGER NOT NULL REFERENCES preset_turni(id) ON DELETE CASCADE,
    giorno_settimana INTEGER NOT NULL CHECK(giorno_settimana BETWEEN 0 AND 6),
    -- 0=Lunedì … 6=Domenica (Python weekday)
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    created_by       INTEGER REFERENCES users(id),
    UNIQUE(preset_id, preset_turno_id, giorno_settimana, manager_id)
);

-- =============================================================================
-- TABELLA: posti_fissi_utenti
-- Pool di utenti per ogni posto fisso (round-robin per rotazione equa).
-- =============================================================================
CREATE TABLE IF NOT EXISTS posti_fissi_utenti (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    posto_fisso_id INTEGER NOT NULL REFERENCES posti_fissi(id) ON DELETE CASCADE,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ordine         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(posto_fisso_id, user_id)
);

-- =============================================================================
-- TABELLA: preset_ottimizzazione
-- Preset configurabili per l'optimizer (cost function pesata).
-- Tipi: completo (bilancia tutto), per_flag (bilancia flag specifico),
--        per_parametro (bilancia ore/festivi), personalizzato (pesi liberi).
-- ref_id → flag_turno.id per tipo=per_flag (es. notturno, mattina).
-- =============================================================================
CREATE TABLE IF NOT EXISTS preset_ottimizzazione (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT    NOT NULL UNIQUE,
    tipo        TEXT    NOT NULL CHECK(tipo IN ('completo','per_flag','per_parametro','personalizzato')),
    ref_id      INTEGER DEFAULT NULL REFERENCES flag_turno(id),
    pesi        TEXT    NOT NULL DEFAULT '{}',
    is_default  INTEGER NOT NULL DEFAULT 0,
    ordine      INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1
);

-- Preset default
INSERT OR IGNORE INTO preset_ottimizzazione (nome, tipo, ref_id, pesi, is_default, ordine) VALUES
    ('Bilancia completo', 'completo', NULL,
     '{"ore":1.0,"target":1.0,"festivi":1.0,"peso":1.0,"varieta":1.0,"desiderata":1.0}', 1, 10);
INSERT OR IGNORE INTO preset_ottimizzazione (nome, tipo, ref_id, pesi, is_default, ordine) VALUES
    ('Bilancia notti', 'per_flag', (SELECT id FROM flag_turno WHERE nome='notturno'),
     '{"ore":0.5,"target":3.0,"festivi":0.5,"peso":0.5,"varieta":0.5,"desiderata":0.5}', 1, 20);
INSERT OR IGNORE INTO preset_ottimizzazione (nome, tipo, ref_id, pesi, is_default, ordine) VALUES
    ('Bilancia ore', 'per_parametro', NULL,
     '{"ore":3.0,"target":0.5,"festivi":0.5,"peso":1.0,"varieta":0.5,"desiderata":0.5}', 1, 30);
INSERT OR IGNORE INTO preset_ottimizzazione (nome, tipo, ref_id, pesi, is_default, ordine) VALUES
    ('Bilancia festivi', 'per_parametro', NULL,
     '{"ore":0.5,"target":0.5,"festivi":3.0,"peso":0.5,"varieta":0.5,"desiderata":0.5}', 1, 40);

-- =============================================================================
-- UTENTE ADMIN DEFAULT
-- Password: Admin2024! — CAMBIARE IMMEDIATAMENTE AL PRIMO AVVIO
--
-- Posizionato a fine file: la tabella users ha una FK a sovragruppi
-- (sovragruppo_id), e su fresh init via executescript con FK ON, l'INSERT
-- fallirebbe se sovragruppi non e' stata ancora creata.
-- =============================================================================
-- Account admin del tenant. Il nome distingue questo livello dall'admin di
-- piattaforma (superadmin, in master_users): vedi la sezione "Role hierarchy"
-- in CLAUDE.md. Password di sviluppo uguale allo username, da cambiare.
INSERT OR IGNORE INTO users (username, password_hash, role, sigla) VALUES
    ('admin_uo',
     '$2b$12$viq/F2pPWIK20e4lrq8gROG2wxBnIM0xbTi//pLIfRo1P78gAPbC.',
     'admin',
     'AUO');

