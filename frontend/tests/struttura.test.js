/**
 * Test della costruzione della struttura turni dal modello della procedura
 * guidata (src/lib/admin/struttura.js).
 *
 * Girano con il test runner incluso in Node: `npm test` dentro frontend/.
 * Nessuna dipendenza aggiuntiva.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { costruisciStruttura, gruppiDellaStruttura, toSigla }
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
