"""
seed_demo.py — Bootstrap di un'installazione dimostrativa da zero.

Tipo modifica: NUOVO STRUMENTO (sostituisce le migrazioni one-shot).

Ricrea master DB, DB tenant e DB template partendo dai soli schemi
(`migrations/init_master_db.sql` e `migrations/init_db.sql`) e li popola
con dati interamente di fantasia: un ospedale fittizio, reparti fittizi,
turni generici e utenti con cognomi inventati.

Nessun dato reale e' coinvolto: tutti i valori sono costanti dichiarate in
questo file. Le sigle sono generate con la stessa convenzione del
frontend (`toSigla(nome)_siglaPadre`), quindi risultano coerenti per
costruzione, senza abbreviazioni residue.

ATTENZIONE: cancella i database esistenti. Usare solo su ambienti di
sviluppo o per preparare una demo pulita.

    python seed_demo.py            # chiede conferma
    python seed_demo.py --force    # non chiede nulla
"""

import json
import os
import sys

import bcrypt

try:
    import sqlcipher3 as sqlite3
except ImportError:
    print("ERRORE: sqlcipher3 non trovato. Esegui: pip install sqlcipher3")
    sys.exit(1)

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Identita' dell'installazione demo (tutto di fantasia)
# ---------------------------------------------------------------------------

NOME_ENTE = 'Ospedale Demo'
SLUG_TENANT = 'default'
NOME_PRESET = 'struttura_demo'

# Account di piattaforma e di tenant. La password coincide con lo username:
# credenziale di sviluppo, da cambiare prima di qualunque uso reale.
UTENTE_PIATTAFORMA = 'superadmin'
UTENTE_ADMIN_TENANT = ('admin_uo', 'AUO', 'admin')

# Cognomi di fantasia a 5 lettere per il personale demo.
COGNOMI_DEMO = [
    'ROSSI', 'BIANC', 'VERDI', 'RUSSO', 'FERRA', 'ESPOS', 'ROMAN', 'COLOM',
    'RICCI', 'MARIN', 'BRUNO', 'GALLO', 'CONTI', 'COSTA', 'GIORD', 'MANCI',
]

# I primi N cognomi diventano manager, i restanti personale semplice.
NUMERO_MANAGER = 2

# Reparti fittizi: (nome, ambito, [nomi dei gruppi], [nomi dei turni]).
REPARTI_DEMO = [
    ('Radiologia', 'Diagnostica per immagini',
     ['Mattina', 'Pomeriggio', 'Notte'],
     ['TC', 'RM', 'Ecografia', 'RX tradizionale']),
    ('Senologia', 'Diagnostica per immagini',
     ['Mattina', 'Pomeriggio'],
     ['Mammografia', 'Ecografia', 'Biopsia']),
    ('Neuroradiologia', 'Diagnostica per immagini',
     ['Mattina', 'Pomeriggio'],
     ['TC', 'RM', 'Angiografia']),
]

# Flag temporale associato a ogni gruppo, per nome del gruppo.
FLAG_PER_GRUPPO = {
    'Mattina': 'mattina',
    'Pomeriggio': 'pomeriggio',
    'Notte': 'notturno',
}

BCRYPT_ROUNDS = 12
LUNGHEZZA_MAX_SIGLA = 8
PASSO_ORDINE = 10


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def to_sigla(nome):
    """
    Genera la sigla di un elemento, come `toSigla()` nel frontend.

    Maiuscolo, soli caratteri alfanumerici, troncato a 8.
    """
    pulito = ''.join(ch for ch in nome.upper() if ch.isalnum())
    return pulito[:LUNGHEZZA_MAX_SIGLA] or 'X'


def sigla_figlio(nome, sigla_padre):
    """Compone la sigla gerarchica figlio: `SIGLA_SIGLAPADRE`."""
    return f"{to_sigla(nome)}_{sigla_padre}"


def hash_password(password):
    """Genera un hash bcrypt nello stesso formato di app/auth.py."""
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    ).decode('utf-8')


def apri_db(percorso, chiave):
    """Apre (creando il file se assente) un database SQLCipher."""
    conn = sqlite3.connect(percorso)
    conn.execute(f"PRAGMA key='{chiave}'")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def esegui_schema(conn, percorso_schema):
    """Applica uno script SQL di schema al database aperto."""
    with open(percorso_schema, encoding='utf-8') as handle:
        conn.executescript(handle.read())
    conn.commit()


def elimina_se_presente(percorso):
    """Rimuove un file di database e i suoi sidecar WAL/SHM."""
    for suffisso in ('', '-wal', '-shm'):
        candidato = percorso + suffisso
        if os.path.exists(candidato):
            os.remove(candidato)


# ---------------------------------------------------------------------------
# Popolamento
# ---------------------------------------------------------------------------

def popola_master(conn):
    """Inserisce l'account di piattaforma e il tenant demo."""
    conn.execute(
        "INSERT INTO master_users (username, password_hash, role, is_active) "
        "VALUES (?, ?, 'master_admin', 1)",
        (UTENTE_PIATTAFORMA, hash_password(UTENTE_PIATTAFORMA))
    )
    conn.execute(
        "INSERT INTO tenants (slug, nome, db_filename, is_active, visibile_login) "
        "VALUES (?, ?, ?, 1, 1)",
        (SLUG_TENANT, NOME_ENTE, f"tenant_{SLUG_TENANT}.db")
    )
    conn.commit()


def popola_utenti(conn):
    """Crea l'admin di tenant, i manager e il personale demo."""
    username, sigla, ruolo = UTENTE_ADMIN_TENANT
    conn.execute("DELETE FROM users")
    conn.execute(
        "INSERT INTO users (username, password_hash, role, sigla, is_active) "
        "VALUES (?, ?, ?, ?, 1)",
        (username, hash_password(username), ruolo, sigla)
    )

    for indice, cognome in enumerate(COGNOMI_DEMO):
        ruolo_utente = 'manager' if indice < NUMERO_MANAGER else 'basic'
        conn.execute(
            "INSERT INTO users (username, password_hash, role, sigla, is_active) "
            "VALUES (?, ?, ?, ?, 1)",
            (cognome.lower(), hash_password(cognome.lower()), ruolo_utente, cognome)
        )
    conn.commit()
    return len(COGNOMI_DEMO) + 1


def _id_flag(conn, nome_flag):
    """Restituisce l'id di un flag_turno per nome, o None."""
    riga = conn.execute(
        "SELECT id FROM flag_turno WHERE nome = ?", (nome_flag,)).fetchone()
    return riga['id'] if riga else None


def popola_struttura(conn):
    """Crea preset, reparti, gruppi e turni con sigle coerenti."""
    cur = conn.execute(
        "INSERT INTO struttura_presets (nome, is_default) VALUES (?, 1)",
        (NOME_PRESET,)
    )
    preset_id = cur.lastrowid
    conteggi = {'sovragruppi': 0, 'gruppi': 0, 'turni': 0}

    for indice_sg, (nome_sg, ambito, nomi_gruppi, nomi_turni) in enumerate(REPARTI_DEMO):
        sigla_sg = to_sigla(nome_sg)
        cur = conn.execute(
            "INSERT INTO sovragruppi (preset_id, sigla, nome, ambito, ordine) "
            "VALUES (?, ?, ?, ?, ?)",
            (preset_id, sigla_sg, nome_sg, ambito, indice_sg * PASSO_ORDINE)
        )
        sg_id = cur.lastrowid
        conteggi['sovragruppi'] += 1

        for indice_g, nome_gruppo in enumerate(nomi_gruppi):
            sigla_gruppo = sigla_figlio(nome_gruppo, sigla_sg)
            cur = conn.execute(
                "INSERT INTO gruppi (sovragruppo_id, sigla, nome, flag_id, ordine) "
                "VALUES (?, ?, ?, ?, ?)",
                (sg_id, sigla_gruppo, nome_gruppo,
                 _id_flag(conn, FLAG_PER_GRUPPO.get(nome_gruppo, 'mattina')),
                 indice_g * PASSO_ORDINE)
            )
            gruppo_id = cur.lastrowid
            conteggi['gruppi'] += 1

            for indice_t, nome_turno in enumerate(nomi_turni):
                conn.execute(
                    "INSERT INTO preset_turni (gruppo_id, sigla, nome, ordine) "
                    "VALUES (?, ?, ?, ?)",
                    (gruppo_id, sigla_figlio(nome_turno, sigla_gruppo),
                     nome_turno, indice_t * PASSO_ORDINE)
                )
                conteggi['turni'] += 1

    conn.commit()
    return conteggi


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def percorso_schema(nome_file):
    """Percorso assoluto di uno schema dentro migrations/."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'migrations', nome_file)


def ricostruisci():
    """Cancella e ricrea i tre database con i dati demo."""
    load_dotenv('.env')

    percorso_master = os.environ.get('MASTER_DB_PATH', 'master.db')
    chiave_master = os.environ.get('MASTER_DB_KEY')
    dir_tenant = os.environ.get('TENANT_DB_DIR', 'tenants/')
    dir_template = os.environ.get('TEMPLATE_DB_DIR', 'templates/')

    with open(os.environ.get('TENANT_KEYS_PATH', 'tenant_keys.json'),
              encoding='utf-8') as handle:
        chiavi = json.load(handle)

    percorso_tenant = os.path.join(dir_tenant, f"tenant_{SLUG_TENANT}.db")
    percorso_template = os.path.join(dir_template, 'template_base.db')

    # --- Master ---
    print(f"--- {percorso_master}")
    elimina_se_presente(percorso_master)
    conn = apri_db(percorso_master, chiave_master)
    esegui_schema(conn, percorso_schema('init_master_db.sql'))
    popola_master(conn)
    conn.close()
    print(f"    ricreato: {UTENTE_PIATTAFORMA} + tenant '{SLUG_TENANT}' ({NOME_ENTE})")

    # --- Tenant ---
    print(f"--- {percorso_tenant}")
    os.makedirs(dir_tenant, exist_ok=True)
    elimina_se_presente(percorso_tenant)
    conn = apri_db(percorso_tenant, chiavi[SLUG_TENANT])
    esegui_schema(conn, percorso_schema('init_db.sql'))
    n_utenti = popola_utenti(conn)
    conteggi = popola_struttura(conn)
    conn.close()
    print(f"    ricreato: {n_utenti} utenti, {conteggi['sovragruppi']} reparti, "
          f"{conteggi['gruppi']} gruppi, {conteggi['turni']} turni")

    # --- Template per nuovi tenant ---
    print(f"--- {percorso_template}")
    os.makedirs(dir_template, exist_ok=True)
    elimina_se_presente(percorso_template)
    conn = apri_db(percorso_template, chiavi['_template_base'])
    esegui_schema(conn, percorso_schema('init_db.sql'))
    popola_utenti_template(conn)
    conn.close()
    print("    ricreato: solo account admin, nessuna persona")


def popola_utenti_template(conn):
    """Il template contiene il solo admin di tenant, nessuna persona fisica."""
    username, sigla, ruolo = UTENTE_ADMIN_TENANT
    conn.execute("DELETE FROM users")
    conn.execute(
        "INSERT INTO users (username, password_hash, role, sigla, is_active) "
        "VALUES (?, ?, ?, ?, 1)",
        (username, hash_password(username), ruolo, sigla)
    )
    conn.commit()


def main():
    """Chiede conferma e ricostruisce l'installazione demo."""
    if '--force' not in sys.argv:
        print("Questa operazione CANCELLA master.db, il DB tenant e il template.")
        risposta = input("Scrivi 'RICOSTRUISCI' per procedere: ").strip()
        if risposta != 'RICOSTRUISCI':
            print("Annullato.")
            return

    ricostruisci()
    print("\nInstallazione demo pronta.")
    print(f"  piattaforma : {UTENTE_PIATTAFORMA} / {UTENTE_PIATTAFORMA}")
    print(f"  tenant      : {UTENTE_ADMIN_TENANT[0]} / {UTENTE_ADMIN_TENANT[0]} "
          f"(organizzazione '{SLUG_TENANT}')")
    print("  ATTENZIONE: password uguali allo username, solo per sviluppo.")


if __name__ == '__main__':
    main()
