/**
 * solver_turni.ts — il riempimento automatico della griglia dei turni.
 *
 * Office Script per Excel. Legge le tabelle di configurazione di
 * `modello_config.xlsx`, decide chi va dove e scrive gli acronimi nelle
 * celle del foglio Calendario.
 *
 * Regola di ingaggio: il solver **non tocca le celle gia' scritte**. Chi
 * programma mette a mano i turni che vuole decidere lui, lancia il
 * solver, e quello riempie il resto. Rilanciarlo non disfa niente.
 *
 * L'ordine in cui lavora:
 *   1. i turni fissi, che sono decisi in partenza
 *   2. i turni obbligatori, dal piu' necessario
 *   3. i turni opzionali, finche' c'e' gente disponibile
 *
 * Per ogni cella sceglie fra le persone ammissibili quella con il
 * punteggio migliore: chi ha chiesto quella fascia, chi e' indietro con i
 * turni dovuti, chi lavora nel proprio presidio.
 */

// ---------------------------------------------------------------------
// Costanti
// ---------------------------------------------------------------------

/** I fogli e le tabelle da cui si legge. */
const FOGLIO_CALENDARIO = "Calendario";
const FOGLIO_DESIDERATA = "Desiderata";

/** La geometria della griglia, la stessa che scrive il generatore. */
const PRIMA_RIGA_DATI = 4;
const PRIMA_COLONNA_GIORNI = 3;
const COLONNA_ID_TURNO = 35;

/** Le iniziali dei giorni, da lunedi'. */
const INIZIALI_GIORNI = "LMMGVSD";
const INDICE_DOMENICA = 6;

/** I nomi dei giorni come stanno nella tendina dei turni fissi. */
const GIORNI_SETTIMANA = ["lunedi", "martedi", "mercoledi", "giovedi",
                          "venerdi", "sabato", "domenica"];

/** Quanto pesa ogni criterio nel punteggio di una candidatura. */
const PUNTI_DESIDERATA_CENTRATO = 120;
const PUNTI_PRESIDIO_PROPRIO = 15;
const PUNTI_PER_TURNO_MANCANTE = 10;

/** Il separatore fra livello e nome dentro un bersaglio. */
const SEPARATORE_LIVELLO = ": ";

/** Quante regole per persona prevede la tabella delle preferenze. */
const REGOLE_PER_PERSONA = 10;

// ---------------------------------------------------------------------
// Tipi
// ---------------------------------------------------------------------

/** Un turno da coprire, come lo descrive T_Turni. */
interface Turno {
    id: string;
    etichetta: string;
    postazione: string;
    sede: string;
    metodica: string;
    fascia: string;
    riempimento: string;
    necessita: number;
    giorni: string;
    apreFestivi: boolean;
    apreSuperfestivi: boolean;
    attivo: boolean;
    riga: number;
}

/** Una persona assegnabile. */
interface Persona {
    acronimo: string;
    presidio: string;
    soloPresidioProprio: boolean;
    attivo: boolean;
    riga: number;
}

/** Una preferenza: un bersaglio e come trattarlo. */
interface Preferenza {
    persona: string;
    livello: string;
    nome: string;
    modo: string;
}

/** Un tetto mensile su un bersaglio; persona vuota vale per tutti. */
interface Tetto {
    persona: string;
    livello: string;
    nome: string;
    massimo: number;
}

/** Un turno che torna ogni settimana alla stessa persona. */
interface PostoFisso {
    persona: string;
    turno: string;
    giorno: number;
    saltaSeAssente: boolean;
}

/** Tutto cio' che serve al solver, letto una volta sola. */
interface Configurazione {
    turni: Turno[];
    persone: Persona[];
    preferenze: Preferenza[];
    tetti: Tetto[];
    postiFissi: PostoFisso[];
    tipologiaSede: Map<string, string>;
    dovutiSede: Map<string, boolean>;
    fasciaRichiesta: Map<string, string>;
    assenze: Set<string>;
    pesoEvita: number;
    pesoPreferisci: number;
    maxGiorniConsecutivi: number;
}

// ---------------------------------------------------------------------
// Lettura della configurazione
// ---------------------------------------------------------------------

/**
 * I valori di una tabella, intestazione esclusa.
 *
 * @param workbook la cartella di lavoro.
 * @param nome nome della Tabella, es. `T_Turni`.
 * @returns le righe come matrice di valori.
 */
function leggiTabella(workbook: ExcelScript.Workbook,
                      nome: string): (string | number | boolean)[][] {
    const tabella = workbook.getTable(nome);
    if (!tabella) {
        throw new Error(`Manca la tabella ${nome}.`);
    }

    return tabella.getRangeBetweenHeaderAndTotal().getValues();
}

/** Il contenuto di una cella come testo pulito. */
function testo(valore: string | number | boolean): string {
    return valore === null || valore === undefined ? "" : String(valore).trim();
}

/** Vero quando la cella dice SI. */
function eSi(valore: string | number | boolean): boolean {
    return testo(valore).toUpperCase() === "SI";
}

/**
 * Spacchetta un bersaglio nella coppia livello e nome.
 *
 * I bersagli si scrivono `sede: S.G.`, `fascia: notte`, e il livello sta
 * scritto davanti proprio per non doverlo cercare in tabella.
 *
 * @param bersaglio il testo del bersaglio.
 * @returns livello e nome, entrambi vuoti se il testo non e' un bersaglio.
 */
function spacchettaBersaglio(bersaglio: string): [string, string] {
    const taglio = bersaglio.indexOf(SEPARATORE_LIVELLO);
    if (taglio < 0) {
        return ["", ""];
    }

    return [bersaglio.substring(0, taglio).trim(),
            bersaglio.substring(taglio + SEPARATORE_LIVELLO.length).trim()];
}

/**
 * I turni attivi, con la riga che occupano nel Calendario.
 *
 * La riga non sta in T_Turni: la si ricava dalla colonna di servizio del
 * Calendario, che porta l'id di ogni riga. Cosi' il solver non deve
 * sapere come sono disposte le sezioni.
 */
function leggiTurni(workbook: ExcelScript.Workbook,
                    righePerId: Map<string, number>): Turno[] {
    const turni: Turno[] = [];

    for (const riga of leggiTabella(workbook, "T_Turni")) {
        const id = testo(riga[0]);
        const posizione = righePerId.get(id);
        if (!eSi(riga[14]) || posizione === undefined) {
            continue;
        }

        turni.push({
            id: id,
            etichetta: testo(riga[1]),
            postazione: testo(riga[3]),
            sede: testo(riga[4]),
            metodica: testo(riga[5]),
            fascia: testo(riga[6]),
            riempimento: testo(riga[8]),
            necessita: Number(riga[9]) || 0,
            giorni: testo(riga[10]),
            apreFestivi: eSi(riga[11]),
            apreSuperfestivi: eSi(riga[12]),
            attivo: true,
            riga: posizione,
        });
    }

    return turni;
}

/** Le persone assegnabili, con la riga che occupano nel Desiderata. */
function leggiPersone(workbook: ExcelScript.Workbook): Persona[] {
    const persone: Persona[] = [];
    let riga = PRIMA_RIGA_DATI;

    for (const valori of leggiTabella(workbook, "T_Persone")) {
        const acronimo = testo(valori[0]);
        if (acronimo !== "") {
            persone.push({
                acronimo: acronimo,
                presidio: testo(valori[3]),
                soloPresidioProprio: eSi(valori[4]),
                attivo: eSi(valori[5]),
                riga: riga,
            });
        }
        riga += 1;
    }

    return persone.filter(persona => persona.attivo);
}

/**
 * Le preferenze, una riga per persona con dieci regole appaiate.
 *
 * @param workbook la cartella di lavoro.
 * @returns una lista piatta di preferenze, saltando gli slot vuoti.
 */
function leggiPreferenze(workbook: ExcelScript.Workbook): Preferenza[] {
    const preferenze: Preferenza[] = [];

    for (const riga of leggiTabella(workbook, "T_Preferenze")) {
        const persona = testo(riga[0]);
        if (persona === "") {
            continue;
        }

        for (let numero = 0; numero < REGOLE_PER_PERSONA; numero++) {
            const bersaglio = testo(riga[1 + numero * 2]);
            const modo = testo(riga[2 + numero * 2]);
            if (bersaglio === "" || modo === "") {
                continue;
            }

            const [livello, nome] = spacchettaBersaglio(bersaglio);
            preferenze.push({ persona, livello, nome, modo });
        }
    }

    return preferenze;
}

/** I tetti mensili; la persona in bianco vale per tutti. */
function leggiTetti(workbook: ExcelScript.Workbook): Tetto[] {
    const tetti: Tetto[] = [];

    for (const riga of leggiTabella(workbook, "T_Tetti")) {
        const bersaglio = testo(riga[1]);
        const massimo = riga[2];
        if (bersaglio === "" || massimo === "" || massimo === null) {
            continue;
        }

        const [livello, nome] = spacchettaBersaglio(bersaglio);
        tetti.push({
            persona: testo(riga[0]),
            livello: livello,
            nome: nome,
            massimo: Number(massimo),
        });
    }

    return tetti;
}

/** I turni fissi settimanali, gia' attivi. */
function leggiPostiFissi(workbook: ExcelScript.Workbook): PostoFisso[] {
    const posti: PostoFisso[] = [];

    for (const riga of leggiTabella(workbook, "T_PostiFissi")) {
        const persona = testo(riga[0]);
        const bersaglio = testo(riga[1]);
        const giorno = GIORNI_SETTIMANA.indexOf(testo(riga[2]).toLowerCase());
        if (persona === "" || bersaglio === "" || giorno < 0 || !eSi(riga[4])) {
            continue;
        }

        posti.push({
            persona: persona,
            turno: spacchettaBersaglio(bersaglio)[1],
            giorno: giorno,
            saltaSeAssente: eSi(riga[3]),
        });
    }

    return posti;
}

/**
 * Legge tutto quello che serve, in una passata sola.
 *
 * Ogni lettura da Excel costa: farle tutte in testa e poi ragionare in
 * memoria e' la differenza fra un solver che gira in un secondo e uno che
 * fa aspettare.
 */
function leggiConfigurazione(workbook: ExcelScript.Workbook,
                             righePerId: Map<string, number>): Configurazione {
    const tipologiaSede = new Map<string, string>();
    const dovutiSede = new Map<string, boolean>();
    for (const riga of leggiTabella(workbook, "T_Sedi")) {
        tipologiaSede.set(testo(riga[0]), testo(riga[3]));
        dovutiSede.set(testo(riga[0]), eSi(riga[4]));
    }

    const fasciaRichiesta = new Map<string, string>();
    const assenze = new Set<string>();
    for (const riga of leggiTabella(workbook, "T_Richieste")) {
        const sigla = testo(riga[0]);
        fasciaRichiesta.set(sigla, testo(riga[2]));
        if (testo(riga[1]) === "assenza") {
            assenze.add(sigla);
        }
    }

    const parametri = new Map<string, number>();
    for (const riga of leggiTabella(workbook, "T_Parametri")) {
        parametri.set(testo(riga[0]), Number(riga[1]) || 0);
    }

    return {
        turni: leggiTurni(workbook, righePerId),
        persone: leggiPersone(workbook),
        preferenze: leggiPreferenze(workbook),
        tetti: leggiTetti(workbook),
        postiFissi: leggiPostiFissi(workbook),
        tipologiaSede: tipologiaSede,
        dovutiSede: dovutiSede,
        fasciaRichiesta: fasciaRichiesta,
        assenze: assenze,
        pesoEvita: parametri.get("peso_evita") || 0,
        pesoPreferisci: parametri.get("peso_preferisci") || 0,
        maxGiorniConsecutivi: parametri.get("max_giorni_consecutivi") || 0,
    };
}

// ---------------------------------------------------------------------
// Bersagli
// ---------------------------------------------------------------------

/**
 * Se un bersaglio colpisce un turno.
 *
 * E' il cuore delle preferenze: `sede: S.M.` colpisce tutti i turni di
 * Santa Maria, `turno: ADD. TC · mattina` ne colpisce uno solo.
 *
 * @param livello il livello del bersaglio.
 * @param nome il nome dentro quel livello.
 * @param turno il turno da verificare.
 * @param configurazione le tabelle lette.
 * @returns vero se il bersaglio comprende quel turno.
 */
function bersaglioColpisce(livello: string, nome: string, turno: Turno,
                           configurazione: Configurazione): boolean {
    if (livello === "fascia") {
        return turno.fascia === nome;
    }
    if (livello === "sede") {
        return turno.sede === nome;
    }
    if (livello === "metodica") {
        return turno.metodica === nome;
    }
    if (livello === "turno") {
        return turno.etichetta === nome || turno.postazione === nome;
    }
    if (livello === "tipologia") {
        return configurazione.tipologiaSede.get(turno.sede) === nome;
    }

    return false;
}

// ---------------------------------------------------------------------
// Stato della griglia
// ---------------------------------------------------------------------

/** Quello che il solver sa, giorno per giorno, di ogni persona. */
class Stato {
    /** Chi lavora quel giorno, e in che fascia. */
    private fascePerGiorno: Map<string, string>[] = [];
    /** Quanti turni ha gia' una persona, contando solo quelli dovuti. */
    private turniDovuti = new Map<string, number>();
    /** Quante volte una persona ha gia' preso un dato bersaglio. */
    private conteggi = new Map<string, number>();

    constructor(giorni: number) {
        for (let giorno = 0; giorno < giorni; giorno++) {
            this.fascePerGiorno.push(new Map<string, string>());
        }
    }

    /** Registra un'assegnazione e aggiorna tutti i contatori. */
    assegna(persona: string, giorno: number, turno: Turno,
            configurazione: Configurazione): void {
        this.fascePerGiorno[giorno].set(persona, turno.fascia);

        if (configurazione.dovutiSede.get(turno.sede) !== false) {
            this.turniDovuti.set(persona,
                                 (this.turniDovuti.get(persona) || 0) + 1);
        }

        for (const chiave of this.chiaviBersaglio(persona, turno,
                                                  configurazione)) {
            this.conteggi.set(chiave, (this.conteggi.get(chiave) || 0) + 1);
        }
    }

    /** Le chiavi di conteggio che un'assegnazione fa crescere. */
    private chiaviBersaglio(persona: string, turno: Turno,
                            configurazione: Configurazione): string[] {
        const tipologia = configurazione.tipologiaSede.get(turno.sede) || "";

        return [
            `${persona}|fascia|${turno.fascia}`,
            `${persona}|sede|${turno.sede}`,
            `${persona}|metodica|${turno.metodica}`,
            `${persona}|turno|${turno.etichetta}`,
            `${persona}|tipologia|${tipologia}`,
        ];
    }

    /** Quante volte la persona ha gia' preso quel bersaglio. */
    conteggio(persona: string, livello: string, nome: string): number {
        return this.conteggi.get(`${persona}|${livello}|${nome}`) || 0;
    }

    /** La fascia che la persona copre quel giorno, o stringa vuota. */
    fascia(persona: string, giorno: number): string {
        if (giorno < 0 || giorno >= this.fascePerGiorno.length) {
            return "";
        }

        return this.fascePerGiorno[giorno].get(persona) || "";
    }

    /** Se la persona lavora quel giorno, in qualsiasi fascia. */
    occupata(persona: string, giorno: number): boolean {
        return this.fascia(persona, giorno) !== "";
    }

    /** Quanti turni che contano ha gia' la persona. */
    dovuti(persona: string): number {
        return this.turniDovuti.get(persona) || 0;
    }
}

// ---------------------------------------------------------------------
// Ammissibilita' e punteggio
// ---------------------------------------------------------------------

/**
 * Se una persona puo' coprire quel turno quel giorno.
 *
 * Sono i divieti che non si negoziano: le regole assolute del contratto,
 * i `mai` e i `solo` delle preferenze, i tetti mensili, l'assenza gia'
 * chiesta. Chi non passa di qui non viene nemmeno valutato.
 *
 * @param persona chi si sta valutando.
 * @param giorno indice del giorno, da zero.
 * @param turno il turno da coprire.
 * @param stato cosa e' gia' stato assegnato.
 * @param chiesto la sigla che la persona ha chiesto quel giorno.
 * @param configurazione le tabelle lette.
 * @returns vero se l'assegnazione e' lecita.
 */
function ammissibile(persona: Persona, giorno: number, turno: Turno,
                     stato: Stato, chiesto: string,
                     configurazione: Configurazione): boolean {
    // Un turno al giorno, e la notte non sta con nient'altro.
    if (stato.occupata(persona.acronimo, giorno)) {
        return false;
    }

    // Smonto: chi ha fatto la notte ieri oggi riposa.
    if (stato.fascia(persona.acronimo, giorno - 1) === "notte") {
        return false;
    }

    // La notte di oggi impegna anche il giorno dopo.
    if (turno.fascia === "notte" && stato.occupata(persona.acronimo,
                                                   giorno + 1)) {
        return false;
    }

    // Aveva chiesto di non esserci.
    if (configurazione.assenze.has(chiesto)) {
        return false;
    }

    if (persona.soloPresidioProprio && persona.presidio !== "") {
        const suo = configurazione.tipologiaSede.has(turno.sede);
        if (suo && !turno.sede.startsWith(persona.presidio)
            && turno.sede !== persona.presidio) {
            return false;
        }
    }

    return rispettaPreferenze(persona.acronimo, turno, configurazione)
        && rispettaTetti(persona.acronimo, turno, stato, configurazione);
}

/**
 * I `mai` e i `solo` di una persona rispetto a un turno.
 *
 * I `solo` si intersecano per asse: chi ha `solo` sulle sedi puo' finire
 * unicamente in quelle sedi, ma la regola non dice niente sulle fasce.
 */
function rispettaPreferenze(persona: string, turno: Turno,
                            configurazione: Configurazione): boolean {
    const soloPerLivello = new Map<string, boolean>();

    for (const regola of configurazione.preferenze) {
        if (regola.persona !== persona) {
            continue;
        }

        const colpisce = bersaglioColpisce(regola.livello, regola.nome, turno,
                                           configurazione);
        if (regola.modo === "mai" && colpisce) {
            return false;
        }
        if (regola.modo === "solo") {
            soloPerLivello.set(regola.livello,
                               (soloPerLivello.get(regola.livello) || false)
                               || colpisce);
        }
    }

    for (const soddisfatto of soloPerLivello.values()) {
        if (!soddisfatto) {
            return false;
        }
    }

    return true;
}

/** Se assegnare quel turno sforerebbe un tetto mensile. */
function rispettaTetti(persona: string, turno: Turno, stato: Stato,
                       configurazione: Configurazione): boolean {
    for (const tetto of configurazione.tetti) {
        if (tetto.persona !== "" && tetto.persona !== persona) {
            continue;
        }
        if (!bersaglioColpisce(tetto.livello, tetto.nome, turno,
                               configurazione)) {
            continue;
        }
        if (stato.conteggio(persona, tetto.livello, tetto.nome)
            >= tetto.massimo) {
            return false;
        }
    }

    return true;
}

/**
 * Quanto e' desiderabile mettere quella persona in quel turno.
 *
 * Piu' alto e' meglio. Conta soprattutto il desiderata centrato, poi
 * l'equilibrio del carico, infine le preferenze morbide e il presidio.
 */
function punteggio(persona: Persona, turno: Turno, stato: Stato,
                   chiesto: string, dovutiMedi: number,
                   configurazione: Configurazione): number {
    let punti = 0;

    if (configurazione.fasciaRichiesta.get(chiesto) === turno.fascia) {
        punti += PUNTI_DESIDERATA_CENTRATO;
    }

    // Chi e' indietro rispetto alla media passa avanti: e' cio' che
    // distribuisce il carico senza doverlo imporre con un vincolo.
    punti += (dovutiMedi - stato.dovuti(persona.acronimo))
        * PUNTI_PER_TURNO_MANCANTE;

    if (persona.presidio !== "" && turno.sede.indexOf(persona.presidio) >= 0) {
        punti += PUNTI_PRESIDIO_PROPRIO;
    }

    for (const regola of configurazione.preferenze) {
        if (regola.persona !== persona.acronimo
            || !bersaglioColpisce(regola.livello, regola.nome, turno,
                                  configurazione)) {
            continue;
        }
        if (regola.modo === "evita") {
            punti += configurazione.pesoEvita;
        }
        if (regola.modo === "preferisci") {
            punti += configurazione.pesoPreferisci;
        }
    }

    return punti;
}

// ---------------------------------------------------------------------
// Il giro principale
// ---------------------------------------------------------------------

/** Se quel turno va coperto quel giorno. */
function turnoAperto(turno: Turno, data: Date, festivo: boolean,
                     superfestivo: boolean): boolean {
    if (turno.riempimento === "chiuso") {
        return false;
    }

    const indice = (data.getDay() + 6) % 7;
    if (turno.giorni.charAt(indice) === "-") {
        return false;
    }
    if (indice === INDICE_DOMENICA && !turno.apreFestivi) {
        return false;
    }
    if (superfestivo && !turno.apreSuperfestivi) {
        return false;
    }

    return true;
}

/**
 * L'ordine in cui il solver affronta le celle.
 *
 * Prima l'obbligatorio, e dentro ciascuna categoria il piu' necessario:
 * quando la gente scarseggia, a restare scoperto dev'essere cio' che
 * conta meno.
 */
function ordinaCelle(celle: { turno: Turno, giorno: number }[]):
        { turno: Turno, giorno: number }[] {
    return celle.sort((primo, secondo) => {
        const pesoPrimo = primo.turno.riempimento === "obbligatorio" ? 1 : 0;
        const pesoSecondo = secondo.turno.riempimento === "obbligatorio" ? 1 : 0;
        if (pesoPrimo !== pesoSecondo) {
            return pesoSecondo - pesoPrimo;
        }
        if (primo.turno.necessita !== secondo.turno.necessita) {
            return secondo.turno.necessita - primo.turno.necessita;
        }

        return primo.giorno - secondo.giorno;
    });
}

/**
 * Applica i turni fissi prima di ogni altra scelta.
 *
 * Sono decisioni gia' prese: il solver le mette e basta, purche' la cella
 * sia libera e la persona non abbia chiesto un'assenza — se `salta_se_
 * assente` dice di rispettarla.
 *
 * @returns quante celle sono state riempite.
 */
function applicaPostiFissi(griglia: string[][], giorni: Date[],
                           indicePerId: Map<string, number>,
                           desiderata: Map<string, string[]>,
                           stato: Stato,
                           configurazione: Configurazione): number {
    let messi = 0;

    for (const posto of configurazione.postiFissi) {
        for (const turno of configurazione.turni) {
            if (turno.etichetta !== posto.turno
                && turno.postazione !== posto.turno) {
                continue;
            }

            for (let giorno = 0; giorno < giorni.length; giorno++) {
                if ((giorni[giorno].getDay() + 6) % 7 !== posto.giorno) {
                    continue;
                }
                const riga = indicePerId.get(turno.id);
                if (riga === undefined || griglia[riga][giorno] !== "") {
                    continue;
                }

                const chiesto = richiestaDi(desiderata, posto.persona, giorno);
                if (posto.saltaSeAssente
                    && configurazione.assenze.has(chiesto)) {
                    continue;
                }
                if (stato.occupata(posto.persona, giorno)) {
                    continue;
                }

                griglia[riga][giorno] = posto.persona;
                stato.assegna(posto.persona, giorno, turno, configurazione);
                messi += 1;
            }
        }
    }

    return messi;
}

/** Cosa aveva chiesto una persona in un dato giorno. */
function richiestaDi(desiderata: Map<string, string[]>, persona: string,
                     giorno: number): string {
    const riga = desiderata.get(persona);

    return riga && giorno < riga.length ? riga[giorno] : "";
}

/**
 * Il punto di ingresso: legge, decide, scrive.
 *
 * @param workbook la cartella di lavoro aperta.
 */
function main(workbook: ExcelScript.Workbook): void {
    const calendario = workbook.getWorksheet(FOGLIO_CALENDARIO);
    if (!calendario) {
        throw new Error(`Manca il foglio ${FOGLIO_CALENDARIO}.`);
    }

    const usato = calendario.getUsedRange();
    const ultimaRiga = usato.getRowCount() + usato.getRowIndex();
    const intestazione = calendario.getRange(
        `A1:${colonnaLettera(COLONNA_ID_TURNO)}${ultimaRiga}`).getValues();

    const giorni = leggiGiorni(intestazione[0]);
    const righePerId = new Map<string, number>();
    const indicePerId = new Map<string, number>();

    for (let riga = PRIMA_RIGA_DATI - 1; riga < intestazione.length; riga++) {
        const id = testo(intestazione[riga][COLONNA_ID_TURNO - 1]);
        if (id !== "") {
            indicePerId.set(id, righePerId.size);
            righePerId.set(id, riga + 1);
        }
    }

    const configurazione = leggiConfigurazione(workbook, righePerId);
    const desiderata = leggiDesiderata(workbook, giorni.length);
    const griglia = leggiGriglia(intestazione, righePerId, giorni.length);

    const riempite = riempi(griglia, giorni, configurazione, desiderata,
                            indicePerId);
    scriviGriglia(calendario, griglia, righePerId, giorni.length);

    console.log(`Riempite ${riempite} celle su ${contaVuote(griglia)
        + riempite} disponibili.`);
}

/** La lettera di colonna per un indice a partire da uno. */
function colonnaLettera(indice: number): string {
    let lettera = "";
    let resto = indice;
    while (resto > 0) {
        const cifra = (resto - 1) % 26;
        lettera = String.fromCharCode(65 + cifra) + lettera;
        resto = Math.floor((resto - cifra) / 26);
    }

    return lettera;
}

/** Le date del mese, dalla riga di intestazione del Calendario. */
function leggiGiorni(intestazione: (string | number | boolean)[]): Date[] {
    const giorni: Date[] = [];

    for (let colonna = PRIMA_COLONNA_GIORNI - 1;
         colonna < intestazione.length; colonna++) {
        const valore = intestazione[colonna];
        if (typeof valore === "number" && valore > 0) {
            // Excel conta i giorni dal 30 dicembre 1899.
            giorni.push(new Date(Date.UTC(1899, 11, 30) + valore * 86400000));
        }
    }

    return giorni;
}

/** Cosa ha chiesto ciascuno, giorno per giorno. */
function leggiDesiderata(workbook: ExcelScript.Workbook,
                         giorni: number): Map<string, string[]> {
    const foglio = workbook.getWorksheet(FOGLIO_DESIDERATA);
    const richieste = new Map<string, string[]>();
    if (!foglio) {
        return richieste;
    }

    const usato = foglio.getUsedRange();
    const valori = foglio.getRange(
        `B${PRIMA_RIGA_DATI}:${colonnaLettera(PRIMA_COLONNA_GIORNI - 1
            + giorni)}${usato.getRowCount() + usato.getRowIndex()}`
    ).getValues();

    for (const riga of valori) {
        const persona = testo(riga[0]);
        if (persona !== "") {
            richieste.set(persona, riga.slice(1).map(cella => testo(cella)));
        }
    }

    return richieste;
}

/** Lo stato attuale della griglia, celle gia' scritte comprese. */
function leggiGriglia(intestazione: (string | number | boolean)[][],
                      righePerId: Map<string, number>,
                      giorni: number): string[][] {
    const griglia: string[][] = [];

    for (const riga of righePerId.values()) {
        const valori: string[] = [];
        for (let giorno = 0; giorno < giorni; giorno++) {
            valori.push(testo(
                intestazione[riga - 1][PRIMA_COLONNA_GIORNI - 1 + giorno]));
        }
        griglia.push(valori);
    }

    return griglia;
}

/** Quante celle restano vuote. */
function contaVuote(griglia: string[][]): number {
    let vuote = 0;
    for (const riga of griglia) {
        for (const cella of riga) {
            if (cella === "") {
                vuote += 1;
            }
        }
    }

    return vuote;
}

/**
 * Riempie le celle vuote, lasciando intatte quelle gia' scritte.
 *
 * Le assegnazioni gia' presenti entrano subito nello stato: contano per
 * l'equilibrio del carico e per i divieti, esattamente come se le avesse
 * decise il solver. Chi ha messo un turno a mano non se lo vede aggirare.
 *
 * @returns quante celle sono state riempite.
 */
function riempi(griglia: string[][], giorni: Date[],
                configurazione: Configurazione,
                desiderata: Map<string, string[]>,
                indicePerId: Map<string, number>): number {
    const stato = new Stato(giorni.length);
    const turniPerIndice = new Map<number, Turno>();
    for (const turno of configurazione.turni) {
        const indice = indicePerId.get(turno.id);
        if (indice !== undefined) {
            turniPerIndice.set(indice, turno);
        }
    }

    for (const [indice, turno] of turniPerIndice) {
        for (let giorno = 0; giorno < giorni.length; giorno++) {
            const gia = griglia[indice][giorno];
            if (gia !== "") {
                stato.assegna(gia, giorno, turno, configurazione);
            }
        }
    }

    const celle: { turno: Turno, giorno: number }[] = [];
    for (const [indice, turno] of turniPerIndice) {
        for (let giorno = 0; giorno < giorni.length; giorno++) {
            if (griglia[indice][giorno] === ""
                && turnoAperto(turno, giorni[giorno], false, false)) {
                celle.push({ turno: turno, giorno: giorno });
            }
        }
    }

    let riempite = applicaPostiFissi(griglia, giorni, indicePerId, desiderata,
                                     stato, configurazione);
    riempite += assegnaCelle(ordinaCelle(celle), griglia, indicePerId,
                             desiderata, stato, configurazione,
                             giorni.length);

    return riempite;
}

/**
 * Sceglie una persona per ogni cella, dalla piu' urgente in giu'.
 *
 * @returns quante celle sono state riempite.
 */
function assegnaCelle(celle: { turno: Turno, giorno: number }[],
                      griglia: string[][],
                      indicePerId: Map<string, number>,
                      desiderata: Map<string, string[]>, stato: Stato,
                      configurazione: Configurazione,
                      giorni: number): number {
    const dovutiMedi = giorni / 2;
    let riempite = 0;

    for (const cella of celle) {
        const indice = indicePerId.get(cella.turno.id);
        if (indice === undefined || griglia[indice][cella.giorno] !== "") {
            continue;
        }

        const scelta = migliorePersona(cella.turno, cella.giorno, stato,
                                       desiderata, dovutiMedi,
                                       configurazione);
        if (scelta === "") {
            continue;
        }

        griglia[indice][cella.giorno] = scelta;
        stato.assegna(scelta, cella.giorno, cella.turno, configurazione);
        riempite += 1;
    }

    return riempite;
}

/** La persona col punteggio piu' alto fra quelle ammissibili. */
function migliorePersona(turno: Turno, giorno: number, stato: Stato,
                         desiderata: Map<string, string[]>,
                         dovutiMedi: number,
                         configurazione: Configurazione): string {
    let migliore = "";
    let punteggioMigliore = -Infinity;

    for (const persona of configurazione.persone) {
        const chiesto = richiestaDi(desiderata, persona.acronimo, giorno);
        if (!ammissibile(persona, giorno, turno, stato, chiesto,
                         configurazione)) {
            continue;
        }

        const punti = punteggio(persona, turno, stato, chiesto, dovutiMedi,
                                configurazione);
        if (punti > punteggioMigliore) {
            punteggioMigliore = punti;
            migliore = persona.acronimo;
        }
    }

    return migliore;
}

/** Riscrive la griglia in Excel, in una sola operazione per riga. */
function scriviGriglia(calendario: ExcelScript.Worksheet, griglia: string[][],
                       righePerId: Map<string, number>, giorni: number): void {
    const ultimaColonna = colonnaLettera(PRIMA_COLONNA_GIORNI - 1 + giorni);
    const prima = colonnaLettera(PRIMA_COLONNA_GIORNI);
    let indice = 0;

    for (const riga of righePerId.values()) {
        calendario.getRange(`${prima}${riga}:${ultimaColonna}${riga}`)
            .setValues([griglia[indice]]);
        indice += 1;
    }
}
