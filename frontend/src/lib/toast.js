/**
 * toast.js — store globale per i messaggi toast.
 *
 * Utilizzo:
 *   import { showToast } from '$lib/toast.js';
 *   showToast('Modifiche salvate.');            // toast verde (successo)
 *   showToast('Errore di rete.', false);        // toast rosso (errore)
 */

import { writable } from 'svelte/store';

// Array di toast attivi: { id, message, ok }
export const toasts = writable([]);

let _nextId = 0;

const TOAST_DURATION_MS = 3000;

/**
 * Mostra un toast in basso a destra.
 * @param {string}  message - Testo da mostrare.
 * @param {boolean} ok      - true = successo (verde), false = errore (rosso).
 */
export function showToast(message, ok = true) {
    const id = ++_nextId;
    toasts.update(list => [...list, { id, message, ok }]);
    setTimeout(() => {
        toasts.update(list => list.filter(t => t.id !== id));
    }, TOAST_DURATION_MS);
}
