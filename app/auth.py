"""
app/auth.py — autenticazione e autorizzazione JWT (multi-tenant).

Fornisce:
- authenticate_user: login utente tenant con verifica bcrypt
- authenticate_master: login master admin
- require_role: decoratore per proteggere route per ruolo tenant
- require_master_role: decoratore per route master admin
- get_current_user: risolve utente corrente da JWT + tenant
"""

from functools import wraps

import bcrypt
from flask import current_app, g, jsonify
from flask_jwt_extended import (
    create_access_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
)

from app.db import get_master_db, query_one

# Lunghezza minima richiesta per una password impostata dall'utente.
LUNGHEZZA_MINIMA_PASSWORD = 8


# ---------------------------------------------------------------------------
# Login tenant
# ---------------------------------------------------------------------------

def sono_credenziali_provvisorie(username, password):
    """
    Indica se l'account usa ancora una credenziale di sviluppo.

    Gli account creati dal seed e dagli script di bonifica hanno password
    uguale allo username. Il controllo avviene al login, quando la password
    in chiaro e' disponibile, e si spegne da solo appena l'utente la cambia.

    Args:
        username (str): nome utente.
        password (str): password in chiaro appena verificata.

    Returns:
        bool: True se la password coincide con lo username.
    """
    return password == username


def authenticate_user(username, password, tenant_slug):
    """
    Verifica le credenziali di un utente tenant e restituisce un token JWT.

    La password viene verificata con bcrypt contro l'hash memorizzato nel DB
    del tenant. L'utente deve essere attivo (is_active = 1).
    Il JWT include il claim 'tenant' per identificare il contesto.

    Args:
        username (str): nome utente inserito nel form di login.
        password (str): password in chiaro inserita nel form di login.
        tenant_slug (str): slug del tenant su cui autenticare.

    Returns:
        dict: con chiavi:
            - 'ok' (bool): True se login riuscito.
            - 'token' (str): token JWT (se ok).
            - 'user' (dict): dati utente pubblici (se ok).
            - 'tenant' (str): slug del tenant (se ok).
            - 'errore' (str): messaggio di errore (se non ok).
    """
    # Imposta il contesto tenant per questa richiesta
    g.tenant_slug = tenant_slug

    utente = query_one(
        "SELECT id, username, password_hash, role, sigla, is_active "
        "FROM users WHERE username = ?",
        (username,)
    )

    if not utente:
        return {'ok': False, 'errore': 'Credenziali non valide.'}

    if not utente['is_active']:
        return {
            'ok': False,
            'errore': 'Account disabilitato. Contatta l\'amministratore.'
        }

    password_valida = bcrypt.checkpw(
        password.encode('utf-8'),
        utente['password_hash'].encode('utf-8')
    )

    if not password_valida:
        return {'ok': False, 'errore': 'Credenziali non valide.'}

    # JWT con claim tenant e ruolo
    token = create_access_token(
        identity=str(utente['id']),
        additional_claims={
            'tenant': tenant_slug,
            'role': utente['role'],
        }
    )

    return {
        'ok': True,
        'token': token,
        'tenant': tenant_slug,
        'user': {
            'id':       utente['id'],
            'username': utente['username'],
            'role':     utente['role'],
            'sigla':    utente['sigla'],
            'credenziali_provvisorie': sono_credenziali_provvisorie(
                utente['username'], password),
        }
    }


# ---------------------------------------------------------------------------
# Login master admin
# ---------------------------------------------------------------------------

def authenticate_master(username, password):
    """
    Verifica le credenziali di un utente master admin.

    Autentica contro la tabella master_users nel master DB.
    Il JWT ha identity 'master:<id>' e claim role='master_admin'.

    Args:
        username (str): nome utente master.
        password (str): password in chiaro.

    Returns:
        dict: con chiavi ok, token, user, errore.
    """
    master_db = get_master_db()
    row = master_db.execute(
        "SELECT id, username, password_hash, role, is_active "
        "FROM master_users WHERE username = ?",
        (username,)
    ).fetchone()

    if not row:
        return {'ok': False, 'errore': 'Credenziali non valide.'}

    utente = dict(row)

    if not utente['is_active']:
        return {
            'ok': False,
            'errore': 'Account disabilitato.'
        }

    password_valida = bcrypt.checkpw(
        password.encode('utf-8'),
        utente['password_hash'].encode('utf-8')
    )

    if not password_valida:
        return {'ok': False, 'errore': 'Credenziali non valide.'}

    token = create_access_token(
        identity=f"master:{utente['id']}",
        additional_claims={
            'role': 'master_admin',
            'tenant': None,
        }
    )

    return {
        'ok': True,
        'token': token,
        'user': {
            'id':       utente['id'],
            'username': utente['username'],
            'role':     'master_admin',
            'credenziali_provvisorie': sono_credenziali_provvisorie(
                utente['username'], password),
        }
    }


def cambia_password_master(user_id, password_attuale, password_nuova):
    """
    Cambia la password di un account master admin.

    La logica sta qui e non nella route perche' e' logica di dominio:
    verifica dell'identita', regole di robustezza e scrittura sul master DB.

    Rifiuta una password nuova uguale allo username: sarebbe di nuovo una
    credenziale provvisoria, esattamente quella che si vuole superare.

    Args:
        user_id (int): id dell'account master autenticato.
        password_attuale (str): password corrente, per conferma identita'.
        password_nuova (str): password da impostare.

    Returns:
        dict: { 'ok': True } oppure { 'ok': False, 'errore': str }.
    """
    master_db = get_master_db()
    row = master_db.execute(
        "SELECT id, username, password_hash FROM master_users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not row:
        return {'ok': False, 'errore': 'Account non trovato.'}

    utente = dict(row)

    if not bcrypt.checkpw(password_attuale.encode('utf-8'),
                          utente['password_hash'].encode('utf-8')):
        return {'ok': False, 'errore': 'Password attuale non corretta.'}

    if len(password_nuova) < LUNGHEZZA_MINIMA_PASSWORD:
        return {
            'ok': False,
            'errore': f'La nuova password deve avere almeno '
                      f'{LUNGHEZZA_MINIMA_PASSWORD} caratteri.'
        }

    if password_nuova == utente['username']:
        return {
            'ok': False,
            'errore': 'La nuova password non puo\' coincidere con il nome utente.'
        }

    if password_nuova == password_attuale:
        return {'ok': False, 'errore': 'La nuova password coincide con quella attuale.'}

    try:
        master_db.execute("BEGIN")
        master_db.execute(
            "UPDATE master_users SET password_hash = ? WHERE id = ?",
            (hash_password(password_nuova), utente['id'])
        )
        master_db.commit()
    except Exception as exc:
        master_db.rollback()
        current_app.logger.error("Cambio password master fallito: %s", type(exc).__name__)
        return {'ok': False, 'errore': 'Errore durante il salvataggio della password.'}

    return {'ok': True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_current_user():
    """
    Restituisce il record dell'utente autenticato dalla richiesta corrente.

    Legge il claim 'tenant' dal JWT per impostare il contesto tenant,
    poi carica il record utente dal DB del tenant.
    Per master admin (identity 'master:<id>') restituisce None.

    Returns:
        dict | None: dati utente, o None se master admin o utente non trovato.
    """
    # Imposta tenant da JWT se non gia' impostato
    claims = get_jwt()
    tenant = claims.get('tenant')
    if tenant and not g.get('tenant_slug'):
        g.tenant_slug = tenant

    user_id = get_jwt_identity()

    # Master admin non ha record in nessun tenant DB
    if str(user_id).startswith('master:'):
        return None

    return query_one(
        "SELECT id, username, role, sigla, is_active, puo_gestire_calendari, "
        "sovragruppo_id, offusca, escluso_turni "
        "FROM users WHERE id = ?",
        (int(user_id),)
    )


def get_current_master_user():
    """
    Restituisce il record del master admin dalla richiesta corrente.

    Usato nelle route master per ottenere l'identita' del master admin.

    Returns:
        dict | None: dati master user, o None se non e' un master admin.
    """
    user_id = get_jwt_identity()
    if not str(user_id).startswith('master:'):
        return None

    master_id = int(str(user_id).split(':')[1])
    master_db = get_master_db()
    row = master_db.execute(
        "SELECT id, username, role FROM master_users WHERE id = ?",
        (master_id,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Decoratori di autorizzazione
# ---------------------------------------------------------------------------

def require_role(*roles):
    """
    Decoratore che protegge una route JWT richiedendo uno dei ruoli specificati.

    Combina @jwt_required() con la verifica del ruolo dell'utente corrente
    nel contesto del tenant (risolto dal claim JWT 'tenant').

    Args:
        *roles (str): uno o piu' ruoli ammessi, es. require_role('admin', 'manager').

    Returns:
        Callable: decoratore da applicare alla funzione di route.
    """
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def wrapper(*args, **kwargs):
            utente = get_current_user()
            if not utente:
                return jsonify({'errore': 'Utente non trovato.'}), 401
            if utente['role'] not in roles:
                return jsonify({'errore': 'Accesso non autorizzato.'}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


def require_master_role():
    """
    Decoratore che protegge una route richiedendo il ruolo master_admin.

    Verifica che il JWT contenga role='master_admin' nei claims.

    Returns:
        Callable: decoratore da applicare alla funzione di route.
    """
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def wrapper(*args, **kwargs):
            claims = get_jwt()
            if claims.get('role') != 'master_admin':
                return jsonify({'errore': 'Accesso master admin richiesto.'}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


def hash_password(password):
    """
    Genera un hash bcrypt della password fornita.

    Usa un cost factor di 12 (buon bilanciamento sicurezza/velocita').

    Args:
        password (str): password in chiaro da cifrare.

    Returns:
        str: hash bcrypt come stringa decodificata, pronta per il DB.
    """
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt(rounds=12)
    ).decode('utf-8')
