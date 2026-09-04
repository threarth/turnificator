/**
 * Test delle etichette dei tipi di regola conflitto (src/lib/regole.js).
 *
 * Girano con il test runner incluso in Node: `npm test` dentro frontend/.
 * Nessuna dipendenza aggiuntiva.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
    TIPI_REGOLA, TIPO_REGOLA_COMPOSIZIONE_PARZIALE, TIPO_REGOLA_TIPO_VS_TIPO,
    etichettaBreve
} from '../src/lib/regole.js';


test('ogni tipo di regola ha entrambe le etichette', () => {
    for (const t of TIPI_REGOLA) {
        assert.ok(t.valore, 'manca il valore');
        assert.ok(t.breve, `manca l'etichetta breve di ${t.valore}`);
        assert.ok(t.esteso, `manca l'etichetta estesa di ${t.valore}`);
    }
});

test('i valori dei tipi non si ripetono', () => {
    const valori = TIPI_REGOLA.map(t => t.valore);

    assert.equal(new Set(valori).size, valori.length);
});

test('etichettaBreve traduce i tipi noti', () => {
    assert.equal(etichettaBreve(TIPO_REGOLA_TIPO_VS_TIPO), 'T vs T');
    assert.equal(etichettaBreve(TIPO_REGOLA_COMPOSIZIONE_PARZIALE), 'Parz.');
});

test('un tipo sconosciuto si mostra com\'e\', non come un altro', () => {
    // La riga etichettata a caso e' peggio della riga con un nome tecnico:
    // e' il motivo per cui questa tabella e' diventata un modulo solo.
    assert.equal(etichettaBreve('tipo_inventato'), 'tipo_inventato');
    assert.equal(etichettaBreve(null), '');
});
