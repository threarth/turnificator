-- ============================================================
-- init_master_db.sql — Schema del database master (multi-tenant)
--
-- Contiene: registro tenant, utenti master admin, template
-- configurazione, audit log impersonation.
-- Tutte le istruzioni sono idempotenti (IF NOT EXISTS / OR IGNORE).
-- ============================================================

-- -----------------------------------------------------------
-- Tenant: registro delle organizzazioni
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT    NOT NULL UNIQUE,
    nome            TEXT    NOT NULL,
    db_filename     TEXT    NOT NULL UNIQUE,
    is_active       INTEGER NOT NULL DEFAULT 1,
    visibile_login  INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------
-- Master users: utenti con ruolo master_admin
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS master_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK(role IN ('master_admin')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------
-- Template: strutture configurazione riutilizzabili
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT    NOT NULL UNIQUE,
    descrizione TEXT    NOT NULL DEFAULT '',
    db_filename TEXT    NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------
-- Configurazione globale master
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS master_config (
    chiave      TEXT PRIMARY KEY,
    valore      TEXT NOT NULL,
    descrizione TEXT NOT NULL DEFAULT ''
);

-- Seed: dropdown login attivo di default
INSERT OR IGNORE INTO master_config (chiave, valore, descrizione)
VALUES ('dropdown_login_attivo', '1', 'Se 1, la pagina login mostra un dropdown con i tenant visibili. Se 0, campo slug testuale.');

-- -----------------------------------------------------------
-- Audit log: impersonation master → tenant
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS impersonation_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    master_user_id  INTEGER NOT NULL REFERENCES master_users(id),
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    azione          TEXT    NOT NULL,
    dettaglio       TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
