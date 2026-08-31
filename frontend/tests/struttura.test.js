/**
 * Test della costruzione della struttura turni dal modello della procedura
 * guidata (src/lib/admin/struttura.js).
 *
 * Girano con il test runner incluso in Node: `npm test` dentro frontend/.
 * Nessuna dipendenza aggiuntiva.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { costruisciStruttura, gruppiDellaStruttura, nomeDuplicato, toSigla }
    from '../src/lib/admin/struttura.js';

// Fasce di riferimento, negli stessi orari del seed.
const FASCE = [
    { id: 11, nome: 'mattina',    orario_inizio: '08:00', orario_fine: '14:20' },
    { id: 12, nome: 'pomeriggio', orario_inizio: '14:00', orario_fine: '20:20' },
    { id: 14, nome: 'notte',      orario_inizio: '20:00', orario_fine: '08:40' },
];

/** Genera id temporanei prevedibili, come fa il wizard. */
function contatoreId() {
    let n = 0;
    return () => `w${++n}`;
}


test('toSigla tiene solo lettere e cifre, in maiuscolo', () => {
    assert.equal(toSigla('Radiologia Nord'), 'RADIOLOG');
    assert.equal(toSigla('TC-1'), 'TC1');
    assert.equal(toSigla('...'), 'X');
    assert.equal(toSigla(''), 'X');
});


test('due turni sulla stessa fascia finiscono in un gruppo solo', () => {
    const gruppi = gruppiDellaStruttura(
        { nome: 'Rad', turni: [
            { nome: 'TC mattina', flag_id: 11 },
            { nome: 'RM mattina', flag_id: 11 },
        ]},
        FASCE, contatoreId()
    );

    assert.equal(gruppi.length, 1);
    assert.equal(gruppi[0].flag_id, 11);
    assert.deepEqual(gruppi[0].turni.map(t => t.nome), ['TC mattina', 'RM mattina']);
});


test('fasce diverse danno gruppi diversi, in ordine di orario', () => {
    const gruppi = gruppiDellaStruttura(
        { nome: 'Rad', turni: [
            { nome: 'Notturno', flag_id: 14 },
            { nome: 'Diurno',   flag_id: 11 },
            { nome: 'Pomeri',   flag_id: 12 },
        ]},
        FASCE, contatoreId()
    );

    assert.deepEqual(gruppi.map(g => g.flag_nome), ['mattina', 'pomeriggio', 'notte']);
});


test('i turni incompleti non creano gruppi', () => {
    const gruppi = gruppiDellaStruttura(
        { nome: 'Rad', turni: [
            { nome: '   ',    flag_id: 11 },
            { nome: 'Senza',  flag_id: null },
            { nome: 'Valido', flag_id: 12 },
        ]},
        FASCE, contatoreId()
    );

    assert.equal(gruppi.length, 1);
    assert.equal(gruppi[0].flag_nome, 'pomeriggio');
});


test("l'orario usato per ordinare non finisce nel payload", () => {
    const [gruppo] = gruppiDellaStruttura(
        { nome: 'Rad', turni: [{ nome: 'TC', flag_id: 11 }] },
        FASCE, contatoreId()
    );

    assert.ok(!('_orario_inizio' in gruppo));
});


test('le strutture senza nome vengono scartate', () => {
    const struttura = costruisciStruttura(
        [
            { nome: 'Radiologia', turni: [{ nome: 'TC', flag_id: 11 }] },
            { nome: '  ',         turni: [{ nome: 'Fantasma', flag_id: 11 }] },
        ],
        FASCE, contatoreId()
    );

    assert.equal(struttura.length, 1);
    assert.equal(struttura[0].nome, 'Radiologia');
});


test('le sigle derivano dai nomi, con il gruppo in coda al turno', () => {
    const [sg] = costruisciStruttura(
        [{ nome: 'Radiologia Nord', ambito: ' Radiologia ', turni: [
            { nome: 'TC mattina', flag_id: 11 },
        ]}],
        FASCE, contatoreId()
    );

    assert.equal(sg.sigla, 'RADIOLOG');
    assert.equal(sg.ambito, 'Radiologia');
    assert.equal(sg.gruppi[0].sigla, 'MATTINA');
    assert.equal(sg.gruppi[0].turni[0].sigla, 'TCMATTIN_MATTINA');
});


test('gli id sono stringhe: il server li riconosce come entita nuove', () => {
    const [sg] = costruisciStruttura(
        [{ nome: 'Rad', turni: [{ nome: 'TC', flag_id: 11 }] }],
        FASCE, contatoreId()
    );

    for (const id of [sg.id, sg.gruppi[0].id, sg.gruppi[0].turni[0].id]) {
        assert.equal(typeof id, 'string');
        assert.ok(!Number.isInteger(Number(id)));
    }
});


test('un turno nuovo nasce automatico, feriale e visibile', () => {
    const [sg] = costruisciStruttura(
        [{ nome: 'Rad', turni: [{ nome: 'TC', flag_id: 11 }] }],
        FASCE, contatoreId()
    );
    const turno = sg.gruppi[0].turni[0];

    assert.equal(turno.priorita_solver, 'automatico');
    assert.equal(turno.apri_festivi, 0);
    assert.equal(turno.is_hidden, 0);
    assert.deepEqual(turno.tipi_qualitativi, []);
});


// ---------------------------------------------------------------------------
// Nome proposto per la copia di un turno
// ---------------------------------------------------------------------------

test('duplicando nella stessa fascia il numero finale avanza', () => {
    assert.equal(nomeDuplicato('DEA1', 'mattina', 'mattina'), 'DEA2');
    assert.equal(nomeDuplicato('DEA 9', 'mattina', 'mattina'), 'DEA 10');
});


test('gli zeri iniziali del numero si conservano', () => {
    assert.equal(nomeDuplicato('T01', 'mattina', 'mattina'), 'T02');
    assert.equal(nomeDuplicato('T09', 'mattina', 'mattina'), 'T10');
});


test('senza numero finale la copia prende il 2', () => {
    assert.equal(nomeDuplicato('Guardia', 'notte', 'notte'), 'Guardia 2');
});


test('cambiando fascia il nome segue la fascia nuova', () => {
    assert.equal(nomeDuplicato('TC mattina', 'mattina', 'pomeriggio'), 'TC pomeriggio');
});


test("la maiuscola iniziale della fascia nominata viene rispettata", () => {
    assert.equal(nomeDuplicato('TC Mattina', 'mattina', 'pomeriggio'), 'TC Pomeriggio');
});


test('cambiando fascia il nome che non la cita resta intatto', () => {
    // La sigla porta in coda quella della fascia: i due turni si distinguono
    // gia' da sola, non serve numerarli.
    assert.equal(nomeDuplicato('Guardia', 'mattina', 'notte'), 'Guardia');
    assert.equal(nomeDuplicato('Guardia1', 'mattina', 'notte'), 'Guardia1');
});


test('il nome vuoto o assente non manda in errore la duplicazione', () => {
    assert.equal(nomeDuplicato('', 'mattina', 'mattina'), ' 2');
    assert.equal(nomeDuplicato(null, 'mattina', 'pomeriggio'), '');
});



// ---------------------------------------------------------------------------
// Le tipologie scelte per un turno
// ---------------------------------------------------------------------------

test('le tipologie scelte arrivano al turno', () => {
    const [sg] = costruisciStruttura(
        [{ nome: 'Rad', turni: [
            { nome: 'TC mattina', flag_id: 11, tipi_qualitativi: [4, 7] },
        ]}],
        FASCE, contatoreId()
    );

    assert.deepEqual(sg.gruppi[0].turni[0].tipi_qualitativi, [4, 7]);
});


test('un turno senza tipologie ne ha una lista vuota, non undefined', () => {
    const [sg] = costruisciStruttura(
        [{ nome: 'Rad', turni: [{ nome: 'Guardia', flag_id: 14 }] }],
        FASCE, contatoreId()
    );

    assert.deepEqual(sg.gruppi[0].turni[0].tipi_qualitativi, []);
});


test('le tipologie di un turno non si condividono per riferimento', () => {
    // Due turni dalla stessa lista non devono finire a puntare lo stesso array.
    const scelte = [4];
    const [sg] = costruisciStruttura(
        [{ nome: 'Rad', turni: [
            { nome: 'A', flag_id: 11, tipi_qualitativi: scelte },
            { nome: 'B', flag_id: 11, tipi_qualitativi: scelte },
        ]}],
        FASCE, contatoreId()
    );

    const [a, b] = sg.gruppi[0].turni;
    a.tipi_qualitativi.push(9);

    assert.deepEqual(b.tipi_qualitativi, [4]);
    assert.deepEqual(scelte, [4]);
});
