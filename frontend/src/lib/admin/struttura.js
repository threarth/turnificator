/**
 * Costruzione della struttura turni a partire dal modello della procedura
 * guidata.
 *
 * Il wizard tiene un modello piatto — struttura → turni, ogni turno con la
 * sua fascia oraria — perche' il gruppo e' un livello interno che l'utente
 * non deve incontrare. Il gruppo esiste comunque nel database: e' l'insieme
 * dei turni di una fascia dentro una struttura, e nasce qui.
 */

// Valori con cui nasce un turno: priorita' automatica, aperto nei soli giorni
// feriali, visibile. L'utente li rifinisce poi nell'editor della struttura.
const TURNO_DEFAULT = {
    tipi_qualitativi: [],
    priorita_solver: 'automatico',
    peso_priorita_solver: 50,
    apri_festivi: 0,
    apri_superfestivi: 0,
    is_disabled: 0,
    is_hidden: 0,
};

const LUNGHEZZA_MAX_SIGLA = 8;

/**
 * Ricava una sigla leggibile da un nome libero.
 *
 * @param {string} nome — nome inserito dall'utente.
 * @returns {string} sigla in maiuscolo, 'X' se non resta nulla.
 */
export function toSigla(nome) {
    return (nome || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, LUNGHEZZA_MAX_SIGLA) || 'X';
}

/**
 * Raggruppa i turni di una struttura per fascia oraria.
 *
 * E' qui che il gruppo nasce senza essere nominato: il primo turno di una
 * fascia lo crea, i successivi lo ritrovano. L'ordine e' quello degli orari,
 * cosi' la struttura si legge dalla mattina alla notte.
 *
 * I turni senza nome o senza fascia vengono ignorati: sono righe che l'utente
 * ha aperto e non ha compilato, non un errore da segnalare.
 *
 * @param {object} struttura — {nome, ambito, turni: [{nome, flag_id}]}.
 * @param {Array} fasce — flag_turno disponibili.
 * @param {Function} nuovoId — genera un id temporaneo non intero.
 * @returns {Array} gruppi pronti per l'API, in ordine di orario.
 */
export function gruppiDellaStruttura(struttura, fasce, nuovoId) {
    const perFascia = new Map();

    for (const turno of struttura.turni ?? []) {
        if (!turno.nome?.trim() || turno.flag_id == null) continue;

        if (!perFascia.has(turno.flag_id)) {
            const fascia = fasce.find(f => f.id === turno.flag_id);
            perFascia.set(turno.flag_id, {
                id: nuovoId(),
                sigla: toSigla(fascia?.nome),
                nome: fascia?.nome ?? '',
                flag_id: turno.flag_id,
                flag_nome: fascia?.nome ?? null,
                _orario_inizio: fascia?.orario_inizio ?? '',
                turni: [],
            });
        }

        const gruppo = perFascia.get(turno.flag_id);
        gruppo.turni.push({
            id: nuovoId(),
            sigla: `${toSigla(turno.nome)}_${gruppo.sigla}`,
            nome: turno.nome.trim(),
            ...TURNO_DEFAULT,
        });
    }

    return [...perFascia.values()]
        .sort((a, b) => a._orario_inizio.localeCompare(b._orario_inizio))
        .map(({ _orario_inizio, ...gruppo }) => gruppo);
}

/**
 * Traduce l'intero modello del wizard nella struttura attesa dall'API.
 *
 * Le strutture senza nome vengono scartate: sono righe vuote lasciate aperte.
 *
 * @param {Array} strutture — modello piatto del wizard.
 * @param {Array} fasce — flag_turno disponibili.
 * @param {Function} nuovoId — genera un id temporaneo non intero.
 * @returns {Array} struttura nel formato di PUT /struttura-presets/<id>/struttura.
 */
export function costruisciStruttura(strutture, fasce, nuovoId) {
    return strutture
        .filter(s => s.nome?.trim())
        .map(s => ({
            id: nuovoId(),
            sigla: toSigla(s.nome),
            nome: s.nome.trim(),
            ambito: (s.ambito ?? '').trim(),
            gruppi: gruppiDellaStruttura(s, fasce, nuovoId),
        }));
}
