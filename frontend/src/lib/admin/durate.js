/**
 * Conversioni fra le unita' con cui si esprimono le durate dei turni.
 *
 * Il database tiene le ore come decimali (6.5) e le durate come minuti
 * interi (390); l'utente legge e scrive 'h:mm'. Le conversioni stanno qui
 * perche' servono sia alla pagina admin sia alla riga della tabella flag.
 */

const MINUTI_PER_ORA = 60;
const CIFRE_MINUTI = 2;

/**
 * Ore decimali → 'h:mm'.
 *
 * @param {number|string|null} dec — ore decimali (es. 6.5).
 * @returns {string} 'h:mm', stringa vuota se il valore manca o non e' un numero.
 */
export function decToHm(dec) {
    if (dec == null || dec === '') return '';

    const d = parseFloat(dec);
    if (isNaN(d)) return '';

    const ore = Math.floor(d);
    const minuti = Math.round((d - ore) * MINUTI_PER_ORA);

    return `${ore}:${String(minuti).padStart(CIFRE_MINUTI, '0')}`;
}

/**
 * 'h:mm' → ore decimali, arrotondate al centesimo.
 *
 * @param {string|null} hm — durata come 'h:mm'.
 * @returns {number|null} ore decimali, null se il campo e' vuoto.
 */
export function hmToDec(hm) {
    if (!hm || !hm.trim()) return null;

    const parti = hm.trim().split(':');
    const ore = parseInt(parti[0]) || 0;
    const minuti = parseInt(parti[1]) || 0;

    return Math.round((ore + minuti / MINUTI_PER_ORA) * 100) / 100;
}

/**
 * Minuti interi → 'h:mm'.
 *
 * @param {number|null} minuti — durata in minuti.
 * @returns {string} 'h:mm', stringa vuota se il valore manca.
 */
export function minToHm(minuti) {
    if (minuti == null || minuti === '') return '';

    const totale = parseInt(minuti);
    if (isNaN(totale)) return '';

    const ore = Math.floor(totale / MINUTI_PER_ORA);

    return `${ore}:${String(totale % MINUTI_PER_ORA).padStart(CIFRE_MINUTI, '0')}`;
}

/**
 * 'h:mm' → minuti interi.
 *
 * @param {string|null} hm — durata come 'h:mm'.
 * @returns {number|null} minuti, null se il campo e' vuoto.
 */
export function hmToMin(hm) {
    if (!hm || !hm.trim()) return null;

    const parti = hm.trim().split(':');
    const ore = parseInt(parti[0]) || 0;
    const minuti = parseInt(parti[1]) || 0;

    return ore * MINUTI_PER_ORA + minuti;
}
