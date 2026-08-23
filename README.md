# Turnificator9000

Pianificatore di turni per personale sanitario. I lavoratori inseriscono le
proprie preferenze mensili (*desiderata*); admin e manager le usano per
costruire la griglia dei turni, manualmente o con il solver.

Applicazione **multi-tenant**: ogni unità operativa ha il proprio database
SQLCipher cifrato, senza alcuna query cross-tenant.

> Il codice è in italiano — variabili, commenti, stringhe UI. Mantenere la
> stessa lingua nelle modifiche.

---

## Requisiti

| | |
|---|---|
| Python | **3.12 consigliato** (3.11+ supportato) |
| Node | **18+ — obbligatorio** |

Node non e' opzionale: `static/` e' output di build e **non e' versionata**.
Senza `npm run build` non esiste frontend da servire e l'app risponde con una
pagina vuota.

Nessuna dipendenza di sistema da installare. `sqlcipher3-wheels` contiene
SQLCipher gia' compilato dentro il wheel, quindi **non** servono
`libsqlcipher-dev` (Linux) ne' `brew install sqlcipher` (macOS).

Perche' Python 3.12: e' l'unica versione con wheel disponibile su tutte le
piattaforme.

| | 3.11 | 3.12 | 3.13 | 3.14 |
|---|---|---|---|---|
| macOS Apple Silicon | si | si | si | si |
| macOS Intel | si | si | no | no |
| Linux x86_64 | si | si | si | no |
| Windows x64 | si | si | si | si |

Sulle combinazioni senza wheel serve compilare: installare la libreria di
sistema (`sudo apt-get install libsqlcipher-dev` oppure
`brew install sqlcipher`) e sostituire `sqlcipher3-wheels` con `sqlcipher3`
in `requirements.txt`.

Dipendenze Python (`requirements.txt`):
`Flask` · `flask-jwt-extended` · `sqlcipher3-wheels` · `bcrypt` · `openpyxl` ·
`weasyprint` · `python-dotenv` · `flask-socketio` · `gevent` ·
`gevent-websocket`. Per i test: `requirements-dev.txt` aggiunge `pytest`.

---

## Setup

Dal repository a un'applicazione funzionante. I passi sono gli stessi su ogni
sistema; cambiano solo i comandi del virtualenv.

> `npm run build` cancella e rigenera `static/` da zero: e' output di build,
> non e' versionata, e va rigenerata dopo ogni `git clone`.

### macOS e Linux

```bash
# 0. Codice
git clone https://github.com/threarth/turnificator.git
cd turnificator

# 1. Configurazione: copiare ENTRAMBI i file di esempio
cp .env.example .env
cp tenant_keys.json.example tenant_keys.json

# 2. Virtualenv e dipendenze Python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt

# 3. Frontend — OBBLIGATORIO, genera static/
cd frontend && npm install && npm run build && cd ..

# 4. Installazione demo — DISTRUTTIVO: azzera i database
#    Chiede conferma: scrivere RICOSTRUISCI
python seed_demo.py

# 5. Avvio
python run.py
```

Poi aprire **http://localhost:5000**.

### Windows (PowerShell)

```powershell
# 0. Codice
git clone https://github.com/threarth/turnificator.git
cd turnificator

# 1. Configurazione: copiare ENTRAMBI i file di esempio
Copy-Item .env.example .env
Copy-Item tenant_keys.json.example tenant_keys.json

# 2. Virtualenv e dipendenze Python
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# 3. Frontend — OBBLIGATORIO, genera static\
cd frontend
npm install
npm run build
cd ..

# 4. Installazione demo — DISTRUTTIVO: azzera i database
#    Chiede conferma: scrivere RICOSTRUISCI
python seed_demo.py

# 5. Avvio
python run.py
```

Poi aprire **http://localhost:5000**.

Se `Activate.ps1` viene bloccato dalla policy di esecuzione:

```powershell
Set-ExecutionPolicy -Scope Process RemoteSigned
```

### Le chiavi del passo 1

I due file copiati contengono segnaposto che vanno **tutti** sostituiti con
valori casuali. Ne servono cinque:

| File | Campo |
|---|---|
| `.env` | `SECRET_KEY` |
| `.env` | `MASTER_DB_KEY` |
| `.env` | `JWT_SECRET_KEY` |
| `tenant_keys.json` | `default` |
| `tenant_keys.json` | `_template_base` |

Per generarne una (`python3` su macOS e Linux, `python` su Windows):

```
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

> Le due chiavi di `tenant_keys.json` cifrano i database. Se le perdi dopo
> aver inserito dati, i dati sono **irrecuperabili**: non esiste recupero.
> Entrambi i file sono in `.gitignore` — non devono mai essere committati.

### Accessi della demo

`seed_demo.py` crea un ospedale fittizio con 3 reparti, 7 gruppi, 24 turni e
17 utenti. **Le password coincidono con lo username**: l'app mostra un avviso
finche' non vengono cambiate, e vanno rigenerate prima di qualunque uso reale.

| Ruolo | Utente | Dove |
|---|---|---|
| Piattaforma | `superadmin` | pagina `/master`, form dedicato |
| Admin unita' operativa | `admin_uo` | login normale, organizzazione `default` |
| Manager | `rossi` | login normale, organizzazione `default` |
| Lavoratore | `conti` | login normale, organizzazione `default` |

### Sviluppo vs produzione

| | Comando | Note |
|---|---|---|
| Dev | `npm run dev` + `python run.py` | Vite (5173) fa da proxy verso Flask (5000) |
| Prod | `npm run build` + `gunicorn` | Il build finisce in `static/`, servito da Flask |

```bash
gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"
```

In produzione gira **solo** Flask: serve `static/index.html` su `/` e le API
sotto `/api/`.

---

## Configurazione (`.env`)

Nessun segreto va nel codice sorgente. `.env` è escluso da git.

| Variabile | Ruolo |
|---|---|
| `SECRET_KEY` | Chiave Flask (sessioni, CSRF) |
| `MASTER_DB_PATH` | Percorso del master DB (default `master.db`) |
| `MASTER_DB_KEY` | Chiave AES-256 del master DB |
| `TENANT_DB_DIR` | Directory dei DB tenant (default `tenants/`) |
| `TEMPLATE_DB_DIR` | Directory dei template (default `templates/`) |
| `TENANT_KEYS_PATH` | JSON con le chiavi per tenant (default `tenant_keys.json`) |
| `JWT_SECRET_KEY` | Firma dei token JWT |
| `JWT_ACCESS_TOKEN_EXPIRES` | Durata token in secondi (default 3600) |
| `MAX_HISTORY_STEPS` | Cap degli step di undo per calendario (default 500) |
| `ORE_GIORNALIERE_DEFAULT` | Ore giornaliere decimali (default 6.5) |
| `FLASK_DEBUG` | `0` in produzione |

`tenant_keys.json` associa a ogni tenant la sua chiave di cifratura, e ne
contiene una anche per ciascun template (prefisso underscore):

```json
{
  "default": "<chiave del tenant>",
  "_template_base": "<chiave del template>"
}
```

> Perdere questo file significa **perdere i dati**: senza la chiave un
> database SQLCipher è irrecuperabile. È in `.gitignore` — verificare che
> ci resti, e conservarne una copia al sicuro.

---

## Architettura

### Backend — Flask application factory

`app/__init__.py` → `create_app()` registra sei blueprint ed esegue
`init_db()` all'avvio.

| Blueprint | Prefisso | Ruoli |
|---|---|---|
| `routes/auth.py` | `/api/auth` | pubblico |
| `routes/master.py` | `/api/master` | `master_admin` |
| `routes/admin.py` | `/api/admin` | `admin` (molte rotte anche `manager`) |
| `routes/manager.py` | `/api/manager` | `admin`, `manager` |
| `routes/basic.py` | `/api/basic` | tutti i ruoli |
| `routes/export.py` | `/api/export` | `admin`, `manager` |

### Gerarchia dei ruoli

| Livello | Dove | Può |
|---|---|---|
| `master_admin` | `master.db` / `master_users` | **Vertice.** Creare e disattivare tenant, gestire template, resettare la password di qualsiasi admin, impersonare un tenant |
| `admin` | `tenants/*.db` / `users` | Autorità piena **dentro il proprio tenant**: struttura, calendari, utenti. Nessuna visibilità sugli altri |
| `manager` | `tenants/*.db` / `users` | Assegnazioni turni e working desiderata, soggetto alla whitelist di accesso |
| `basic` | `tenants/*.db` / `users` | Solo i propri desiderata |

Il master admin entra da `/api/master/auth/login` ed è protetto da
`require_master_role()`; i ruoli tenant usano `require_role(*roles)`.
L'impersonation è tracciata in `impersonation_log` e notificata al tenant.

### Autenticazione

- JWT (`flask-jwt-extended`), token in `localStorage`.
- Il claim `tenant` nel JWT determina **quale database** viene aperto: il
  middleware `_resolve_tenant` popola `g.tenant_slug`, e `get_db()` risolve la
  connessione da lì. Senza contesto tenant, `get_db()` solleva `RuntimeError`.
- `app/auth.py`: `require_role(*roles)`, `require_master_role()`,
  `get_current_user()`, `hash_password()` (bcrypt cost 12),
  `authenticate_user()`, `authenticate_master()`.
- Quattro handler JWT registrati in `app/__init__.py` restituiscono 401 con
  JSON invece del 500 di default.

### Database

- **SQLCipher** (SQLite cifrato AES-256), un file per tenant.
- `app/db.py`: `get_db()` (connessione per-richiesta via `g`), `query_one()`,
  `query_all()`, `execute_write()`, `execute_many()`, `get_master_db()`.
- Lo schema vive in `migrations/init_db.sql` e `migrations/init_master_db.sql`,
  **riapplicati idempotentemente a ogni avvio**.

> **Non esistono migrazioni `.py`.** Ogni evoluzione di schema va messa in
> `init_db.sql` (con `CREATE TABLE IF NOT EXISTS` / `INSERT OR IGNORE`) oppure
> in una funzione `_migrate_*` dentro `app/db.py`, richiamata da
> `init_tenant_db()`. È il meccanismo già in uso.

### Modello dati

**Struttura turni** (3 livelli, tutti con campo `style` JSON per la
formattazione):

```
struttura_presets → sovragruppi → gruppi → preset_turni
```

Le sigle si generano a cascata: `toSigla(nome)_siglaPadre`, quindi
`Radiologia` → `RADIOLOG`, `Mattina` → `MATTINA_RADIOLOG`, `TC` →
`TC_MATTINA_RADIOLOG`.

**Calendari** — `calendario_turni` è uno **snapshot completo e autosufficiente**
del preset al momento della creazione: contiene sigla, nome e ordine di gruppo
e sovragruppo, senza JOIN esterni. La sua unica foreign key punta a
`calendari(id)`; `gruppo_id` e `sg_id` sono interi **senza vincolo**.

> Conseguenza: modificare un preset **non tocca** i calendari esistenti.
> Il riallineamento è esplicito, via `POST /api/admin/calendari/<id>/ricarica-struttura`
> (`mode: preview | apply`), e funziona solo su calendari `APERTO`.
> In `apply` i turni assenti dal preset vengono **rimossi**, con CASCADE sulle
> assegnazioni: passare sempre da `preview`.

> **Regola**: ogni campo aggiunto alla struttura turni va aggiunto anche allo
> snapshot `calendario_turni` e popolato in `crea_calendario()`.

**Ciclo di vita**: `APERTO` ↔ `CHIUSO`. Il tipo è `programmato` o `effettivo`;
l'EFFETTIVO è una copia parallela con `originale_user_id`. Alla riapertura del
principale l'EFFETTIVO viene eliminato con la sua history; quella del
principale è preservata.

**Desiderata**: i lavoratori compilano `desiderata` → l'admin congela →
vengono copiate in `working_desiderata`, la copia editabile dai manager.
Il ri-congelamento è sicuro (cancella e ricopia).

**Assegnazioni**: `assegnazioni_turni`, con `user_id = NULL` per turno
scoperto. Il campo `conflitto` codifica il colore della cella:
`free`, `match`, `mismatch`, `forced`, `notte_same`, `notte_rest`, `empty`.

**History**: tabelle `history` + `history_ptr` per calendario, step-based,
con cap `MAX_HISTORY_STEPS`. Esistono history separate per le working
desiderata (`wd_history`) e per la formattazione (`style_history`).

### Services

| File | Responsabilità |
|---|---|
| `validatori.py` | Conflitti fra turni e desiderata (warning visivi, non bloccanti) |
| `solver.py` | Assegnazione automatica greedy |
| `optimizer.py` | Ottimizzazione di una griglia già assegnata |
| `ore.py` | Ore lavorate e giustificate, mensili e annuali |
| `history.py`, `wd_history.py`, `style_history.py` | Undo/redo per dominio |
| `accesso_manager.py` | Whitelist utenti/turni visibili al manager |
| `calendario_state.py` | `ottieni_calendario_aperto()` — guard di stato |
| `effettivo.py` | Creazione e gestione del calendario EFFETTIVO |
| `auto_close.py` | Chiusura automatica |
| `config_snapshot.py` | Snapshot della configurazione nel calendario |
| `websocket.py` | Broadcast real-time |

**Regole di conflitto** — configurabili da admin (`regole_conflitto`), non
hardcoded. Tipi: `tipo_vs_tipo`, `desiderata_mismatch`,
`desiderata_assenza_mismatch`. Tutti i conflitti sono **warning visivi**, mai
bloccanti.

### WebSocket

`flask-socketio` lato server, `socket.io-client` lato client. Una room per
calendario (`calendar_{id}`). Eventi: `assegnazione_changed`, `undo_redo`,
`solver_completed`. L'auth JWT avviene nell'handshake; ogni evento porta il
`manager_id` per evitare il doppio aggiornamento sul client che l'ha originato.

### Frontend — SvelteKit + Bootstrap 5

Adapter statico, output in `../static/`.

| Percorso | Contenuto |
|---|---|
| `src/lib/api.js` | Client API, allega `Authorization: Bearer`, gestisce 401 → `/login` |
| `src/lib/auth.js` | Store `user`, `token`, `tenant`, `impersonated` |
| `src/routes/master/` | Pannello piattaforma: tenant, template, audit, config |
| `src/routes/admin/` | Pannello admin (~3000 righe, Svelte 4) |
| `src/routes/manager/` | Griglia turni (Svelte 5) |
| `src/routes/basic/` | Desiderata del lavoratore (Svelte 5) |

> **Svelte misto**: `manager` e `basic` usano Svelte 5 (`$state`, `$derived`);
> `admin` è ancora Svelte 4 (`on:click`, `$:`) ma importa componenti Svelte 5.
> Verificare quale dialetto usa il file prima di modificarlo.

Componenti condivisi in `src/lib/`: `GridPreview`, `StyleContextMenu`,
`DesiderataInserimento`, `CellEditor`, `Toast`, `CredenzialiProvvisorie`.

---

## Test

```bash
pytest              # 21 test
```

`tests/conftest.py` costruisce master DB e tenant di prova in memoria, con
account sintetici (`admin_t`, `manager_t`, `basic_t`, `escluso_t`, `master_t`).
Non tocca i database reali.

---

## Convenzioni

- **Indentazione**: 4 spazi, Python e JavaScript. PEP 8 come riferimento per
  entrambi.
- **Nessun numero magico**: ogni costante ha un nome descrittivo.
- **Route sottili**: la logica di business sta nei service, non nelle route.
- **Query parametrizzate** sempre; mai concatenazione di stringhe SQL.
- **Scritture in transazione esplicita** con rollback.
- **Log senza dati sensibili**: mai PII o PHI, nemmeno in debug.
- I commenti che iniziano con `***DG:` sono dell'utente: non rimuoverli senza
  chiedere.

---

## Dati e privacy

Il progetto tratta desiderata di personale sanitario: dati personali soggetti
a GDPR. Il repository contiene **solo dati fittizi**.

Coperti da `.gitignore` e da tenere fuori da ogni commit: `.env`,
`tenant_keys.json`, `master.db`, `tenants/`, `templates/`, `static/`.

> Prima di ogni `git add -A`, controllare `git status --porcelain -uall`.
> Qualsiasi nuova directory che riceva export, dump o file di produzione va
> aggiunta a `.gitignore` nel momento stesso in cui viene creata. Mai
> committare nomi reali, nemmeno nei nomi dei file.

---

## Licenza

GPL v3 — vedi `LICENSE`.
