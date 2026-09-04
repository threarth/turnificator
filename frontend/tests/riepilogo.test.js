/**
 * Test dei conteggi del riepilogo sotto il calendario (src/lib/riepilogo.js).
 *
 * Girano con il test runner incluso in Node: `npm test` dentro frontend/.
 * Nessuna dipendenza aggiuntiva.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { calcolaRiepilogo, ripartizioneMinuti, settimaneDelMese }
    from '../src/lib/riepilogo.js';
import { costruisciMappaFlag } from '../src/lib/fasceOrarie.js';


// Aprile 2026, come nel foglio d'esempio: il 1 e' un mercoledi', il 5 e'
// Pasqua e il 6 Pasquetta.
const ANNO = 2026;
const MESE = 4;
const GIORNI_DEL_MESE = 30;

/** Giorno del mese → giorno della settimana, con la convenzione 0=Dom. */
function dow(giorno) {
    return new Date(ANNO, MESE - 1, giorno).getDay();
}

// Gerarchia dei flag: i concetti e le fasce che ne discendono.
const FLAG = [
    { id: 1, nome: 'diurno',   parent_id: null },
    { id: 2, nome: 'notturno', parent_id: null },
    { id: 11, nome: 'mattina', parent_id: 1, orario_inizio: '08:00', orario_fine: '14:20', pausa_minuti: 10 },
    { id: 12, nome: 'lunga',   parent_id: 1, orario_inizio: '08:00', orario_fine: '20:40', pausa_minuti: 10 },
    { id: 13, nome: 'notte',   parent_id: 2, orario_inizio: '20:00', orario_fine: '08:40', pausa_minuti: 10 },
];
const MAPPA_FLAG = costruisciMappaFlag(FLAG);

const SOVRAGRUPPI = [
    {
        id: 1, sigla: 'DEA', nome: 'DEA',
        gruppi: [{
            id: 1,
            turni: [
                { id: 101, flag_nome: 'mattina', flag_id: 11, peso_turno: 1 },
                { id: 102, flag_nome: 'notte',   flag_id: 13, peso_turno: 2 },
                { id: 103, flag_nome: 'lunga',   flag_id: 12, peso_turno: 2 },
            ],
        }],
    },
    {
        id: 2, sigla: 'TC', nome: 'TC S.G.',
        gruppi: [{
            id: 2,
            turni: [{ id: 201, flag_nome: 'mattina', flag_id: 11, peso_turno: 1 }],
        }],
    },
];

const UTENTI = [
    { id: 7, sigla: 'GUERR' },
    { id: 8, sigla: 'ASSAE' },
];

// I giorni del mese: festivi la domenica, piu' Pasqua (5), Pasquetta (6) e
// la Liberazione (25), che nel 2026 cade di sabato. Sono gli stessi del
// foglio d'esempio, e per questo i dovuti tornano ai suoi numeri.
const FESTIVI = new Set([5, 6, 25]);

function giorniDelMese() {
    const giorni = [];
    for (let g = 1; g <= GIORNI_DEL_MESE; g += 1) {
        const domenica = dow(g) === 0;
        const festivo = domenica || FESTIVI.has(g);
        giorni.push({
            giorno: g,
            is_lavorativo: festivo ? 0 : 1,
            tipo: festivo ? 'festivo' : 'normale',
        });
    }

    return giorni;
}

const TIPI_RICHIESTA = [
    { id: 1, sigla: 'CO',   tipo: 'assenza',    counting_flag: 1 },
    { id: 2, sigla: 'ROMC', tipo: 'assenza',    counting_flag: 0 },
    { id: 3, sigla: 'M',    tipo: 'lavorativo', counting_flag: 1 },
];

/** Costruisce l'input di calcolaRiepilogo, con le assegnazioni date. */
function riepilogo({ assegnazioni = {}, desiderata = [] } = {}) {
    return calcolaRiepilogo({
        sovragruppi: SOVRAGRUPPI,
        giorni: giorniDelMese(),
        assegnazioni,
        utenti: UTENTI,
        desiderata,
        tipiRichiesta: TIPI_RICHIESTA,
        fasce: FLAG,
        mappaFlag: MAPPA_FLAG,
        dow,
    });
}

/** La riga di un lavoratore, per sigla. */
function riga(esito, sigla) {
    return esito.righe.find(r => r.sigla === sigla);
}


// ---------------------------------------------------------------------------
// Ripartizione dei minuti sulla mezzanotte
// ---------------------------------------------------------------------------

test('una fascia che sta nel giorno tiene tutti i suoi minuti', () => {
    const parti = ripartizioneMinuti(FLAG[2]);  // mattina 08:00-14:20 + 10

    assert.deepEqual(parti, { primoGiorno: 390, giornoDopo: 0 });
});

test('la notte si spezza sui due giorni, con la pausa in coda', () => {
    // 20:00-08:40 con 10 di pausa: 4 ore prima di mezzanotte, 8h40 + 10 dopo.
    const parti = ripartizioneMinuti(FLAG[4]);

    assert.deepEqual(parti, { primoGiorno: 240, giornoDopo: 530 });
});

test('i due pezzi sommano la durata totale della fascia', () => {
    const parti = ripartizioneMinuti(FLAG[4]);

    assert.equal(parti.primoGiorno + parti.giornoDopo, 760 + 10);
});

test('una fascia senza orari non ha minuti da spartire', () => {
    assert.deepEqual(ripartizioneMinuti({}), { primoGiorno: 0, giornoDopo: 0 });
    assert.deepEqual(ripartizioneMinuti(null), { primoGiorno: 0, giornoDopo: 0 });
});


// ---------------------------------------------------------------------------
// Settimane
// ---------------------------------------------------------------------------

test('le settimane vanno da lunedi a domenica, tagliate ai bordi del mese', () => {
    const settimane = settimaneDelMese(giorniDelMese(), dow);

    assert.deepEqual(settimane.map(s => s.etichetta),
                     ['01 - 05', '06 - 12', '13 - 19', '20 - 26', '27 - 30']);
});

test('i dovuti di una settimana sono i suoi giorni lavorativi', () => {
    const settimane = settimaneDelMese(giorniDelMese(), dow);

    // Come nel foglio: la prima settimana e' mer-sab (Pasqua non conta), la
    // seconda perde Pasquetta e la domenica.
    assert.deepEqual(settimane.map(s => s.dovuti), [4, 5, 6, 5, 4]);
});

test('i turni dovuti del mese sono la somma delle settimane', () => {
    const esito = riepilogo();

    assert.equal(esito.turniDovuti, 24);
});


// ---------------------------------------------------------------------------
// Conteggi per lavoratore
// ---------------------------------------------------------------------------

test('senza assegnazioni ogni lavoratore ha una riga a zero', () => {
    const esito = riepilogo();

    assert.equal(esito.righe.length, 2);
    assert.equal(riga(esito, 'GUERR').lavorati, 0);
    assert.deepEqual(riga(esito, 'GUERR').perSettimana, [0, 0, 0, 0, 0]);
});

test('un turno feriale e uno festivo finiscono in righe diverse', () => {
    // Il 1 e' un mercoledi' feriale, il 5 e' Pasqua.
    const esito = riepilogo({ assegnazioni: {
        '101-1': { user_id: 7 },
        '101-5': { user_id: 7 },
    } });

    const r = riga(esito, 'GUERR');
    assert.equal(r.giorniFeriali, 1);
    assert.equal(r.giorniFestivi, 1);
    assert.equal(r.lavorati, 2);
});

test('la notte pesa due turni, e sta fra le notti', () => {
    const esito = riepilogo({ assegnazioni: { '102-1': { user_id: 7 } } });

    const r = riga(esito, 'GUERR');
    assert.equal(r.nottiFeriali, 2);
    assert.equal(r.giorniFeriali, 0);
    assert.equal(r.lavorati, 2);
});

test('la fascia che vale due turni compare col suo nome', () => {
    const esito = riepilogo({ assegnazioni: { '103-1': { user_id: 7 } } });

    assert.deepEqual(esito.fasceLunghe, ['lunga']);
    assert.deepEqual(riga(esito, 'GUERR').lunghe, { lunga: 2 });
    // Resta anche fra i giorni feriali: e' un sottoinsieme, non un'altra cosa.
    assert.equal(riga(esito, 'GUERR').giorniFeriali, 2);
});

test('la mattina non e una fascia lunga', () => {
    const esito = riepilogo({ assegnazioni: { '101-1': { user_id: 7 } } });

    assert.deepEqual(esito.fasceLunghe, []);
    assert.deepEqual(riga(esito, 'GUERR').lunghe, {});
});


// ---------------------------------------------------------------------------
// Weekend
// ---------------------------------------------------------------------------

test('il diurno del sabato conta fra i turni di weekend', () => {
    // Il 4 aprile 2026 e' un sabato.
    assert.equal(dow(4), 6);
    const esito = riepilogo({ assegnazioni: { '101-4': { user_id: 7 } } });

    const r = riga(esito, 'GUERR');
    assert.equal(r.diurniWeekend, 1);
    assert.equal(r.nottiSabato, 0);
    assert.equal(r.oreWeekend, 390 / 60);
});

test('la notte del sabato e la notte della domenica stanno in righe diverse', () => {
    const esito = riepilogo({ assegnazioni: {
        '102-4': { user_id: 7 },   // sabato
        '102-5': { user_id: 7 },   // domenica
    } });

    const r = riga(esito, 'GUERR');
    assert.equal(r.nottiSabato, 2);
    assert.equal(r.nottiDomenica, 2);
    assert.equal(r.diurniWeekend, 0);
});

test('la notte del venerdi porta al sabato solo la parte dopo mezzanotte', () => {
    // Il 3 aprile 2026 e' un venerdi': 4 ore di venerdi', 8h40 + 10 di sabato.
    assert.equal(dow(3), 5);
    const esito = riepilogo({ assegnazioni: { '102-3': { user_id: 7 } } });

    const r = riga(esito, 'GUERR');
    assert.equal(r.oreWeekend, 530 / 60);
    assert.equal(r.nottiSabato, 0, 'la notte resta del venerdi, dove comincia');
});

test('la notte della domenica porta al lunedi la parte dopo mezzanotte', () => {
    // Domenica 5: le 4 ore prima di mezzanotte sono weekend, le altre no.
    const esito = riepilogo({ assegnazioni: { '102-5': { user_id: 7 } } });

    assert.equal(riga(esito, 'GUERR').oreWeekend, 240 / 60);
});

test('la notte dell ultimo giorno del mese non sconfina in un giorno che non c e', () => {
    // Il 30 aprile 2026 e' un giovedi': niente del turno cade nel weekend.
    const esito = riepilogo({ assegnazioni: { '102-30': { user_id: 7 } } });

    assert.equal(riga(esito, 'GUERR').oreWeekend, 0);
});


// ---------------------------------------------------------------------------
// Struttura, settimana, globale
// ---------------------------------------------------------------------------

test('i turni si dividono per struttura', () => {
    const esito = riepilogo({ assegnazioni: {
        '101-1': { user_id: 7 },   // DEA
        '201-2': { user_id: 7 },   // TC
        '201-3': { user_id: 7 },   // TC
    } });

    assert.deepEqual(esito.strutture.map(s => s.sigla), ['DEA', 'TC']);
    assert.deepEqual(riga(esito, 'GUERR').perStruttura, { 1: 1, 2: 2 });
});

test('i turni si dividono per settimana', () => {
    const esito = riepilogo({ assegnazioni: {
        '101-1': { user_id: 7 },    // prima settimana
        '101-2': { user_id: 7 },    // prima settimana
        '101-13': { user_id: 7 },   // terza
    } });

    assert.deepEqual(riga(esito, 'GUERR').perSettimana, [2, 0, 1, 0, 0]);
});

test('il totale e i lavorati piu le assenze giustificate', () => {
    const esito = riepilogo({
        assegnazioni: { '101-1': { user_id: 7 } },
        desiderata: [
            { user_id: 7, giorno: 2, tipo_richiesta_id: 1 },   // ferie, contano
            { user_id: 7, giorno: 3, tipo_richiesta_id: 2 },   // ROMC, non conta
        ],
    });

    const r = riga(esito, 'GUERR');
    assert.equal(r.lavorati, 1);
    assert.equal(r.giustificate, 1);
    assert.equal(r.totale, 2);
});

test('un assenza in un giorno festivo non copre un turno che non era dovuto', () => {
    const esito = riepilogo({ desiderata: [
        { user_id: 7, giorno: 5, tipo_richiesta_id: 1 },   // Pasqua
    ] });

    assert.equal(riga(esito, 'GUERR').giustificate, 0);
});

test('le assegnazioni di un lavoratore non finiscono nella riga di un altro', () => {
    const esito = riepilogo({ assegnazioni: {
        '101-1': { user_id: 7 },
        '201-1': { user_id: 8 },
    } });

    assert.equal(riga(esito, 'GUERR').lavorati, 1);
    assert.equal(riga(esito, 'ASSAE').lavorati, 1);
});

test('una cella vuota non conta per nessuno', () => {
    const esito = riepilogo({ assegnazioni: { '101-1': { user_id: null } } });

    assert.equal(riga(esito, 'GUERR').lavorati, 0);
    assert.equal(riga(esito, 'ASSAE').lavorati, 0);
});
