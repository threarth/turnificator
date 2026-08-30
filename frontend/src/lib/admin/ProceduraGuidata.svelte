<!--
  ProceduraGuidata — accompagna alla creazione della struttura turni chi non
  conosce il sistema.

  Nuova feature. I tre livelli interni — sovragruppo, gruppo, turno — qui non
  si vedono: l'utente definisce le fasce orarie, poi le sue strutture (che
  chiama come vuole: reparto, ambulatorio, presidio), poi i turni di ciascuna.
  Il gruppo, che e' l'insieme dei turni di una fascia dentro una struttura,
  nasce da solo: due turni sulla stessa fascia finiscono nello stesso gruppo.

  Non tocca le strutture esistenti: crea sempre un preset nuovo, e alla fine
  lo consegna all'editor normale.

  Props:
    - fasce           : Array — flag_turno, come li carica la pagina admin
    - etichetta       : {singolare, plurale} — come l'utente chiama le strutture
    - oncompletata    : (presetId, etichetta) => void — preset creato
    - onannulla       : () => void — uscita senza creare nulla
    - onfasceaggiornate : () => Promise — ricarica i flag nel chiamante
-->
<script>
    import { adminApi } from '$lib/api.js';
    import { focusOnMount } from './actions.js';
    import DeleteButton from './DeleteButton.svelte';
    import { minToHm } from './durate.js';
    import { costruisciStruttura } from './struttura.js';

    export let fasce = [];
    export let etichetta = { singolare: 'Struttura', plurale: 'Strutture' };
    export let oncompletata;
    export let onannulla;
    export let onfasceaggiornate;

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

    const PASSI = [
        'Fasce orarie',
        'Le tue strutture',
        'I turni',
    ];

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
            { nome: '', flag_id: fasceDisponibili[0]?.id ?? null },
        ];
        strutture = [...strutture];
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

    $: puoAvanzare = [
        fasceDisponibili.length > 0,
        struttureValide.length > 0 && etichetta.singolare.trim(),
        turniTotali > 0 && nomePreset.trim(),
    ][passo];

    async function completa() {
        if (!puoAvanzare || salvataggio) return;

        salvataggio = true;
        errore = '';

        const creato = await adminApi.creaPreset({ nome: nomeCompletoPreset(nomePreset) });
        if (!creato.ok) {
            errore = creato.errore || 'Creazione del preset non riuscita.';
            salvataggio = false;
            return;
        }

        const salvato = await adminApi.salvaStrutturaPreset(creato.id, {
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
        oncompletata(creato.id, { ...etichetta });
    }

    // I preset di struttura portano tutti lo stesso prefisso.
    function nomeCompletoPreset(nome) {
        const pulito = nome.trim();
        return pulito.startsWith('struttura_') ? pulito : `struttura_${pulito}`;
    }
</script>

<div class="card" style="max-width:960px">
    <div class="card-header d-flex align-items-center justify-content-between">
        <span class="fw-semibold"><i class="bi bi-magic me-2"></i>Procedura guidata</span>
        <button class="btn btn-sm btn-outline-secondary" on:click={onannulla}>
            <i class="bi bi-x-lg me-1"></i>Esci
        </button>
    </div>

    <div class="card-body">
        <!-- Avanzamento -->
        <div class="d-flex gap-2 mb-4">
            {#each PASSI as nome, i}
                <div class="flex-fill text-center small pb-1 border-bottom border-3
                            {i === passo ? 'border-primary fw-semibold text-primary'
                             : i < passo ? 'border-success text-success' : 'border-light text-muted'}">
                    {#if i < passo}<i class="bi bi-check-lg me-1"></i>{/if}{nome}
                </div>
            {/each}
        </div>

        {#if errore}
            <div class="alert alert-danger py-2 small">{errore}</div>
        {/if}

        <!-- ═══ Passo 1: fasce orarie ═══ -->
        {#if passo === 0}
            <p class="text-muted small">
                Una fascia oraria dice quando comincia e quando finisce un turno.
                Le ore e il peso li calcola il sistema dagli orari. Le fasce valgono
                per tutta l'installazione: quelle che vedi qui sono già disponibili.
            </p>

            <table class="table table-sm align-middle" style="font-size:.85rem">
                <thead><tr>
                    <th style="width:150px">Fascia</th>
                    <th style="width:110px">Categoria</th>
                    <th style="width:90px">Inizio</th>
                    <th style="width:90px">Fine</th>
                    <th style="width:90px">Pausa</th>
                    <th style="width:80px">Durata</th>
                    <th style="width:70px"></th>
                </tr></thead>
                <tbody>
                    {#each fasceDisponibili as f (f.id)}
                        {@const modifica = modificheFasce[f.id]}
                        <tr>
                            <td class="fw-semibold">{f.nome}</td>
                            <td class="small text-muted">{f.parent_nome || '—'}</td>
                            <td><input class="form-control form-control-sm"
                                       value={modifica?.orario_inizio ?? f.orario_inizio ?? ''}
                                       on:input={e => modificaFascia(f, 'orario_inizio', e.target.value)} /></td>
                            <td><input class="form-control form-control-sm"
                                       value={modifica?.orario_fine ?? f.orario_fine ?? ''}
                                       on:input={e => modificaFascia(f, 'orario_fine', e.target.value)} /></td>
                            <td><input class="form-control form-control-sm" type="number" min="0"
                                       value={modifica?.pausa_minuti ?? f.pausa_minuti ?? 0}
                                       on:input={e => modificaFascia(f, 'pausa_minuti', e.target.value)} /></td>
                            <td class="small text-muted">{minToHm(f.durata_totale_minuti) || '—'}</td>
                            <td>
                                {#if modifica}
                                    <button class="btn btn-success btn-sm py-0" on:click={() => salvaFascia(f)}>
                                        <i class="bi bi-check-lg"></i>
                                    </button>
                                {/if}
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>

            <div class="border-top pt-3 mt-2">
                <div class="small fw-semibold mb-2">Aggiungi una fascia</div>
                <div class="d-flex gap-2 align-items-center flex-wrap">
                    <input class="form-control form-control-sm" style="width:160px" placeholder="Nome (es. sera)"
                           bind:value={nuovaFascia.nome} />
                    <select class="form-select form-select-sm" style="width:150px" bind:value={nuovaFascia.parent_id}>
                        {#each concetti as c}
                            <option value={c.id}>{c.nome}</option>
                        {/each}
                    </select>
                    <input class="form-control form-control-sm" style="width:90px" placeholder="Inizio"
                           bind:value={nuovaFascia.orario_inizio} />
                    <input class="form-control form-control-sm" style="width:90px" placeholder="Fine"
                           bind:value={nuovaFascia.orario_fine} />
                    <input class="form-control form-control-sm" style="width:90px" type="number" min="0"
                           title="Pausa obbligatoria (minuti)" bind:value={nuovaFascia.pausa_minuti} />
                    <button class="btn btn-primary btn-sm" disabled={!nuovaFasciaCompleta} on:click={aggiungiFascia}>
                        <i class="bi bi-plus-lg me-1"></i>Aggiungi
                    </button>
                </div>
                <div class="form-text small">
                    La categoria dice se la fascia è diurna, notturna o una guardia:
                    da lì discendono le regole sul riposo dopo la notte.
                </div>
            </div>
        {/if}

        <!-- ═══ Passo 2: le strutture ═══ -->
        {#if passo === 1}
            <p class="text-muted small">
                Come chiami i luoghi in cui si svolgono i turni? La parola che scegli
                verrà usata dal resto del programma.
            </p>

            <div class="d-flex gap-2 align-items-center flex-wrap mb-3">
                {#each ETICHETTE_SUGGERITE as e}
                    <button class="btn btn-sm {!etichettaLibera && etichetta.singolare === e.singolare
                                               ? 'btn-primary' : 'btn-outline-secondary'}"
                            on:click={() => scegliEtichetta(e)}>{e.plurale}</button>
                {/each}
                <button class="btn btn-sm {etichettaLibera ? 'btn-primary' : 'btn-outline-secondary'}"
                        on:click={() => scegliEtichetta(null)}>Altro…</button>
            </div>

            {#if etichettaLibera}
                <div class="d-flex gap-2 align-items-center flex-wrap mb-3">
                    <input class="form-control form-control-sm" style="width:180px" placeholder="Singolare"
                           bind:value={etichetta.singolare} />
                    <input class="form-control form-control-sm" style="width:180px" placeholder="Plurale"
                           bind:value={etichetta.plurale} />
                </div>
            {/if}

            <div class="fw-semibold small mb-2">{etichetta.plurale}</div>
            {#each strutture as s, i}
                <div class="d-flex gap-2 align-items-center mb-2">
                    <input class="form-control form-control-sm" style="width:240px"
                           placeholder={etichetta.singolare} bind:value={s.nome} />
                    <input class="form-control form-control-sm" style="width:200px"
                           placeholder="Ambito (facoltativo, es. Radiologia)" bind:value={s.ambito} />
                    <DeleteButton ondelete={() => rimuoviStruttura(i)} />
                </div>
            {/each}
            <button class="btn btn-outline-primary btn-sm mt-1" on:click={aggiungiStruttura}>
                <i class="bi bi-plus-lg me-1"></i>Aggiungi {etichetta.singolare.toLowerCase()}
            </button>
        {/if}

        <!-- ═══ Passo 3: i turni ═══ -->
        {#if passo === 2}
            <p class="text-muted small">
                Per ogni {etichetta.singolare.toLowerCase()}, i turni che si svolgono
                e in quale fascia oraria cadono. I turni della stessa fascia finiscono
                insieme da soli.
            </p>

            {#each struttureValide as s, i}
                <div class="border rounded p-2 mb-3">
                    <div class="fw-semibold mb-2">
                        {s.nome}
                        {#if s.ambito}<span class="text-muted small ms-1">({s.ambito})</span>{/if}
                    </div>

                    {#each s.turni as t, j}
                        <div class="d-flex gap-2 align-items-center mb-2">
                            <input class="form-control form-control-sm" style="width:220px"
                                   placeholder="Nome del turno" bind:value={t.nome} />
                            <select class="form-select form-select-sm" style="width:200px" bind:value={t.flag_id}>
                                {#each fasceDisponibili as f}
                                    <option value={f.id}>
                                        {f.nome}{f.orario_inizio ? ` (${f.orario_inizio}–${f.orario_fine})` : ''}
                                    </option>
                                {/each}
                            </select>
                            <DeleteButton ondelete={() => rimuoviTurno(strutture.indexOf(s), j)} />
                        </div>
                    {/each}

                    <button class="btn btn-outline-primary btn-sm"
                            on:click={() => aggiungiTurno(strutture.indexOf(s))}>
                        <i class="bi bi-plus-lg me-1"></i>Aggiungi turno
                    </button>
                </div>
            {/each}

            <div class="border-top pt-3">
                <div class="d-flex gap-2 align-items-center flex-wrap">
                    <label class="form-label mb-0 small text-muted" for="nome-struttura-turni">
                        Nome di questa struttura turni
                    </label>
                    <input id="nome-struttura-turni" class="form-control form-control-sm" style="width:240px"
                           use:focusOnMount placeholder="es. 2026" bind:value={nomePreset} />
                </div>
                <div class="form-text small">
                    {struttureValide.length}
                    {struttureValide.length === 1
                        ? etichetta.singolare.toLowerCase()
                        : etichetta.plurale.toLowerCase()},
                    {turniTotali} {turniTotali === 1 ? 'turno' : 'turni'} in tutto.
                </div>
            </div>
        {/if}
    </div>

    <div class="card-footer d-flex justify-content-between">
        <button class="btn btn-outline-secondary btn-sm" disabled={passo === 0}
                on:click={() => { errore = ''; passo -= 1; }}>
            <i class="bi bi-arrow-left me-1"></i>Indietro
        </button>

        {#if passo < PASSI.length - 1}
            <button class="btn btn-primary btn-sm" disabled={!puoAvanzare}
                    on:click={() => { errore = ''; passo += 1; }}>
                Avanti<i class="bi bi-arrow-right ms-1"></i>
            </button>
        {:else}
            <button class="btn btn-success btn-sm" disabled={!puoAvanzare || salvataggio} on:click={completa}>
                <i class="bi bi-check-lg me-1"></i>{salvataggio ? 'Creazione…' : 'Crea la struttura turni'}
            </button>
        {/if}
    </div>
</div>
