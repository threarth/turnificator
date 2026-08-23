"""
app/services/websocket.py — WebSocket event handlers per sync real-time.

Gestisce connessione, autenticazione JWT, room per calendario,
e funzioni di broadcast per assegnazioni/undo/redo/solver.

Multi-tenant: le room sono prefissate con il tenant slug per garantire
isolamento tra organizzazioni diverse. Il formato room e':
    {tenant_slug}_calendar_{cal_id}
"""

from flask import g, request
from flask_socketio import emit, join_room, leave_room
from flask_jwt_extended import decode_token

from app import socketio


# ---------------------------------------------------------------------------
# Helper: nome room tenant-aware
# ---------------------------------------------------------------------------

def _room_name(tenant_slug, cal_id):
    """
    Genera il nome della room SocketIO per un calendario.

    Il prefisso tenant garantisce che manager di tenant diversi
    non ricevano eventi incrociati anche se i calendar ID coincidono.

    Args:
        tenant_slug (str): slug del tenant (se None, usa solo calendar_).
        cal_id (int|str): ID del calendario.

    Returns:
        str: nome room nel formato '{tenant_slug}_calendar_{cal_id}'.
    """
    if tenant_slug:
        return f'{tenant_slug}_calendar_{cal_id}'
    return f'calendar_{cal_id}'


def _get_tenant_slug():
    """
    Ottiene il tenant slug dal contesto corrente.

    Cerca prima in g.tenant_slug (impostato dal middleware),
    poi nel socketio_user (impostato al connect WebSocket).
    """
    slug = getattr(g, 'tenant_slug', None)
    if slug:
        return slug
    user_info = request.environ.get('socketio_user', {})
    return user_info.get('tenant')


# ---------------------------------------------------------------------------
# Connessione e autenticazione
# ---------------------------------------------------------------------------

@socketio.on('connect')
def on_connect(auth):
    """
    Autenticazione via JWT nel handshake.

    Estrae user ID, ruolo e tenant slug dal token JWT.
    Rifiuta la connessione se il token manca o non e' valido.
    """
    token = auth.get('token') if auth else None
    if not token:
        return False
    try:
        decoded = decode_token(token)
        tenant_slug = decoded.get('tenant')
        request.environ['socketio_user'] = {
            'id': decoded.get('sub'),
            'role': decoded.get('role', 'basic'),
            'tenant': tenant_slug,
        }
    except Exception:
        return False


@socketio.on('join_calendario')
def on_join(data):
    """Manager entra nella room del calendario per ricevere aggiornamenti."""
    cal_id = data.get('calendario_id')
    user_info = request.environ.get('socketio_user', {})
    tenant_slug = user_info.get('tenant')

    if cal_id and tenant_slug:
        join_room(_room_name(tenant_slug, cal_id))


@socketio.on('leave_calendario')
def on_leave(data):
    """Manager esce dalla room del calendario."""
    cal_id = data.get('calendario_id')
    user_info = request.environ.get('socketio_user', {})
    tenant_slug = user_info.get('tenant')

    if cal_id and tenant_slug:
        leave_room(_room_name(tenant_slug, cal_id))


# ---------------------------------------------------------------------------
# Broadcast helpers (chiamati dagli endpoint manager)
# ---------------------------------------------------------------------------

def broadcast_assegnazione(cal_id, turno_id, giorno, user_id, conflitto, conflitti, history_info, manager_id, tenant_slug=None):
    """Broadcast quando un'assegnazione cambia."""
    room = _room_name(tenant_slug or _get_tenant_slug(), cal_id)
    socketio.emit('assegnazione_changed', {
        'turno_id': turno_id,
        'giorno': giorno,
        'user_id': user_id,
        'conflitto': conflitto,
        'conflitti': conflitti,
        'history': history_info,
        'manager_id': manager_id,
    }, room=room)


def broadcast_svuota(cal_id, turno_id, giorno, history_info, manager_id, tenant_slug=None):
    """Broadcast quando una cella viene svuotata."""
    room = _room_name(tenant_slug or _get_tenant_slug(), cal_id)
    socketio.emit('assegnazione_changed', {
        'turno_id': turno_id,
        'giorno': giorno,
        'user_id': None,
        'conflitto': 'empty',
        'conflitti': '[]',
        'history': history_info,
        'manager_id': manager_id,
    }, room=room)


def broadcast_undo_redo(cal_id, tabella, dati, history_info, manager_id, tenant_slug=None):
    """Broadcast dopo undo/redo."""
    room = _room_name(tenant_slug or _get_tenant_slug(), cal_id)
    socketio.emit('undo_redo', {
        'tabella': tabella,
        'dati': dati,
        'history': history_info,
        'manager_id': manager_id,
    }, room=room)


def broadcast_solver(cal_id, risultato, manager_id, tenant_slug=None):
    """Broadcast dopo solver completato."""
    room = _room_name(tenant_slug or _get_tenant_slug(), cal_id)
    socketio.emit('solver_completed', {
        'risultato': {
            'celle_riempite': risultato.get('celle_riempite', 0),
            'turni_operati': risultato.get('turni_operati', 0),
        },
        'manager_id': manager_id,
    }, room=room)


def broadcast_ricalcolo_conflitti(cal_id, aggiornamenti, manager_id, tenant_slug=None):
    """Broadcast aggiornamenti conflitti dopo ricalcolo."""
    room = _room_name(tenant_slug or _get_tenant_slug(), cal_id)
    socketio.emit('conflitti_updated', {
        'aggiornamenti': aggiornamenti,
        'manager_id': manager_id,
    }, room=room)


# ---------------------------------------------------------------------------
# Broadcast desiderata e privacy (sync real-time viste desiderata)
# ---------------------------------------------------------------------------

def broadcast_desiderata_changed(cal_id, user_id, giorno, entry, source, actor_id, tenant_slug=None, author_offusca=0):
    """
    Broadcast quando una desiderata (basic) o working_desiderata (manager) cambia.

    Args:
        cal_id (int): ID calendario.
        user_id (int): autore della desiderata (non l'attore).
        giorno (int): giorno 1-31.
        entry (dict|None): {tipo_richiesta_id, req_sigla, req_tipo} se inserita,
                           None se cancellata.
        source (str): 'desiderata' (basic) | 'working_desiderata' (manager).
        actor_id (int): chi ha eseguito l'azione (per evitare doppio update).
        author_offusca (int): flag offusca dell'autore (0/1/2), serve ai client
            basic per applicare il mascheramento in tempo reale.
    """
    room = _room_name(tenant_slug or _get_tenant_slug(), cal_id)
    socketio.emit('desiderata_changed', {
        'user_id': user_id,
        'giorno': giorno,
        'entry': entry,
        'source': source,
        'actor_id': actor_id,
        'author_offusca': author_offusca,
    }, room=room)


def broadcast_privacy_changed(cal_id, user_id, offusca, actor_id, tenant_slug=None):
    """
    Broadcast quando un utente cambia il flag offusca.

    Viene emesso per ogni calendario aperto del tenant cosi' che tutti
    i client collegati a una vista desiderata vedano aggiornarsi
    immediatamente il mascheramento.
    """
    room = _room_name(tenant_slug or _get_tenant_slug(), cal_id)
    socketio.emit('privacy_changed', {
        'user_id': user_id,
        'offusca': offusca,
        'actor_id': actor_id,
    }, room=room)
