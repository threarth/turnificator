/**
 * WebSocket client per sync real-time tra manager.
 * Usa socket.io-client con autenticazione JWT.
 */
import { io } from 'socket.io-client';
import { get } from 'svelte/store';
import { token } from './auth.js';

let socket = null;
let listeners = [];
let _onStatusChange = null;

export function connectSocket() {
  const t = get(token);
  if (!t || socket?.connected) return socket;

  socket = io('/', {
    auth: { token: t },
    transports: ['websocket', 'polling'],
  });

  socket.on('connect', () => {
    console.log('[WS] connected');
    if (_onStatusChange) _onStatusChange(true);
  });
  socket.on('disconnect', (reason) => {
    console.log('[WS] disconnected:', reason);
    if (_onStatusChange) _onStatusChange(false);
  });
  socket.on('connect_error', (err) => {
    console.warn('[WS] connect_error:', err.message);
  });

  return socket;
}

export function joinCalendario(calId) {
  socket?.emit('join_calendario', { calendario_id: calId });
}

export function leaveCalendario(calId) {
  socket?.emit('leave_calendario', { calendario_id: calId });
}

export function onAssegnazioneChanged(callback) {
  if (!socket) return;
  socket.on('assegnazione_changed', callback);
  listeners.push(['assegnazione_changed', callback]);
}

export function onUndoRedo(callback) {
  if (!socket) return;
  socket.on('undo_redo', callback);
  listeners.push(['undo_redo', callback]);
}

export function onSolverCompleted(callback) {
  if (!socket) return;
  socket.on('solver_completed', callback);
  listeners.push(['solver_completed', callback]);
}

export function onConflittiUpdated(callback) {
  if (!socket) return;
  socket.on('conflitti_updated', callback);
  listeners.push(['conflitti_updated', callback]);
}

export function onDesiderataChanged(callback) {
  if (!socket) return;
  socket.on('desiderata_changed', callback);
  listeners.push(['desiderata_changed', callback]);
}

export function onPrivacyChanged(callback) {
  if (!socket) return;
  socket.on('privacy_changed', callback);
  listeners.push(['privacy_changed', callback]);
}

export function removeAllListeners() {
  for (const [event, cb] of listeners) {
    socket?.off(event, cb);
  }
  listeners = [];
}

/**
 * Rimuove un singolo handler precedentemente registrato.
 * Usato da componenti figli che non devono toccare i listener del parent.
 */
export function offListener(event, callback) {
  socket?.off(event, callback);
  listeners = listeners.filter(([e, cb]) => !(e === event && cb === callback));
}

export function disconnectSocket() {
  removeAllListeners();
  socket?.disconnect();
  socket = null;
}

export function isConnected() {
  return socket?.connected ?? false;
}

export function onStatusChange(callback) {
  _onStatusChange = callback;
}

export function getSocket() {
  return socket;
}
