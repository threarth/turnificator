/**
 * lib/riepilogo.js — i conteggi del riepilogo sotto il calendario.
 *
 * Nuova feature. Una sola passata sulle assegnazioni produce tutti i blocchi:
 * turni feriali e festivi, solo weekend, globale, per struttura, per
 * settimana. Sta nel browser perche' i dati sono gia' tutti li': il riepilogo
 * si aggiorna mentre si costruisce il turno, senza tornare al server.
 *
 * Due regole valgono ovunque:
 *
 * - **Si contano i pesi, non le righe.** Una notte o una lunga valgono due
 *   turni tipo, ed e' cosi' che il solver confronta il fatto con il dovuto:
 *   contare le righe darebbe due numeri diversi per la stessa cosa.
 * - **La notte scavalca la mezzanotte.** Le ore del weekend si spezzano sui
 *   due giorni, ricavandolo dagli orari della fascia: se l'ora di fine e'
 *   minore di quella di inizio, la fascia scavalca.
 *
 * Convenzione del giorno della settimana: `0 = domenica`, come `Date.getDay()`
 * e come il resto della pagina manager. Nel solver e in calendario_giorni vale
 * l'altra, `0 = lunedi'`: le due convivono, e unificarle tocca dati salvati.
 */

import { eNotturna } from './fasceOrarie.js';

/** Giorni della settimana secondo Date.getDay(). */
const DOMENICA = 0;
const SABATO = 6;

const MINUTI_PER_ORA = 60;
const MINUTI_PER_GIORNO = 24 * MINUTI_PER_ORA;

/** Un turno vale «lungo» da qui in su: due turni tipo, cioe' circa 12 ore. */
const PESO_TURNO_LUNGO = 2;

/** Tipi di giorno che non sono feriali. */
const GIORNI_FESTIVI = ['festivo', 'superfestivo'];


/**
 * Converte 'HH:MM' in minuti dalla mezzanotte.
 *
 * @param {?string} orario
 * @returns {?number} minuti, o null se l'orario manca o non si legge
 */
function inMinuti(orario) {
    if (!orario) return null;

    const [ore, minuti] = String(orario).split(':');
    const h = Number(ore);
    const m = Number(minuti ?? 0);
    if (!Number.isFinite(h) || !Number.isFinite(m)) return null;

    return h * MINUTI_PER_ORA + m;
}

/**
 * Come si spartiscono i minuti di una fascia fra il giorno in cui comincia e
 * quello dopo.
 *
 * La pausa sta dove finisce il turno: per la notte 20:00-08:40 con 10 minuti
 * di pausa sono 240 minuti sul giorno di inizio e 530 su quello dopo.
 *
 * @param {?object} fascia riga flag_turno con orario_inizio, orario_fine, pausa_minuti
 * @returns {{primoGiorno: number, giornoDopo: number}} minuti, 0 se la fascia non ha orari
 */
export function ripartizioneMinuti(fascia) {
    const inizio = inMinuti(fascia?.orario_inizio);
    const fine = inMinuti(fascia?.orario_fine);
    const pausa = Number(fascia?.pausa_minuti ?? 0) || 0;

    if (inizio == null || fine == null) return { primoGiorno: 0, giornoDopo: 0 };

    if (fine > inizio) {
        return { primoGiorno: fine - inizio + pausa, giornoDopo: 0 };
    }

    // Scavalca la mezzanotte: fino alle 24 sul giorno di inizio, il resto dopo.
    const primaDiMezzanotte = MINUTI_PER_GIORNO - inizio;

    return { primoGiorno: primaDiMezzanotte, giornoDopo: fine + pausa };
}

/**
 * Divide il mese in settimane da lunedi' a domenica, tagliate ai bordi.
 *
 * @param {Array<{giorno: number, is_lavorativo: ?number}>} giorni giorni del calendario
 * @param {function(number): number} dow giorno → giorno della settimana (0=Dom)
 * @returns {Array<{dal: number, al: number, etichetta: string, dovuti: number}>}
 */
export function settimaneDelMese(giorni, dow) {
    const settimane = [];
    let corrente = null;

    for (const g of giorni) {
        // Lunedi' apre una settimana nuova; il primo giorno del mese pure,
        // anche quando cade a meta' settimana.
        const lunedi = dow(g.giorno) === 1;
        if (!corrente || lunedi) {
            corrente = { dal: g.giorno, al: g.giorno, dovuti: 0 };
            settimane.push(corrente);
        }
        corrente.al = g.giorno;
        if (g.is_lavorativo) corrente.dovuti += 1;
    }

    for (const s of settimane) {
        s.etichetta = `${String(s.dal).padStart(2, '0')} - ${String(s.al).padStart(2, '0')}`;
    }

    return settimane;
}

/** La riga vuota di un lavoratore: tutti i conteggi a zero. */
function rigaVuota(utente, numeroSettimane) {
    return {
        user_id: utente.id,
        sigla: utente.sigla,
        nottiFeriali: 0,
        nottiFestive: 0,
        giorniFeriali: 0,
        giorniFestivi: 0,
        lunghe: {},
        diurniWeekend: 0,
        nottiSabato: 0,
        nottiDomenica: 0,
        oreWeekend: 0,
        perStruttura: {},
        perSettimana: new Array(numeroSettimane).fill(0),
        lavorati: 0,
        giustificate: 0,
        totale: 0,
    };
}

/** Appiattisce la gerarchia in una lista di turni, ciascuno con la sua struttura. */
function turniPiatti(sovragruppi) {
    const turni = [];
    for (const sg of sovragruppi ?? []) {
        for (const gruppo of sg.gruppi ?? []) {
            for (const t of gruppo.turni ?? []) {
                turni.push({ ...t, sg_id: sg.id, sg_nome: sg.nome, sg_sigla: sg.sigla });
            }
        }
    }

    return turni;
}

/**
 * Somma un'assegnazione dentro la riga del lavoratore.
 *
 * @param {object} riga riga da aggiornare, modificata sul posto
 * @param {object} ctx  { turno, giorno, festivo, notturna, peso, fascia, dow, settimana }
 */
function sommaAssegnazione(riga, ctx) {
    const { turno, giorno, festivo, notturna, peso, fascia, dow, settimana } = ctx;

    if (notturna) {
        if (festivo) riga.nottiFestive += peso;
        else riga.nottiFeriali += peso;
    } else {
        if (festivo) riga.giorniFestivi += peso;
        else riga.giorniFeriali += peso;
        if (peso >= PESO_TURNO_LUNGO && turno.flag_nome) {
            riga.lunghe[turno.flag_nome] = (riga.lunghe[turno.flag_nome] ?? 0) + peso;
        }
    }

    const gds = dow(giorno);
    if (gds === SABATO || gds === DOMENICA) {
        if (!notturna) riga.diurniWeekend += peso;
        else if (gds === SABATO) riga.nottiSabato += peso;
        else riga.nottiDomenica += peso;
    }

    // Ore del weekend: la parte di turno che cade di sabato o domenica.
    const parti = ripartizioneMinuti(fascia);
    let minuti = 0;
    if (gds === SABATO || gds === DOMENICA) minuti += parti.primoGiorno;
    const domani = dow(giorno + 1);
    if (parti.giornoDopo && (domani === SABATO || domani === DOMENICA)) {
        minuti += parti.giornoDopo;
    }
    riga.oreWeekend += minuti / MINUTI_PER_ORA;

    if (turno.sg_id != null) {
        riga.perStruttura[turno.sg_id] = (riga.perStruttura[turno.sg_id] ?? 0) + peso;
    }
    if (settimana >= 0) riga.perSettimana[settimana] += peso;
    riga.lavorati += peso;
}

/** Per ogni giorno del mese, l'indice della settimana che lo contiene. */
function indiceSettimane(settimane) {
    const indice = {};
    settimane.forEach((s, i) => {
        for (let g = s.dal; g <= s.al; g += 1) indice[g] = i;
    });

    return indice;
}

/**
 * Conta le assenze giustificate di ogni lavoratore.
 *
 * Contano solo le richieste di assenza con `counting_flag` acceso — il ROMC
 * non conta — e solo nei giorni lavorativi: un'assenza in un festivo non
 * copre un turno che non era dovuto.
 *
 * @param {Array} desiderata working desiderata, con user_id, giorno, tipo_richiesta_id
 * @param {Array} tipiRichiesta tipi dallo snapshot, con tipo e counting_flag
 * @param {object} giornoLavorativo giorno → boolean
 * @returns {object} user_id → quante
 */
function assenzeGiustificate(desiderata, tipiRichiesta, giornoLavorativo) {
    const contabili = new Set(
        (tipiRichiesta ?? [])
            .filter(t => t.tipo === 'assenza' && t.counting_flag)
            .map(t => t.id)
    );

    const per_utente = {};
    for (const d of desiderata ?? []) {
        if (!contabili.has(d.tipo_richiesta_id)) continue;
        if (!giornoLavorativo[d.giorno]) continue;
        per_utente[d.user_id] = (per_utente[d.user_id] ?? 0) + 1;
    }

    return per_utente;
}

/**
 * Calcola tutti i blocchi del riepilogo.
 *
 * @param {object} dati
 * @param {Array}  dati.sovragruppi   gerarchia del calendario
 * @param {Array}  dati.giorni        [{giorno, is_lavorativo, tipo}]
 * @param {object} dati.assegnazioni  `${turno_id}-${giorno}` → {user_id}
 * @param {Array}  dati.utenti        [{id, sigla}], nell'ordine da mostrare
 * @param {Array}  dati.desiderata    working desiderata
 * @param {Array}  dati.tipiRichiesta tipi richiesta dello snapshot
 * @param {Array}  dati.fasce         flag_turno dello snapshot, con gli orari
 * @param {Map}    dati.mappaFlag     gerarchia dei flag, per riconoscere le notti
 * @param {function(number): number} dati.dow giorno → giorno della settimana (0=Dom)
 * @returns {object} { turniDovuti, settimane, strutture, fasceLunghe, righe }
 */
export function calcolaRiepilogo(dati) {
    const { sovragruppi, giorni, assegnazioni, utenti, desiderata,
            tipiRichiesta, fasce, mappaFlag, dow } = dati;

    const settimane = settimaneDelMese(giorni ?? [], dow);
    const dellaSettimana = indiceSettimane(settimane);
    const tipoGiorno = {};
    const giornoLavorativo = {};
    for (const g of giorni ?? []) {
        tipoGiorno[g.giorno] = g.tipo ?? 'normale';
        giornoLavorativo[g.giorno] = !!g.is_lavorativo;
    }

    const fasciaPerId = new Map((fasce ?? []).map(f => [f.id, f]));
    const turni = turniPiatti(sovragruppi);
    const righe = new Map((utenti ?? []).map(u => [u.id, rigaVuota(u, settimane.length)]));

    for (const turno of turni) {
        const peso = turno.peso_turno ?? 1;
        const notturna = eNotturna(turno.flag_nome, mappaFlag);
        const fascia = fasciaPerId.get(turno.flag_id);

        for (const g of giorni ?? []) {
            const riga = righe.get(assegnazioni[`${turno.id}-${g.giorno}`]?.user_id);
            if (!riga) continue;

            sommaAssegnazione(riga, {
                turno, giorno: g.giorno, peso, notturna, fascia, dow,
                festivo: GIORNI_FESTIVI.includes(tipoGiorno[g.giorno]),
                settimana: dellaSettimana[g.giorno] ?? -1,
            });
        }
    }

    const giustificate = assenzeGiustificate(desiderata, tipiRichiesta, giornoLavorativo);
    for (const riga of righe.values()) {
        riga.giustificate = giustificate[riga.user_id] ?? 0;
        riga.totale = riga.lavorati + riga.giustificate;
    }

    const elenco = [...righe.values()];

    return {
        turniDovuti: settimane.reduce((somma, s) => somma + s.dovuti, 0),
        settimane,
        strutture: strutturePresenti(sovragruppi),
        fasceLunghe: fasceLunghePresenti(elenco),
        righe: elenco,
    };
}

/** Le strutture in colonna, nell'ordine della griglia. */
function strutturePresenti(sovragruppi) {
    return (sovragruppi ?? []).map(sg => ({
        id: sg.id, nome: sg.nome, sigla: sg.sigla,
    }));
}

/**
 * I nomi delle fasce lunghe effettivamente assegnate.
 *
 * Il blocco non ha una riga «turni 12h» inchiodata: la fascia che vale due
 * turni si chiama come l'ha chiamata chi configura, e con quel nome compare.
 *
 * @param {Array} righe righe gia' calcolate
 * @returns {Array<string>} nomi, in ordine alfabetico
 */
function fasceLunghePresenti(righe) {
    const nomi = new Set();
    for (const riga of righe) {
        for (const nome of Object.keys(riga.lunghe)) nomi.add(nome);
    }

    return [...nomi].sort();
}
