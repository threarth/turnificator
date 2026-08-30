/**
 * Come l'utente chiama le sue strutture.
 *
 * "Sovragruppo" e' un termine interno: chi configura il sistema parla di
 * reparti, ambulatori, presidi. La parola si sceglie nella procedura guidata,
 * vive in `config` sul tenant e da qui la leggono le schermate che la mostrano,
 * senza passarsela di componente in componente.
 */

import { writable } from 'svelte/store';

// Il termine interno resta il ripiego: e' quello che l'installazione mostra
// finche' nessuno ha scelto la propria parola.
export const ETICHETTA_STRUTTURA_DEFAULT = {
    singolare: 'Sovragruppo',
    plurale: 'Sovragruppi',
};

export const etichettaStruttura = writable({ ...ETICHETTA_STRUTTURA_DEFAULT });

/**
 * Adotta la parola salvata nella configurazione del tenant.
 *
 * @param {object} config — mappa chiave/valore da GET /api/admin/config.
 */
export function leggiEtichettaDaConfig(config) {
    const singolare = config?.['etichetta_struttura'];
    if (!singolare) return;

    etichettaStruttura.set({
        singolare,
        plurale: config['etichetta_strutture'] || singolare,
    });
}
