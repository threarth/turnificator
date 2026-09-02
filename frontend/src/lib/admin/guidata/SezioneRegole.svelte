<!--
  SezioneRegole — le regole che dicono quali turni non stanno insieme.

  Sono la parte che protegge il lavoratore: il riposo dopo la notte, il
  divieto di due turni lo stesso giorno, il rispetto delle assenze chieste.
  Il solver le applica come vincoli invalicabili, e il caposala le vede
  colorate nella griglia.

  Qui si leggono come frasi, non come righe di tabella: chi configura deve
  capire cosa vieta una regola senza sapere cos'è un `tipo_vs_tipo`.

  Props:
    - regole      : Array — regole configurate
    - fasce       : Array — fasce e concetti a cui una regola può puntare
    - onaggiornate: () => Promise — ricarica le regole nel chiamante
-->
<script>
    import { adminApi } from '$lib/api.js';
    import DeleteButton from '../DeleteButton.svelte';

    export let regole = [];
    export let fasce = [];
    export let onaggiornate;

    // Quanto pesa una violazione. "Critica" ferma il riempimento automatico;
    // "consigliata" lo lascia passare e colora la cella.
    const SEVERITA = [
        { valore: 'critica',     nome: 'Critica' },
        { valore: 'consigliata', nome: 'Consigliata' },
    ];

    // Le regole che si possono scrivere da qui. Le altre due — quelle sui
    // desiderata — esistono in copia unica e non si moltiplicano.
    const QUANDO = [
        { valore: 0, nome: 'lo stesso giorno' },
        { valore: 1, nome: 'il giorno dopo' },
    ];

    let nuova = regolaVuota();
    let errore = '';

    function regolaVuota() {
        return { nome: '', tipo_regola: 'tipo_vs_tipo', flag_a_id: null,
                 flag_b_id: null, offset_giorni: 0, categoria: 'critica',
                 blocca_inserimento: 0, peso_numerico: 8.0, is_active: 1 };
    }

    function nomeFascia(id) {
        if (id === null || id === undefined) return 'un turno qualsiasi';
        return fasce.find(f => f.id === id)?.nome ?? '—';
    }

    /**
     * La regola detta in italiano.
     *
     * È il punto della sezione: `tipo_vs_tipo / notturno / diurno / offset 1`
     * non dice niente a chi configura, «dopo un turno notturno, il giorno dopo
     * niente turni diurni» sì.
     */
    function inParole(r) {
        if (r.tipo_regola === 'desiderata_assenza_mismatch') {
            return 'Assegnare un turno a chi ha chiesto un’assenza.';
        }
        if (r.tipo_regola === 'desiderata_mismatch') {
            return 'Assegnare una fascia diversa da quella che il lavoratore aveva chiesto.';
        }

        const a = nomeFascia(r.flag_a_id);
        const b = nomeFascia(r.flag_b_id);
        return r.offset_giorni === 1
            ? `Dopo ${a}, il giorno dopo ${b}.`
            : `${a} insieme a ${b}, lo stesso giorno.`;
    }

    $: puoAggiungere = nuova.nome.trim() && nuova.flag_a_id !== null;

    async function aggiungi() {
        if (!puoAggiungere) return;

        errore = '';
        const r = await adminApi.creaRegola({ ...nuova });
        if (!r.ok) { errore = r.errore || 'Creazione non riuscita.'; return; }

        nuova = regolaVuota();
        await onaggiornate();
    }

    async function cambiaSeverita(regola, categoria) {
        errore = '';
        const r = await adminApi.editRegola(regola.id, { ...regola, categoria });
        if (!r.ok) { errore = r.errore || 'Modifica non riuscita.'; return; }

        await onaggiornate();
    }

    async function commutaAttiva(regola) {
        errore = '';
        const r = await adminApi.editRegola(regola.id, {
            ...regola, is_active: regola.is_active ? 0 : 1,
        });
        if (!r.ok) { errore = r.errore || 'Modifica non riuscita.'; return; }

        await onaggiornate();
    }

    async function elimina(id) {
        errore = '';
        const r = await adminApi.delRegola(id);
        if (!r.ok) { errore = r.errore || 'Eliminazione non riuscita.'; return; }

        await onaggiornate();
    }
</script>

<p class="guidata-intro">
    Le regole dicono quali turni non possono stare insieme — il riposo dopo la
    notte, due turni nello stesso giorno — e cosa succede se il lavoratore
    aveva chiesto altro. Il riempimento automatico non le viola mai; al
    caposala compaiono come celle colorate.
</p>

{#if errore}<div class="alert alert-danger py-2 small">{errore}</div>{/if}

<section class="guidata-sezione">
    <h6 class="guidata-titolo">Le regole in vigore</h6>

    {#if regole.length}
        <table class="table table-sm align-middle mb-0">
            <thead><tr>
                <th style="width:180px">Nome</th>
                <th>Cosa vieta</th>
                <th style="width:150px">Severità</th>
                <th style="width:90px">Attiva</th>
                <th style="width:80px">Elimina</th>
            </tr></thead>
            <tbody>
                {#each regole as r (r.id)}
                    <tr class:text-muted={!r.is_active}>
                        <td class="fw-semibold">{r.nome}</td>
                        <td class="small">{inParole(r)}</td>
                        <td>
                            <select class="form-select form-select-sm" value={r.categoria}
                                    on:change={e => cambiaSeverita(r, e.target.value)}>
                                {#each SEVERITA as s}<option value={s.valore}>{s.nome}</option>{/each}
                            </select>
                        </td>
                        <td>
                            <input type="checkbox" checked={!!r.is_active}
                                   on:change={() => commutaAttiva(r)} />
                        </td>
                        <td><DeleteButton ondelete={() => elimina(r.id)} /></td>
                    </tr>
                {/each}
            </tbody>
        </table>
        <p class="guidata-aiuto mt-2 mb-0">
            <strong>Critica</strong> ferma il riempimento automatico.
            <strong>Consigliata</strong> lo lascia passare e segnala la cella.
        </p>
    {:else}
        <p class="guidata-aiuto mb-0">
            Nessuna regola. Senza almeno il riposo dopo la notte il riempimento
            automatico può assegnare un turno il giorno dopo una notte.
        </p>
    {/if}
</section>

<section class="guidata-sezione guidata-inserimento">
    <h6 class="guidata-titolo">Aggiungi una regola</h6>
    <p class="guidata-aiuto">
        Si legge come una frase: «dopo <em>la notte</em>, il giorno dopo
        <em>un turno diurno</em>». Lasciando vuoto il secondo campo la regola
        vale per qualunque turno.
    </p>

    <div class="row g-3 align-items-end">
        <div class="col-auto" style="width:200px">
            <label class="form-label" for="regola-nome">Come la chiami</label>
            <input id="regola-nome" class="form-control form-control-sm"
                   placeholder="es. Riposo post-notte" bind:value={nuova.nome} />
        </div>
        <div class="col-auto" style="width:180px">
            <label class="form-label" for="regola-a">Chi fa…</label>
            <select id="regola-a" class="form-select form-select-sm" bind:value={nuova.flag_a_id}>
                <option value={null}>— scegli —</option>
                {#each fasce as f}
                    <option value={f.id}>{f.parent_nome ? f.parent_nome + '→' : ''}{f.nome}</option>
                {/each}
            </select>
        </div>
        <div class="col-auto" style="width:170px">
            <label class="form-label" for="regola-quando">non può fare…</label>
            <select id="regola-quando" class="form-select form-select-sm"
                    bind:value={nuova.offset_giorni}>
                {#each QUANDO as q}<option value={q.valore}>{q.nome}</option>{/each}
            </select>
        </div>
        <div class="col-auto" style="width:180px">
            <label class="form-label" for="regola-b">questo turno</label>
            <select id="regola-b" class="form-select form-select-sm" bind:value={nuova.flag_b_id}>
                <option value={null}>qualsiasi</option>
                {#each fasce as f}
                    <option value={f.id}>{f.parent_nome ? f.parent_nome + '→' : ''}{f.nome}</option>
                {/each}
            </select>
        </div>
        <div class="col-auto" style="width:150px">
            <label class="form-label" for="regola-severita">Severità</label>
            <select id="regola-severita" class="form-select form-select-sm"
                    bind:value={nuova.categoria}>
                {#each SEVERITA as s}<option value={s.valore}>{s.nome}</option>{/each}
            </select>
        </div>
        <div class="col-auto">
            <button class="btn btn-primary btn-sm" disabled={!puoAggiungere} on:click={aggiungi}>
                Aggiungi la regola
            </button>
        </div>
    </div>

    {#if nuova.flag_a_id !== null}
        <p class="guidata-aiuto mt-2 mb-0">
            Vieterà: <em>{inParole(nuova)}</em>
        </p>
    {/if}
</section>
