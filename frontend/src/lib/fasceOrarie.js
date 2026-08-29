/**
 * lib/fasceOrarie.js — appartenenza di una fascia oraria a un concetto.
 *
 * Gemello lato client di app/services/fasce_orarie.py, limitato alle sole
 * domande sulla gerarchia: le durate e i pesi arrivano gia' calcolati dal
 * backend.
 *
 * I flag_turno sono organizzati su due livelli: i concetti root (diurno,
 * notturno, guardia_24h) e le fasce orarie che ne discendono. Le fasce si
 * possono rinominare, i concetti no: per sapere se un turno e' una notte si
 * guarda da chi discende, mai come si chiama.
 */

/** Nomi dei concetti root: l'unico riferimento stabile per il codice. */
export const NOME_ROOT_DIURNO = 'diurno';
export const NOME_ROOT_NOTTURNO = 'notturno';
export const NOME_ROOT_GUARDIA = 'guardia_24h';

/** Guardia contro gerarchie cicliche prodotte da dati corrotti. */
const PROFONDITA_MAX_GERARCHIA = 16;

/**
 * Indicizza per id la lista dei flag ricevuta dal backend.
 *
 * @param {Array<{id: number, nome: string, parent_id: ?number}>} flags
 * @returns {Map<number, object>} mappa id → flag
 */
export function costruisciMappaFlag(flags) {
    return new Map((flags ?? []).map(f => [f.id, f]));
}

/**
 * Risale la gerarchia e restituisce il flag stesso con tutti i suoi antenati.
 *
 * @param {?number} flagId
 * @param {Map<number, object>} mappa
 * @returns {Array<object>} flag incontrati, dal piu' specifico al concetto
 */
function catenaAntenati(flagId, mappa) {
    const catena = [];
    const visti = new Set();
    let corrente = flagId;

    while (corrente != null && !visti.has(corrente) && catena.length < PROFONDITA_MAX_GERARCHIA) {
        visti.add(corrente);
        const flag = mappa.get(corrente);
        if (!flag) break;
        catena.push(flag);
        corrente = flag.parent_id;
    }

    return catena;
}

/**
 * Verifica se un flag e' il concetto indicato o una fascia che ne discende.
 *
 * Il concetto matcha anche se stesso: i calendari creati prima delle fasce
 * orarie agganciano i gruppi direttamente ai concetti, e i loro snapshot non
 * vengono riscritti.
 *
 * @param {?string} flagNome nome del flag da verificare
 * @param {?string} nomeRoot nome del concetto, es. 'notturno'
 * @param {Map<number, object>} mappa
 * @returns {boolean}
 */
export function discendeDaNome(flagNome, nomeRoot, mappa) {
    if (!flagNome || !nomeRoot) return false;

    // Senza gerarchia disponibile resta il confronto sul nome: preferibile a
    // rispondere sempre "no" e far sparire, per esempio, la colonna notti.
    if (!mappa || mappa.size === 0) {
        return flagNome.toLowerCase() === nomeRoot.toLowerCase();
    }

    const flag = [...mappa.values()].find(f => f.nome === flagNome);
    if (!flag) return false;

    return catenaAntenati(flag.id, mappa).some(f => f.nome === nomeRoot);
}

/**
 * Scorciatoia per la domanda piu' frequente: questo turno e' una notte?
 *
 * @param {?string} flagNome nome della fascia del turno
 * @param {Map<number, object>} mappa
 * @returns {boolean}
 */
export function eNotturna(flagNome, mappa) {
    return discendeDaNome(flagNome, NOME_ROOT_NOTTURNO, mappa);
}
