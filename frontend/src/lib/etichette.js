/**
 * Come l'utente chiama le sue strutture.
 *
 * "Sovragruppo" e' un termine interno: chi configura il sistema parla di
 * reparti, ambulatori, presidi. Lo stesso vale per chi pianifica i turni,
 * che a seconda del reparto e' un caposala, un capotecnico o un primario.
 *
 * Le parole si scelgono nella configurazione guidata, vivono in `config` sul
 * tenant e da qui le leggono le schermate che le mostrano, senza passarsele
 * di componente in componente.
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

// Chi pianifica i turni. Il ruolo interno si chiama `manager`; la parola con
// cui lo si nomina cambia da reparto a reparto.
export const ETICHETTA_MANAGER_DEFAULT = 'Pianificatore';

export const etichettaManager = writable(ETICHETTA_MANAGER_DEFAULT);

/**
 * Adotta la parola salvata per chi pianifica i turni.
 *
 * @param {object} config — mappa chiave/valore da GET /api/admin/config.
 */
export function leggiEtichettaManager(config) {
    const scelta = config?.['etichetta_manager'];
    if (scelta) etichettaManager.set(scelta);
}
