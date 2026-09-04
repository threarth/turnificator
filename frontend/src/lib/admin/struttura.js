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
// Le tipologie non stanno qui: le sceglie l'utente turno per turno.
const TURNO_DEFAULT = {
    priorita_solver: 'automatico',
    peso_priorita_solver: 50,
    apri_festivi: 0,
    apri_superfestivi: 0,
    is_disabled: 0,
    is_hidden: 0,
};

const LUNGHEZZA_MAX_SIGLA = 8;

// Suffisso dato alla copia di un turno il cui nome non finisce con un numero
// e non nomina la sua fascia: "Guardia" diventa "Guardia 2".
const SUFFISSO_COPIA = ' 2';

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
 * @param {object} struttura — {nome, ambito, turni: [{nome, flag_id,
 *                              tipi_qualitativi}]}.
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
            tipi_qualitativi: [...(turno.tipi_qualitativi ?? [])],
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
            escluso_solver: s.escluso_solver ? 1 : 0,
            gruppi: gruppiDellaStruttura(s, fasce, nuovoId),
        }));
}


/**
 * Appiattisce la struttura del database nel modello della procedura guidata.
 *
 * Il database la tiene su tre livelli — struttura, gruppo, turno — mentre il
 * wizard ne mostra due: il gruppo e' la fascia oraria, e qui torna a essere
 * un attributo del turno. E' l'operazione inversa di costruisciStruttura().
 *
 * @param {Array} sovragruppi — come li restituisce l'API della struttura.
 * @returns {Array} strutture nel modello piatto del wizard.
 */
export function appiattisciStruttura(sovragruppi) {
    return (sovragruppi ?? []).map(sg => ({
        id: sg.id,
        nome: sg.nome ?? '',
        ambito: sg.ambito ?? '',
        escluso_solver: sg.escluso_solver ? 1 : 0,
        turni: (sg.gruppi ?? []).flatMap(g =>
            (g.turni ?? []).map(t => ({
                nome: t.nome ?? '',
                flag_id: g.flag_id,
                tipi_qualitativi: (t.tipi_qualitativi ?? []).map(q => q?.id ?? q),
            }))
        ),
    }));
}


/**
 * Propone il nome per la copia di un turno.
 *
 * La copia in un'altra fascia e' gia' un turno diverso — la sigla porta in
 * coda quella della fascia, quindi TC_MATTINA e TC_POMERIGGIO si distinguono
 * da soli — e il nome resta com'e'. Fa eccezione il nome che cita la fascia
 * di partenza: "TC mattina" duplicato nel pomeriggio diventa "TC pomeriggio".
 *
 * Nella stessa fascia invece i due turni si somiglierebbero in tutto, quindi
 * il nome va distinto: "DEA1" diventa "DEA2", "Guardia" diventa "Guardia 2".
 *
 * @param {string} nome — nome del turno originale.
 * @param {string} fasciaOrigine — nome della fascia di partenza.
 * @param {string} fasciaDestinazione — nome della fascia della copia.
 * @returns {string} nome proposto, comunque modificabile dall'utente.
 */
export function nomeDuplicato(nome, fasciaOrigine = '', fasciaDestinazione = '') {
    const originale = (nome ?? '').trim();

    if (fasciaDestinazione && fasciaDestinazione !== fasciaOrigine) {
        return sostituisciNomeFascia(originale, fasciaOrigine, fasciaDestinazione) ?? originale;
    }

    const numeroFinale = originale.match(/^(.*?)(\d+)$/);
    if (numeroFinale) {
        const [, radice, cifre] = numeroFinale;
        const successivo = String(Number(cifre) + 1);
        // Conserva gli zeri iniziali: "T01" continua con "T02".
        return radice + successivo.padStart(cifre.length, '0');
    }

    return originale + SUFFISSO_COPIA;
}

/**
 * Sostituisce nel nome il riferimento a una fascia con quello di un'altra.
 *
 * Rispetta l'iniziale maiuscola di quello che trova, cosi' "TC Mattina"
 * diventa "TC Pomeriggio" e "tc mattina" diventa "tc pomeriggio".
 *
 * @returns {string|null} il nome nuovo, o null se la fascia non e' nominata.
 */
function sostituisciNomeFascia(nome, fasciaOrigine, fasciaDestinazione) {
    if (!fasciaOrigine) return null;

    const posizione = nome.toLowerCase().indexOf(fasciaOrigine.toLowerCase());
    if (posizione < 0) return null;

    const trovato = nome.slice(posizione, posizione + fasciaOrigine.length);
    const iniziale = trovato[0];
    const sostituto = iniziale === iniziale.toUpperCase() && iniziale !== iniziale.toLowerCase()
        ? fasciaDestinazione[0].toUpperCase() + fasciaDestinazione.slice(1)
        : fasciaDestinazione;

    return nome.slice(0, posizione) + sostituto + nome.slice(posizione + fasciaOrigine.length);
}

