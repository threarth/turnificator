/**
 * lib/regole.js — i tipi di regola conflitto, con i loro nomi leggibili.
 *
 * Estrazione: nessun comportamento nuovo. Gemello lato client delle costanti
 * in app/services/validatori.py, che stavano scritte a mano in tre punti per
 * pagina, in due pagine: un tipo nuovo ne mancava sempre uno, e la riga
 * finiva etichettata come qualcos'altro.
 *
 * `breve` e' per le tabelle strette, `esteso` per i menu a tendina.
 */

export const TIPO_REGOLA_TIPO_VS_TIPO = 'tipo_vs_tipo';
export const TIPO_REGOLA_DESIDERATA_MISMATCH = 'desiderata_mismatch';
export const TIPO_REGOLA_DESIDERATA_ASSENZA = 'desiderata_assenza_mismatch';
export const TIPO_REGOLA_COMPOSIZIONE_PARZIALE = 'desiderata_composizione_parziale';

/** I tipi nell'ordine in cui conviene proporli, dal piu' usato. */
export const TIPI_REGOLA = [
    {
        valore: TIPO_REGOLA_TIPO_VS_TIPO,
        breve: 'T vs T',
        esteso: 'Tipo vs Tipo',
    },
    {
        valore: TIPO_REGOLA_DESIDERATA_MISMATCH,
        breve: 'Des.',
        esteso: 'Desiderata mismatch',
    },
    {
        valore: TIPO_REGOLA_DESIDERATA_ASSENZA,
        breve: 'Ass.',
        esteso: 'Assenza mismatch',
    },
    {
        valore: TIPO_REGOLA_COMPOSIZIONE_PARZIALE,
        breve: 'Parz.',
        esteso: 'Composizione incompleta',
    },
];

/**
 * L'etichetta breve di un tipo di regola, per le celle strette.
 *
 * @param {?string} tipo valore della colonna tipo_regola
 * @returns {string} etichetta, o il valore stesso se il tipo e' sconosciuto
 */
export function etichettaBreve(tipo) {
    return TIPI_REGOLA.find(t => t.valore === tipo)?.breve ?? (tipo ?? '');
}
