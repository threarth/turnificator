<!--
  ConfigurazioneGuidata — l'intera configurazione del tenant, accompagnata.

  Nuova feature. Sei sezioni indipendenti con una roadmap in cima: si
  percorrono in ordine la prima volta, ma poi si salta direttamente a quella
  che serve. Riaprirla e' il caso normale, non l'eccezione.

  Cinque sezioni su sei lavorano sui dati veri e salvano subito: fasce,
  tipologie, conteggi e vincoli sono impostazioni globali e non hanno niente
  da confermare alla fine. Fanno eccezione strutture e turni, che accumulano
  in memoria e producono la struttura turni alla conferma.

  I tre livelli interni — sovragruppo, gruppo, turno — non si vedono mai: il
  gruppo, che e' l'insieme dei turni di una fascia dentro una struttura, nasce
  da solo quando due turni cadono nella stessa fascia.

  Props:
    - fasce           : Array — flag_turno, come li carica la pagina admin
    - tipologie       : Array — tipi qualitativo
    - conteggi        : Array — conteggi del context menu
    - etichetta       : {singolare, plurale} — come l'utente chiama le strutture
    - presetEsistente : la struttura turni del tenant, se già creata
    - adminApi        : il client API, per le sezioni che lo usano
    - tipiQualitativo, vincoliGlobali, vincoliSolver — passati a VincoliSolver
    - oncompletata    : (presetId, etichetta) => void — configurazione salvata
    - onannulla       : () => void — uscita
    - onfasceaggiornate : () => Promise — ricarica i flag nel chiamante
    - ontipologieaggiornate : () => Promise — ricarica le tipologie
    - onconteggiaggiornati  : (conteggi) => Promise — salva e ricarica i conteggi
-->
<script>
    import { adminApi } from '$lib/api.js';
    import { focusOnMount } from '../actions.js';
    import DeleteButton from '../DeleteButton.svelte';
    import VincoliSolver from '../VincoliSolver.svelte';
    import { minToHm } from '../durate.js';
    import { costruisciStruttura, nomeDuplicato } from '../struttura.js';
    import SezioneTipologie from './SezioneTipologie.svelte';
    import SezioneConteggi from './SezioneConteggi.svelte';
    import SezioneUtenti from './SezioneUtenti.svelte';

    export let fasce = [];
    export let tipologie = [];
    export let conteggi = [];
    export let utenti = [];
    export let sovragruppi = [];
    export let etichetta = { singolare: 'Struttura', plurale: 'Strutture' };
    export let vincoliGlobali = [];
    export let vincoliSolver = [];
    export let presetEsistente = null;
    export let oncompletata;
    export let onannulla;
    export let onfasceaggiornate;
    export let ontipologieaggiornate;
    export let onconteggiaggiornati;
    export let onutentiaggiornati;

    // Il turno tipo e' l'unita' di misura del peso, non classifica turni:
    // non va offerto come categoria di una fascia.
    const NOME_TURNO_TIPO = 'turno_tipo';

    // Pausa obbligatoria di default, in minuti.
    const PAUSA_DEFAULT_MINUTI = 10;

    // Nomi comuni per la struttura, con il loro plurale gia' corretto:
    // sceglierli da un elenco evita di doverlo indovinare dal singolare.
    const ETICHETTE_SUGGERITE = [
        { singolare: 'Reparto',     plurale: 'Reparti' },
        { singolare: 'Ambulatorio', plurale: 'Ambulatori' },
        { singolare: 'Presidio',    plurale: 'Presidi' },
        { singolare: 'Ospedale',    plurale: 'Ospedali' },
        { singolare: 'Servizio',    plurale: 'Servizi' },
        { singolare: 'Struttura',   plurale: 'Strutture' },
    ];

    // Le sezioni, nell'ordine in cui conviene percorrerle la prima volta.
    // `chiusa` distingue quelle che salvano subito da strutture e turni, che
    // producono qualcosa solo alla conferma finale.
    $: sezioni = [
        { id: 'fasce',      nome: 'Fasce orarie',      chiusa: true },
        { id: 'tipologie',  nome: 'Tipologie turno',   chiusa: true },
        { id: 'strutture',  nome: etichetta.plurale,   chiusa: false },
        { id: 'turni',      nome: 'I turni',           chiusa: false },
        { id: 'utenti',     nome: 'Le persone',        chiusa: true },
        { id: 'conteggi',   nome: 'Conteggi',          chiusa: true },
        { id: 'vincoli',    nome: 'Vincoli',           chiusa: true },
    ];

    $: sezioneCorrente = sezioni[passo]?.id;

    let passo = 0;
    let errore = '';
    let salvataggio = false;

    // Etichetta personalizzata: attiva quando nessun suggerimento va bene.
    let etichettaLibera = false;

    // Passo 1 — form di creazione di una fascia nuova.
    let nuovaFascia = fasciaVuota();

    // Orari in corso di modifica, per id fascia: { orario_inizio, orario_fine, pausa_minuti }.
    let modificheFasce = {};

    // Passo 2 e 3 — il modello del wizard e' piatto: struttura → turni.
    // I gruppi non esistono qui, li materializza costruisciStruttura().
    let strutture = [struttureVuota()];

    let nomePreset = '';

    // Contatore per gli id temporanei: il server distingue le entita' nuove
    // dal fatto che l'id non e' un intero.
    let contatoreId = 0;
    function idTemporaneo() {
        contatoreId += 1;
        return `w${contatoreId}`;
    }

    function fasciaVuota() {
        return {
            nome: '', parent_id: null,
            orario_inizio: '', orario_fine: '', pausa_minuti: PAUSA_DEFAULT_MINUTI,
        };
    }

    function struttureVuota() {
        return { nome: '', ambito: '', turni: [] };
    }

    // I concetti sotto cui una fascia puo' stare: dicono se e' diurna,
    // notturna o una guardia, e da li' discendono le regole sulle notti.
    $: concetti = fasce.filter(f =>
        !f.parent_id && f.tipo !== 'assenza' && f.nome !== NOME_TURNO_TIPO
    );

    // Le fasce agganciabili a un turno, in ordine di orario.
    $: fasceDisponibili = fasce
        .filter(f => f.mostra_in_struttura)
        .sort((a, b) => (a.orario_inizio || '').localeCompare(b.orario_inizio || ''));

    $: if (!nuovaFascia.parent_id && concetti.length) {
        nuovaFascia.parent_id = concetti[0].id;
    }

    // ── Passo 1: fasce orarie ────────────────────────────────────────────

    /** Una fascia e' pronta se ha nome, categoria ed entrambi gli orari. */
    $: nuovaFasciaCompleta = nuovaFascia.nome.trim()
        && nuovaFascia.parent_id
        && nuovaFascia.orario_inizio.trim()
        && nuovaFascia.orario_fine.trim();

    async function aggiungiFascia() {
        if (!nuovaFasciaCompleta) return;

        errore = '';
        const r = await adminApi.creaFlagTurno({ ...nuovaFascia, tipo: 'lavorativo' });
        if (!r.ok) { errore = r.errore || 'Creazione della fascia non riuscita.'; return; }

        nuovaFascia = fasciaVuota();
        await onfasceaggiornate();
    }

    /** Registra la modifica di un orario senza salvarla: serve il pulsante. */
    function modificaFascia(fascia, campo, valore) {
        const corrente = modificheFasce[fascia.id] ?? {
            orario_inizio: fascia.orario_inizio ?? '',
            orario_fine: fascia.orario_fine ?? '',
            pausa_minuti: fascia.pausa_minuti ?? PAUSA_DEFAULT_MINUTI,
        };
        modificheFasce = { ...modificheFasce, [fascia.id]: { ...corrente, [campo]: valore } };
    }

    async function salvaFascia(fascia) {
        const modifica = modificheFasce[fascia.id];
        if (!modifica) return;

        errore = '';
        const r = await adminApi.editFlagTurno(fascia.id, modifica);
        if (!r.ok) { errore = r.errore || 'Modifica della fascia non riuscita.'; return; }

        const { [fascia.id]: _rimossa, ...resto } = modificheFasce;
        modificheFasce = resto;
        await onfasceaggiornate();
    }

    // ── Passo 2: le strutture ────────────────────────────────────────────

    function scegliEtichetta(scelta) {
        etichettaLibera = scelta === null;
        if (scelta) etichetta = { ...scelta };
    }

    function aggiungiStruttura() {
        strutture = [...strutture, struttureVuota()];
    }

    function rimuoviStruttura(indice) {
        strutture = strutture.filter((_, i) => i !== indice);
        if (!strutture.length) strutture = [struttureVuota()];
    }

    // ── Passo 3: i turni ─────────────────────────────────────────────────

    function aggiungiTurno(indice) {
        const struttura = strutture[indice];
        struttura.turni = [
            ...struttura.turni,
            { nome: '', flag_id: fasceDisponibili[0]?.id ?? null, tipi_qualitativi: [] },
        ];
        strutture = [...strutture];
    }

    /**
     * Aggiunge sotto al turno una sua copia, nella fascia indicata.
     *
     * Serve a due gesti diversi con lo stesso pulsante: sfornare i turni di
     * una serie nella stessa fascia (DEA1, DEA2) e portare un turno in
     * un'altra fascia (TC mattina, TC pomeriggio). Il nome proposto segue il
     * gesto, e resta comunque modificabile.
     *
     * @param indiceStruttura — struttura a cui appartiene il turno
     * @param indiceTurno — posizione del turno da duplicare
     * @param flagId — fascia della copia; se omessa, la stessa dell'originale
     */
    function duplicaTurno(indiceStruttura, indiceTurno, flagId = null) {
        const struttura = strutture[indiceStruttura];
        const originale = struttura.turni[indiceTurno];
        const fasciaCopia = flagId ?? originale.flag_id;

        const copia = {
            nome: nomeDuplicato(
                originale.nome,
                nomeFascia(originale.flag_id),
                nomeFascia(fasciaCopia)
            ),
            flag_id: fasciaCopia,
            // Una copia serve a rifare lo stesso turno: le tipologie la seguono.
            tipi_qualitativi: [...(originale.tipi_qualitativi ?? [])],
        };

        struttura.turni = [
            ...struttura.turni.slice(0, indiceTurno + 1),
            copia,
            ...struttura.turni.slice(indiceTurno + 1),
        ];
        strutture = [...strutture];
    }

    /** Attiva o disattiva una tipologia su un turno. */
    function commutaTipologia(turno, tipologiaId) {
        const scelte = turno.tipi_qualitativi ?? [];
        turno.tipi_qualitativi = scelte.includes(tipologiaId)
            ? scelte.filter(id => id !== tipologiaId)
            : [...scelte, tipologiaId];
        strutture = [...strutture];
    }

    /** Le tipologie di un turno in parole, per il pulsante che le apre. */
    function etichettaTipologie(turno) {
        const scelte = turno.tipi_qualitativi ?? [];
        if (!scelte.length) return '—';

        return tipologie
            .filter(t => scelte.includes(t.id))
            .map(t => t.nome)
            .join(', ');
    }

    function nomeFascia(flagId) {
        return fasce.find(f => f.id === flagId)?.nome ?? '';
    }

    function rimuoviTurno(indiceStruttura, indiceTurno) {
        const struttura = strutture[indiceStruttura];
        struttura.turni = struttura.turni.filter((_, i) => i !== indiceTurno);
        strutture = [...strutture];
    }

    // ── Costruzione e salvataggio ────────────────────────────────────────

    $: struttureValide = strutture.filter(s => s.nome.trim());
    $: turniTotali = struttureValide
        .reduce((somma, s) => somma + s.turni.filter(t => t.nome.trim()).length, 0);

    // Le sezioni si attraversano liberamente: il requisito riguarda solo il
    // salvataggio finale, che senza turni e senza nome non ha cosa produrre.
    $: puoSalvare = turniTotali > 0
        && nomePreset.trim()
        && etichetta.singolare.trim();

    // Cosa manca perche' la configurazione sia salvabile, detto all'utente.
    $: cosaManca = !turniTotali ? 'Aggiungi almeno un turno.'
        : !nomePreset.trim() ? 'Dai un nome a questa configurazione.'
        : '';

    function vaiA(indice) {
        errore = '';
        passo = indice;
    }

    /**
     * Trova la struttura turni su cui scrivere.
     *
     * Il tenant ne ha una sola: se esiste si aggiorna quella, altrimenti la
     * si crea. Riaprire la guidata non lascia copie dietro di se'.
     *
     * @returns {Promise<number|null>} id della struttura, null se fallisce
     */
    async function presetDaAggiornare() {
        if (presetEsistente?.id) return presetEsistente.id;

        const creato = await adminApi.creaPreset({ nome: nomeCompletoPreset(nomePreset) });
        if (!creato.ok) {
            errore = creato.errore || 'Creazione della struttura turni non riuscita.';
            return null;
        }

        return creato.id;
    }

    async function completa() {
        if (!puoSalvare || salvataggio) return;

        salvataggio = true;
        errore = '';

        const presetId = await presetDaAggiornare();
        if (presetId === null) { salvataggio = false; return; }

        const salvato = await adminApi.salvaStrutturaPreset(presetId, {
            struttura: costruisciStruttura(strutture, fasce, idTemporaneo),
        });
        if (!salvato.ok) {
            errore = salvato.errore || 'Salvataggio della struttura non riuscito.';
            salvataggio = false;
            return;
        }

        await adminApi.setConfig({
            etichetta_struttura: etichetta.singolare.trim(),
            etichetta_strutture: etichetta.plurale.trim(),
        });

        salvataggio = false;
        oncompletata(presetId, { ...etichetta });
    }

    // I preset di struttura portano tutti lo stesso prefisso.
    function nomeCompletoPreset(nome) {
        const pulito = nome.trim();
        return pulito.startsWith('struttura_') ? pulito : `struttura_${pulito}`;
    }
</script>

<div class="guidata card">
    <div class="card-header d-flex align-items-center justify-content-between py-3">
        <div>
            <div class="fw-semibold">
                <i class="bi bi-compass me-2"></i>Configurazione guidata
            </div>
            <div class="text-muted small">
                {#if presetEsistente}
                    Aggiorna quello che serve: puoi andare direttamente alla sezione che ti interessa.
                {:else}
                    Sette sezioni, percorribili in ordine o saltando a quella che serve.
                {/if}
            </div>
        </div>
        <button class="btn btn-sm btn-outline-secondary" on:click={onannulla}>Esci</button>
    </div>

    <!-- La roadmap: numerata perche' l'ordine e' quello sensato la prima
         volta, ma ogni tappa e' raggiungibile direttamente. -->
    <nav class="guidata-passi d-flex" aria-label="Sezioni della configurazione">
        {#each sezioni as sezione, i}
            <button type="button"
                    class="guidata-passo flex-fill d-flex align-items-center gap-2 px-3 py-2
                           {i === passo ? 'corrente' : i < passo ? 'fatto' : 'futuro'}"
                    title="Vai a {sezione.nome}"
                    on:click={() => vaiA(i)}>
                <span class="guidata-numero">
                    {#if i < passo}<i class="bi bi-check-lg"></i>{:else}{i + 1}{/if}
                </span>
                <span class="small">{sezione.nome}</span>
            </button>
        {/each}
    </nav>

    <div class="card-body">
        {#if errore}
            <div class="alert alert-danger py-2 small">{errore}</div>
        {/if}

        <!-- ═══ Fasce orarie ═══ -->
        {#if sezioneCorrente === 'fasce'}
            <p class="guidata-intro">
                Una fascia oraria è l'orario di un turno: da che ora a che ora.
                Bastano quelli — durata, ore e peso li ricava il programma da sé.
            </p>

            <section class="guidata-sezione">
                <h6 class="guidata-titolo">Le fasce già disponibili</h6>
                <p class="guidata-aiuto">
                    Se un orario non corrisponde ai tuoi turni, correggilo qui.
                    Le fasce sono in comune: la correzione vale per ogni struttura
                    turni, non solo per quella che stai creando.
                </p>

                <table class="table table-sm align-middle mb-0">
                    <thead><tr>
                        <th style="width:150px">Fascia</th>
                        <th style="width:120px">Categoria</th>
                        <th style="width:100px">Inizio</th>
                        <th style="width:100px">Fine</th>
                        <th style="width:100px">Pausa (min)</th>
                        <th style="width:90px">Durata</th>
                        <th style="width:70px"></th>
                    </tr></thead>
                    <tbody>
                        {#each fasceDisponibili as f (f.id)}
                            {@const modifica = modificheFasce[f.id]}
                            <tr class:table-warning={modifica}>
                                <td class="fw-semibold">{f.nome}</td>
                                <td class="small text-muted">{f.parent_nome || '—'}</td>
                                <td><input class="form-control form-control-sm" aria-label="Inizio di {f.nome}"
                                           value={modifica?.orario_inizio ?? f.orario_inizio ?? ''}
                                           on:input={e => modificaFascia(f, 'orario_inizio', e.target.value)} /></td>
                                <td><input class="form-control form-control-sm" aria-label="Fine di {f.nome}"
                                           value={modifica?.orario_fine ?? f.orario_fine ?? ''}
                                           on:input={e => modificaFascia(f, 'orario_fine', e.target.value)} /></td>
                                <td><input class="form-control form-control-sm" type="number" min="0"
                                           aria-label="Pausa di {f.nome}"
                                           value={modifica?.pausa_minuti ?? f.pausa_minuti ?? 0}
                                           on:input={e => modificaFascia(f, 'pausa_minuti', e.target.value)} /></td>
                                <td class="small text-muted">{minToHm(f.durata_totale_minuti) || '—'}</td>
                                <td>
                                    {#if modifica}
                                        <button class="btn btn-warning btn-sm py-0" on:click={() => salvaFascia(f)}>
                                            Salva
                                        </button>
                                    {/if}
                                </td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </section>

            <section class="guidata-sezione guidata-inserimento">
                <h6 class="guidata-titolo">Aggiungi una fascia</h6>
                <div class="row g-3 align-items-end">
                    <div class="col-auto" style="width:180px">
                        <label class="form-label" for="fascia-nome">Nome</label>
                        <input id="fascia-nome" class="form-control form-control-sm"
                               placeholder="es. sera" bind:value={nuovaFascia.nome} />
                    </div>
                    <div class="col-auto" style="width:170px">
                        <label class="form-label" for="fascia-categoria">Categoria</label>
                        <select id="fascia-categoria" class="form-select form-select-sm" bind:value={nuovaFascia.parent_id}>
                            {#each concetti as c}
                                <option value={c.id}>{c.nome}</option>
                            {/each}
                        </select>
                    </div>
                    <div class="col-auto" style="width:110px">
                        <label class="form-label" for="fascia-inizio">Inizio</label>
                        <input id="fascia-inizio" class="form-control form-control-sm"
                               placeholder="16:00" bind:value={nuovaFascia.orario_inizio} />
                    </div>
                    <div class="col-auto" style="width:110px">
                        <label class="form-label" for="fascia-fine">Fine</label>
                        <input id="fascia-fine" class="form-control form-control-sm"
                               placeholder="22:20" bind:value={nuovaFascia.orario_fine} />
                    </div>
                    <div class="col-auto" style="width:110px">
                        <label class="form-label" for="fascia-pausa">Pausa (min)</label>
                        <input id="fascia-pausa" class="form-control form-control-sm" type="number" min="0"
                               bind:value={nuovaFascia.pausa_minuti} />
                    </div>
                    <div class="col-auto">
                        <button class="btn btn-primary btn-sm" disabled={!nuovaFasciaCompleta} on:click={aggiungiFascia}>
                            Aggiungi la fascia
                        </button>
                    </div>
                </div>
                <p class="guidata-aiuto mt-2 mb-0">
                    La categoria dice se la fascia è diurna, notturna o di guardia.
                    Il programma la usa per applicare le regole da sé: dopo una
                    notte, per esempio, il riposo del giorno dopo è obbligatorio.
                </p>
            </section>
        {/if}

        <!-- ═══ Tipologie turno ═══ -->
        {#if sezioneCorrente === 'tipologie'}
            <SezioneTipologie {tipologie} onaggiornate={ontipologieaggiornate} />
        {/if}

        <!-- ═══ Le strutture ═══ -->
        {#if sezioneCorrente === 'strutture'}
            <p class="guidata-intro">
                I turni si svolgono in un luogo: un reparto, un ambulatorio, un
                presidio. Scegli la parola che usate voi — da qui in avanti il
                programma userà quella.
            </p>

            <section class="guidata-sezione">
                <h6 class="guidata-titolo">Come li chiami</h6>
                <div class="d-flex gap-2 align-items-center flex-wrap">
                    {#each ETICHETTE_SUGGERITE as e}
                        <button class="btn btn-sm {!etichettaLibera && etichetta.singolare === e.singolare
                                                   ? 'btn-primary' : 'btn-outline-secondary'}"
                                on:click={() => scegliEtichetta(e)}>{e.plurale}</button>
                    {/each}
                    <button class="btn btn-sm {etichettaLibera ? 'btn-primary' : 'btn-outline-secondary'}"
                            on:click={() => scegliEtichetta(null)}>Un'altra parola…</button>
                </div>

                {#if etichettaLibera}
                    <div class="row g-3 align-items-end mt-1">
                        <div class="col-auto" style="width:200px">
                            <label class="form-label" for="etichetta-singolare">Uno solo</label>
                            <input id="etichetta-singolare" class="form-control form-control-sm"
                                   placeholder="es. Padiglione" bind:value={etichetta.singolare} />
                        </div>
                        <div class="col-auto" style="width:200px">
                            <label class="form-label" for="etichetta-plurale">Più di uno</label>
                            <input id="etichetta-plurale" class="form-control form-control-sm"
                                   placeholder="es. Padiglioni" bind:value={etichetta.plurale} />
                        </div>
                    </div>
                {/if}
            </section>

            <section class="guidata-sezione guidata-inserimento">
                <h6 class="guidata-titolo">{etichetta.plurale}</h6>
                <p class="guidata-aiuto">
                    Il nome è quello che vedrai sul calendario dei turni. L'ambito
                    è facoltativo e serve a distinguere due
                    {etichetta.plurale.toLowerCase()} che si chiamano allo stesso modo.
                </p>

                <table class="table table-sm align-middle mb-2">
                    <thead><tr>
                        <th style="width:280px">Nome</th>
                        <th style="width:240px">Ambito</th>
                        <th style="width:80px">Elimina</th>
                    </tr></thead>
                    <tbody>
                        {#each strutture as s, i}
                            <tr>
                                <td><input class="form-control form-control-sm"
                                           aria-label="Nome {etichetta.singolare.toLowerCase()} {i + 1}"
                                           placeholder="es. Radiologia Nord" bind:value={s.nome} /></td>
                                <td><input class="form-control form-control-sm"
                                           aria-label="Ambito {etichetta.singolare.toLowerCase()} {i + 1}"
                                           placeholder="es. Radiologia" bind:value={s.ambito} /></td>
                                <td><DeleteButton ondelete={() => rimuoviStruttura(i)} /></td>
                            </tr>
                        {/each}
                    </tbody>
                </table>

                <button class="btn btn-outline-primary btn-sm" on:click={aggiungiStruttura}>
                    <i class="bi bi-plus-lg me-1"></i>Aggiungi {etichetta.singolare.toLowerCase()}
                </button>
            </section>
        {/if}

        <!-- ═══ I turni ═══ -->
        {#if sezioneCorrente === 'turni'}
            <p class="guidata-intro">
                Per ogni {etichetta.singolare.toLowerCase()}, i turni che ci si
                svolgono e la fascia oraria in cui cadono. Due turni sulla stessa
                fascia si mettono insieme da soli: non devi crearci nulla attorno.
            </p>

            {#each struttureValide as s, i}
                <section class="guidata-sezione">
                    <div class="d-flex align-items-baseline justify-content-between mb-2">
                        <h6 class="guidata-titolo mb-0">
                            {s.nome}
                            {#if s.ambito}<span class="text-muted fw-normal small ms-1">{s.ambito}</span>{/if}
                        </h6>
                        <span class="text-muted small">
                            {s.turni.filter(t => t.nome.trim()).length}
                            {s.turni.filter(t => t.nome.trim()).length === 1 ? 'turno' : 'turni'}
                        </span>
                    </div>

                    {#if s.turni.length}
                        <table class="table table-sm align-middle mb-2">
                            <thead><tr>
                                <th style="width:210px">Nome</th>
                                <th style="width:210px">Fascia oraria</th>
                                <th style="width:170px">Tipologia</th>
                                <th style="width:120px">Duplica in…</th>
                                <th style="width:80px">Elimina</th>
                            </tr></thead>
                            <tbody>
                                {#each s.turni as t, j}
                                    <tr>
                                        <td>
                                            <input class="form-control form-control-sm" aria-label="Nome turno {j + 1}"
                                                   placeholder="es. TC mattina" bind:value={t.nome} />
                                        </td>
                                        <td>
                                            <select class="form-select form-select-sm" aria-label="Fascia turno {j + 1}"
                                                    bind:value={t.flag_id}>
                                                {#each fasceDisponibili as f}
                                                    <option value={f.id}>
                                                        {f.nome}{f.orario_inizio ? ` (${f.orario_inizio}–${f.orario_fine})` : ''}
                                                    </option>
                                                {/each}
                                            </select>
                                        </td>
                                        <td>
                                            {#if tipologie.length}
                                                <div class="dropdown">
                                                    <button class="btn btn-outline-secondary btn-sm py-0 dropdown-toggle w-100 text-truncate"
                                                            data-bs-toggle="dropdown" data-bs-auto-close="outside"
                                                            aria-expanded="false"
                                                            title="Che attività si svolge in questo turno">
                                                        {etichettaTipologie(t)}
                                                    </button>
                                                    <ul class="dropdown-menu px-2">
                                                        {#each tipologie as tipologia}
                                                            <li>
                                                                <label class="dropdown-item small d-flex align-items-center gap-2 px-1">
                                                                    <input type="checkbox"
                                                                           checked={(t.tipi_qualitativi ?? []).includes(tipologia.id)}
                                                                           on:change={() => commutaTipologia(t, tipologia.id)} />
                                                                    {tipologia.nome}
                                                                </label>
                                                            </li>
                                                        {/each}
                                                    </ul>
                                                </div>
                                            {:else}
                                                <span class="text-muted small">nessuna definita</span>
                                            {/if}
                                        </td>
                                        <td>
                                            <div class="btn-group">
                                                <button class="btn btn-outline-secondary btn-sm py-0"
                                                        title="Stessa fascia"
                                                        on:click={() => duplicaTurno(strutture.indexOf(s), j)}>
                                                    <i class="bi bi-copy"></i>
                                                </button>
                                                <button class="btn btn-outline-secondary btn-sm py-0 dropdown-toggle dropdown-toggle-split"
                                                        data-bs-toggle="dropdown" title="Altra fascia" aria-expanded="false">
                                                    <span class="visually-hidden">Scegli la fascia</span>
                                                </button>
                                                <ul class="dropdown-menu">
                                                    {#each fasceDisponibili as f}
                                                        <li>
                                                            <button class="dropdown-item small"
                                                                    on:click={() => duplicaTurno(strutture.indexOf(s), j, f.id)}>
                                                                {f.nome}
                                                                {#if f.id === t.flag_id}
                                                                    <span class="text-muted">(stessa)</span>
                                                                {/if}
                                                            </button>
                                                        </li>
                                                    {/each}
                                                </ul>
                                            </div>
                                        </td>
                                        <td>
                                            <DeleteButton ondelete={() => rimuoviTurno(strutture.indexOf(s), j)} />
                                        </td>
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                    {:else}
                        <p class="guidata-aiuto">
                            Ancora nessun turno in {s.nome}. Aggiungi il primo: gli
                            altri li ottieni duplicandolo, anche in un'altra fascia.
                        </p>
                    {/if}

                    <button class="btn btn-outline-primary btn-sm"
                            on:click={() => aggiungiTurno(strutture.indexOf(s))}>
                        <i class="bi bi-plus-lg me-1"></i>Aggiungi turno
                    </button>
                </section>
            {/each}

            <section class="guidata-sezione guidata-inserimento">
                <h6 class="guidata-titolo">Dai un nome a questa struttura turni</h6>
                <p class="guidata-aiuto">
                    È il nome con cui la sceglierai quando aprirai un calendario.
                    Di solito basta l'anno, o il nome del servizio.
                </p>
                <div style="width:280px">
                    <label class="form-label visually-hidden" for="nome-struttura-turni">Nome</label>
                    <input id="nome-struttura-turni" class="form-control form-control-sm"
                           use:focusOnMount placeholder="es. 2026" bind:value={nomePreset} />
                </div>
            </section>
        {/if}

        <!-- ═══ Le persone ═══ -->
        {#if sezioneCorrente === 'utenti'}
            <SezioneUtenti {utenti} strutture={sovragruppi} {etichetta}
                           onaggiornati={onutentiaggiornati} />
        {/if}

        <!-- ═══ Conteggi ═══ -->
        {#if sezioneCorrente === 'conteggi'}
            <SezioneConteggi {conteggi} fasce={fasceDisponibili} {tipologie}
                             onaggiornati={onconteggiaggiornati} />
        {/if}

        <!-- ═══ Vincoli ═══ -->
        {#if sezioneCorrente === 'vincoli'}
            <p class="guidata-intro">
                I tetti che il riempimento automatico non deve superare: quante
                notti al mese, quante TC, e gli scostamenti per singolo
                lavoratore. Si possono lasciare vuoti e metterli più avanti.
            </p>
            <section class="guidata-sezione">
                <VincoliSolver {adminApi} flagTurno={fasce} tipiQualitativo={tipologie}
                               initGlobali={vincoliGlobali} initSolver={vincoliSolver}
                               onmsg={(testo, ok) => { if (!ok) errore = testo; }} />
            </section>
        {/if}
    </div>

    <div class="card-footer d-flex justify-content-between align-items-center">
        <button class="btn btn-outline-secondary btn-sm" disabled={passo === 0}
                on:click={() => vaiA(passo - 1)}>
            <i class="bi bi-arrow-left me-1"></i>Indietro
        </button>

        <span class="text-muted small">
            {struttureValide.length}
            {struttureValide.length === 1
                ? etichetta.singolare.toLowerCase()
                : etichetta.plurale.toLowerCase()}
            · {turniTotali} {turniTotali === 1 ? 'turno' : 'turni'}
        </span>

        <div class="d-flex align-items-center gap-2">
            {#if cosaManca}
                <span class="text-muted small">{cosaManca}</span>
            {/if}
            {#if passo < sezioni.length - 1}
                <button class="btn btn-outline-primary btn-sm"
                        on:click={() => vaiA(passo + 1)}>
                    Avanti<i class="bi bi-arrow-right ms-1"></i>
                </button>
            {/if}
            <button class="btn btn-success btn-sm" disabled={!puoSalvare || salvataggio}
                    on:click={completa}>
                {salvataggio ? 'Salvataggio…'
                 : presetEsistente ? 'Aggiorna la configurazione'
                 : 'Salva la configurazione'}
            </button>
        </div>
    </div>
</div>

<style>
    .guidata {
        max-width: 1040px;
    }

    /* ── I passi ─────────────────────────────────────────────────────── */
    .guidata-passi {
        border-bottom: 1px solid var(--bs-border-color);
        background: var(--bs-tertiary-bg);
    }
    .guidata-passo + .guidata-passo {
        border-left: 1px solid var(--bs-border-color);
    }
    .guidata-numero {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.6rem;
        height: 1.6rem;
        border-radius: 50%;
        font-size: .8rem;
        font-weight: 600;
        border: 1px solid var(--bs-border-color);
        color: var(--bs-secondary-color);
        background: var(--bs-body-bg);
    }
    .guidata-passo.corrente {
        background: var(--bs-body-bg);
        font-weight: 600;
    }
    .guidata-passo.corrente .guidata-numero {
        background: var(--bs-primary);
        border-color: var(--bs-primary);
        color: #fff;
    }
    .guidata-passo.fatto .guidata-numero {
        background: var(--bs-success);
        border-color: var(--bs-success);
        color: #fff;
    }
    .guidata-passo.futuro {
        color: var(--bs-secondary-color);
    }

    /* ── Riquadri ────────────────────────────────────────────────────── */
    .guidata-intro {
        font-size: .9rem;
        color: var(--bs-secondary-color);
        max-width: 62ch;
    }
    .guidata-sezione {
        border: 1px solid var(--bs-border-color);
        border-radius: .5rem;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    /* Dove si inserisce qualcosa di nuovo, invece che modificare l'esistente. */
    .guidata-sezione.guidata-inserimento {
        background: var(--bs-tertiary-bg);
    }
    .guidata-titolo {
        font-size: .8rem;
        text-transform: uppercase;
        letter-spacing: .04em;
        color: var(--bs-secondary-color);
        margin-bottom: .5rem;
    }
    .guidata-aiuto {
        font-size: .8rem;
        color: var(--bs-secondary-color);
        margin-bottom: .75rem;
    }
    .guidata-sezione :global(.form-label) {
        font-size: .78rem;
        font-weight: 600;
        color: var(--bs-secondary-color);
        margin-bottom: .2rem;
    }
    .guidata-sezione :global(.table > thead th) {
        font-size: .75rem;
        text-transform: uppercase;
        letter-spacing: .03em;
        font-weight: 600;
        color: var(--bs-secondary-color);
        border-bottom-width: 1px;
    }
    /* Il campo attivo si vede da lontano: e' la domanda "dove scrivo?". */
    .guidata-sezione :global(.form-control:focus),
    .guidata-sezione :global(.form-select:focus) {
        border-color: var(--bs-primary);
        box-shadow: 0 0 0 .2rem rgba(var(--bs-primary-rgb), .2);
    }
</style>
