<!--
  SezioneTipologie — le tipologie di turno (TC, RM, ambulatorio).

  Una tipologia dice *che attivita'* si svolge in un turno, mentre la fascia
  oraria dice *quando*. Servono ai conteggi e ai limiti del solver, ed e' la
  parte che un'installazione nuova trova vuota.

  Scrive subito: le tipologie sono globali, non c'e' niente da confermare
  alla fine.

  Props:
    - tipologie   : Array — tipi qualitativo esistenti
    - onaggiornate: () => Promise — ricarica l'elenco nel chiamante
-->
<script>
    import { adminApi } from '$lib/api.js';
    import DeleteButton from '../DeleteButton.svelte';

    export let tipologie = [];
    export let onaggiornate;

    let nuova = { nome: '', descrizione: '', carico_lavoro: 0 };
    let errore = '';

    $: puoAggiungere = nuova.nome.trim().length > 0;

    async function aggiungi() {
        if (!puoAggiungere) return;

        errore = '';
        const r = await adminApi.creaTipoQualitativo({ ...nuova });
        if (!r.ok) { errore = r.errore || 'Creazione non riuscita.'; return; }

        nuova = { nome: '', descrizione: '', carico_lavoro: 0 };
        await onaggiornate();
    }

    async function elimina(id) {
        errore = '';
        const r = await adminApi.delTipoQualitativo(id);
        if (!r.ok) { errore = r.errore || 'Eliminazione non riuscita.'; return; }

        await onaggiornate();
    }
</script>

<p class="guidata-intro">
    Una tipologia dice che attività si svolge in un turno — TC, risonanza,
    ambulatorio — mentre la fascia oraria dice quando. Servono a contare
    "quante TC ha fatto questo mese" e a metterci un tetto.
</p>

{#if errore}<div class="alert alert-danger py-2 small">{errore}</div>{/if}

<section class="guidata-sezione">
    <h6 class="guidata-titolo">Le tipologie definite</h6>

    {#if tipologie.length}
        <table class="table table-sm align-middle mb-0">
            <thead><tr>
                <th style="width:180px">Nome</th>
                <th style="width:240px">Descrizione</th>
                <th style="width:110px" title="Quanto pesa sul carico di lavoro">Carico</th>
                <th style="width:80px">Elimina</th>
            </tr></thead>
            <tbody>
                {#each tipologie as t (t.id)}
                    <tr>
                        <td class="fw-semibold">{t.nome}</td>
                        <td class="small text-muted">{t.descrizione || '—'}</td>
                        <td class="small">{t.carico_lavoro ?? 0}</td>
                        <td><DeleteButton ondelete={() => elimina(t.id)} /></td>
                    </tr>
                {/each}
            </tbody>
        </table>
    {:else}
        <p class="guidata-aiuto mb-0">
            Nessuna tipologia. Se i tuoi turni si distinguono solo per orario
            puoi saltare questo passo.
        </p>
    {/if}
</section>

<section class="guidata-sezione guidata-inserimento">
    <h6 class="guidata-titolo">Aggiungi una tipologia</h6>
    <div class="row g-3 align-items-end">
        <div class="col-auto" style="width:200px">
            <label class="form-label" for="tipologia-nome">Nome</label>
            <input id="tipologia-nome" class="form-control form-control-sm"
                   placeholder="es. TC" bind:value={nuova.nome}
                   on:keydown={e => e.key === 'Enter' && aggiungi()} />
        </div>
        <div class="col-auto" style="width:260px">
            <label class="form-label" for="tipologia-descrizione">Descrizione</label>
            <input id="tipologia-descrizione" class="form-control form-control-sm"
                   placeholder="es. Tomografia computerizzata"
                   bind:value={nuova.descrizione}
                   on:keydown={e => e.key === 'Enter' && aggiungi()} />
        </div>
        <div class="col-auto" style="width:120px">
            <label class="form-label" for="tipologia-carico">Carico</label>
            <input id="tipologia-carico" class="form-control form-control-sm" type="number"
                   bind:value={nuova.carico_lavoro} />
        </div>
        <div class="col-auto">
            <button class="btn btn-primary btn-sm" disabled={!puoAggiungere} on:click={aggiungi}>
                Aggiungi la tipologia
            </button>
        </div>
    </div>
</section>
