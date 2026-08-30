# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git Workflow

Dopo ogni modifica completata, **chiedi conferma all'utente** prima di fare commit e push. Non committare automaticamente. Il flusso è:
1. Completa la modifica e verifica che il build passi
2. Chiedi all'utente: "Vuoi che faccia commit e push?"
3. Solo dopo conferma: commit con messaggio descrittivo + push su `origin/main`


## Project Overview

**Turnificator9000** — a shift scheduling web application for healthcare workers. Workers submit monthly shift preferences (*desiderata*), which admins/managers use to build shift rosters. The codebase is Italian (variables, comments, UI strings are all in Italian).

## Commands

### Backend (Python/Flask)
```bash
# First-time setup: create .env from .env.example, then install deps
pip install -r requirements.txt

# Build a clean demo installation from scratch (DESTRUCTIVE: wipes master.db,
# the tenant DB and the template). Seeds a fictional hospital, fictional
# departments and demo users. Schema comes from migrations/*.sql, which are
# re-applied idempotently on every startup — there are no .py migrations.
python seed_demo.py

# Run development server
python run.py

# Production — i WebSocket richiedono il worker gevent e un solo processo
gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
         -w 1 -b 0.0.0.0:5000 "app:create_app()"
```

### Frontend (SvelteKit)
```bash
cd frontend
npm install

# Dev server (proxies API calls to Flask on :5000)
npm run dev

# Build SPA → outputs to ../static/ (served by Flask)
npm run build

# Test della logica pura estratta dai componenti (runner incluso in Node)
npm test
```

The frontend build output lands in `static/` at the project root, which Flask serves. In production, only Flask needs to run.

`static/` is build output and is **not versioned**: after a fresh clone `npm run build` is mandatory, otherwise Flask has no frontend to serve. The build wipes and regenerates the whole directory.

### SQLCipher
No system dependency: `requirements.txt` uses `sqlcipher3-wheels`, which ships
SQLCipher already compiled for Windows, macOS and Linux. Only on
Python/platform combinations without a wheel (see the table in `README.md`)
switch to `sqlcipher3` and install `libsqlcipher-dev` / `brew install sqlcipher`
first.

## Architecture

### Dual-server dev, single-server prod
- **Dev**: Vite dev server (frontend) + Flask (backend) run separately
- **Prod**: `npm run build` compiles SPA to `static/`; Flask serves `static/index.html` at `/` and all API routes under `/api/`

### Backend: Flask Application Factory
`app/__init__.py` → `create_app()` registers six blueprints and runs `init_db()` on startup:

| Blueprint | Prefix | Roles |
|---|---|---|
| `routes/auth.py` | `/api/auth` | public |
| `routes/master.py` | `/api/master` | `master_admin` |
| `routes/admin.py` | `/api/admin` | `admin` |
| `routes/manager.py` | `/api/manager` | `admin`, `manager` |
| `routes/basic.py` | `/api/basic` | all roles |
| `routes/export.py` | `/api/export` | `admin`, `manager` |

### Authentication
- JWT via `flask-jwt-extended`. Token stored in `localStorage` on client.
- `app/auth.py` provides:
  - `require_role(*roles)` — decorator combining `@jwt_required()` + role check
  - `get_current_user()` — resolves JWT identity to DB user record
  - `hash_password()` / `autentica_utente()` — bcrypt-based

### Database
- **SQLCipher** (AES-256 encrypted SQLite). Key set via `DATABASE_KEY` env var.
- `app/db.py` provides `get_db()` (per-request connection via Flask `g`), `query_one()`, `query_all()`, `execute_write()`, `execute_many()`.
- Schema initialized idempotently from `migrations/init_db.sql` every startup.

### Role hierarchy

Two distinct authority levels, deliberately named apart to avoid confusion:

| Level | Where | Username | Can do |
|---|---|---|---|
| `master_admin` | `master.db` / `master_users` | `superadmin` | **Top of the hierarchy.** Create/disable tenants, manage templates, reset any tenant admin's password, impersonate a tenant admin (logged in `impersonation_log` + notified to the tenant) |
| `admin` | `tenants/*.db` / `users` | `admin_uo` | Full authority **inside its own tenant** only: structure, calendars, users. No visibility across tenants |
| `manager` | `tenants/*.db` / `users` | — | Shift assignments, working desiderata (subject to access whitelist) |
| `basic` | `tenants/*.db` / `users` | — | Own desiderata only |

The master admin logs in via `/api/master/login` and is guarded by `require_master_role()`; tenant roles use `require_role(*roles)`.

- Dev credentials: every seeded account uses `password == username` (`superadmin`/`superadmin`, `admin_uo`/`admin_uo`). **Development only — regenerate before any production use.**

### Data Model (key tables)
- **3-tier shift hierarchy**: `sovragruppi` → `gruppi` (type: mattina/pomeriggio/notte/altro) → `turni`
- **Calendar lifecycle**: `BOZZA` → `APERTO` → `CHIUSO` → `ARCHIVIATO`
- **Desiderata flow**: Workers submit `desiderata` → admin freezes → creates `working_desiderata` (editable copy for managers)
- **`assegnazioni_turni`**: actual shift assignments; `user_id=NULL` means uncovered shift; `conflitto` field encodes cell color (`free`, `match`, `mismatch`, `forced`, `notte_same`, `notte_rest`, `empty`)
- **History/undo-redo**: `history` + `history_ptr` tables per calendar; capped at `MAX_HISTORY_STEPS` (default 500)

### Business Rules (`app/services/validatori.py`)
- **Absolute** (non-bypassable): night shift cannot coexist with other shifts same day (`notte_same`); mandatory rest day after night shift (`notte_rest`)
- **Bypassable** with `forza_inserimento=True`: worker has a `notWorking` desiderata request

### Frontend (SvelteKit + Bootstrap 5)
- Static adapter → outputs SPA to `../static/`
- Auth state in Svelte stores (`frontend/src/lib/auth.js`): `user`, `token` persisted to `localStorage`
- All API calls via `frontend/src/lib/api.js` which attaches `Authorization: Bearer <token>` header and handles 401 → redirect to `/login`
- Routes: `/` (home), `/login`, `/basic`, `/manager`, `/admin`, `/manuale`, `/master` (+ `/master/templates`, `/master/audit`, `/master/config`)

### Hour Calculation (`app/services/ore.py`)
- Worked hours: from `assegnazioni_turni`
- Justified hours: from `working_desiderata` where `tipi_richiesta.tipo='notWorking'` AND `counting_flag=1` (ROMC with `counting_flag=0` does NOT count)
- Export to `.xlsx` via `openpyxl` (`app/routes/export.py`)
