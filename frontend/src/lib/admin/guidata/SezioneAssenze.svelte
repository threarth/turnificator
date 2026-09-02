<!--
  SezioneAssenze — le assenze e cosa un lavoratore può chiedere.

  È l'altra metà del vocabolario: la sezione delle fasce dice quando si
  lavora, questa dice quando non si lavora e come lo si chiede.

  Due cose distinte e legate:
  - **le assenze** sono le categorie (ferie, malattia, riposo);
  - **i tipi richiesta** sono le voci che il lavoratore sceglie quando compila
    i desiderata, e che possono puntare a una fascia o a un'assenza.

  Scrive subito, come le altre sezioni globali.

  Props:
    - assenze       : Array — flag_turno di tipo assenza
    - fasce         : Array — fasce orarie, a cui un tipo richiesta può puntare
    - tipiRichiesta : Array — le voci richiedibili
    - onaggiornate  : () => Promise — ricarica flag e tipi nel chiamante
-->
<script>
    import { adminApi } from '$lib/api.js';
    import DeleteButton from '../DeleteButton.svelte';

    export let assenze = [];
    export let fasce = [];
    export let tipiRichiesta = [];
    export let onaggiornate;

    let nuovaAssenza = { nome: '', descrizione: '' };
    let nuovoTipo = tipoVuoto();
    let errore = '';
    let inCorso = false;

    function tipoVuoto() {
        return { sigla: '', descrizione: '', tipo: 'assenza', flag_id: null,
                 counting_flag: 1, ordine: 0 };
    }

    $: puoAggiungereAssenza = nuovaAssenza.nome.trim();
    $: puoAggiungereTipo = nuovoTipo.sigla.trim() && nuovoTipo.descrizione.trim();

    // Un tipo richiesta punta a una fascia se è lavorativo, a un'assenza se no.
    $: bersagli = nuovoTipo.tipo === 'assenza' ? assenze : fasce;

    function nomeBersaglio(flagId) {
        const f = [...assenze, ...fasce].find(x => x.id === flagId);
        return f ? f.nome : '—';
    }

    async function aggiungiAssenza() {
        if (!puoAggiungereAssenza) return;

        errore = '';
        const r = await adminApi.creaFlagTurno({ ...nuovaAssenza, tipo: 'assenza' });
        if (!r.ok) { errore = r.errore || 'Creazione non riuscita.'; return; }

        nuovaAssenza = { nome: '', descrizione: '' };
        await onaggiornate();
    }

    async function eliminaAssenza(id) {
        errore = '';
        const r = await adminApi.delFlagTurno(id);
        if (!r.ok) { errore = r.errore || 'Eliminazione non riuscita.'; return; }

        await onaggiornate();
    }

    async function aggiungiTipo() {
        if (!puoAggiungereTipo) return;

        errore = '';
        const r = await adminApi.creaTipo({ ...nuovoTipo });
        if (!r.ok) { errore = r.errore || 'Creazione non riuscita.'; return; }

        nuovoTipo = tipoVuoto();
        await onaggiornate();
    }

    async function eliminaTipo(id) {
        errore = '';
        const r = await adminApi.delTipo(id);
        if (!r.ok) { errore = r.errore || 'Eliminazione non riuscita.'; return; }

        await onaggiornate();
    }

    /** Rimette le voci di serie che mancano, senza toccare quelle presenti. */
    async function riprendiDefault() {
        inCorso = true;
        errore = '';

        await adminApi.ripristinaFlagDefault();
        const r = await adminApi.ripristinaTipiDefault();

        inCorso = false;
        if (!r.ok) { errore = r.errore || 'Ripristino non riuscito.'; return; }

        await onaggiornate();
    }
</script>

<p class="guidata-intro">
    L'altra metà del vocabolario: quando non si lavora, e come il lavoratore lo
    chiede. Le assenze sono le categorie — ferie, malattia, riposo — e i tipi
    richiesta sono le voci che compaiono quando compila i desiderata.
</p>

{#if errore}<div class="alert alert-danger py-2 small">{errore}</div>{/if}

{#if !assenze.length && !tipiRichiesta.length}
    <section class="guidata-sezione guidata-inserimento">
        <h6 class="guidata-titolo">Comincia dalle voci di serie</h6>
        <p class="guidata-aiuto">
            Ferie, malattia, riposo, permesso, aggiornamento e i recuperi ore:
            sono quelle che usano quasi tutti, e si possono rinominare dopo.
        </p>
        <button class="btn btn-primary btn-sm" disabled={inCorso} on:click={riprendiDefault}>
            {inCorso ? 'Inserisco…' : 'Inserisci le voci di serie'}
        </button>
    </section>
{/if}

<section class="guidata-sezione">
    <h6 class="guidata-titolo">Le assenze</h6>
    <p class="guidata-aiuto">
        Un'assenza non ha orari e non entra mai nella struttura turni: dice solo
        che quel giorno la persona non c'è.
    </p>

    {#if assenze.length}
        <table class="table table-sm align-middle mb-0">
            <thead><tr>
                <th style="width:170px">Nome</th>
                <th style="width:280px">Descrizione</th>
                <th style="width:80px">Elimina</th>
            </tr></thead>
            <tbody>
                {#each assenze as a (a.id)}
                    <tr>
                        <td class="fw-semibold">{a.nome}</td>
                        <td class="small text-muted">{a.descrizione || '—'}</td>
                        <td><DeleteButton ondelete={() => eliminaAssenza(a.id)} /></td>
                    </tr>
                {/each}
            </tbody>
        </table>
    {:else}
        <p class="guidata-aiuto mb-0">Nessuna assenza definita.</p>
    {/if}
</section>

<section class="guidata-sezione guidata-inserimento">
    <h6 class="guidata-titolo">Aggiungi un'assenza</h6>
    <div class="row g-3 align-items-end">
        <div class="col-auto" style="width:190px">
            <label class="form-label" for="assenza-nome">Nome</label>
            <input id="assenza-nome" class="form-control form-control-sm"
                   placeholder="es. congedo" bind:value={nuovaAssenza.nome}
                   on:keydown={e => e.key === 'Enter' && aggiungiAssenza()} />
        </div>
        <div class="col-auto" style="width:280px">
            <label class="form-label" for="assenza-descrizione">Descrizione</label>
            <input id="assenza-descrizione" class="form-control form-control-sm"
                   bind:value={nuovaAssenza.descrizione}
                   on:keydown={e => e.key === 'Enter' && aggiungiAssenza()} />
        </div>
        <div class="col-auto">
            <button class="btn btn-primary btn-sm" disabled={!puoAggiungereAssenza}
                    on:click={aggiungiAssenza}>Aggiungi l'assenza</button>
        </div>
    </div>
</section>

<section class="guidata-sezione">
    <h6 class="guidata-titolo">Cosa può chiedere un lavoratore</h6>
    <p class="guidata-aiuto">
        La sigla è quella che comparirà nella griglia dei desiderata. "Conta le
        ore" dice se quel giorno entra nel monte ore — il recupero del mese
        corrente, per esempio, non conta, perché è già nelle ore lavorate.
    </p>

    {#if tipiRichiesta.length}
        <table class="table table-sm align-middle mb-0">
            <thead><tr>
                <th style="width:90px">Sigla</th>
                <th style="width:230px">Descrizione</th>
                <th style="width:110px">Tipo</th>
                <th style="width:150px">Si riferisce a</th>
                <th style="width:110px">Conta le ore</th>
                <th style="width:80px">Elimina</th>
            </tr></thead>
            <tbody>
                {#each tipiRichiesta as t (t.id)}
                    <tr class:text-muted={!t.is_active}>
                        <td class="fw-semibold">{t.sigla}</td>
                        <td class="small">{t.descrizione}</td>
                        <td class="small">{t.tipo}</td>
                        <td class="small">{nomeBersaglio(t.flag_id)}</td>
                        <td class="small">{t.counting_flag ? 'sì' : 'no'}</td>
                        <td><DeleteButton ondelete={() => eliminaTipo(t.id)} /></td>
                    </tr>
                {/each}
            </tbody>
        </table>
    {:else}
        <p class="guidata-aiuto mb-0">Nessuna voce richiedibile.</p>
    {/if}
</section>

<section class="guidata-sezione guidata-inserimento">
    <h6 class="guidata-titolo">Aggiungi una voce richiedibile</h6>
    <div class="row g-3 align-items-end">
        <div class="col-auto" style="width:110px">
            <label class="form-label" for="tipo-sigla">Sigla</label>
            <input id="tipo-sigla" class="form-control form-control-sm"
                   placeholder="es. CO" bind:value={nuovoTipo.sigla} />
        </div>
        <div class="col-auto" style="width:230px">
            <label class="form-label" for="tipo-descrizione">Descrizione</label>
            <input id="tipo-descrizione" class="form-control form-control-sm"
                   placeholder="es. Ferie" bind:value={nuovoTipo.descrizione} />
        </div>
        <div class="col-auto" style="width:150px">
            <label class="form-label" for="tipo-tipo">Tipo</label>
            <select id="tipo-tipo" class="form-select form-select-sm" bind:value={nuovoTipo.tipo}>
                <option value="assenza">assenza</option>
                <option value="lavorativo">lavorativo</option>
            </select>
        </div>
        <div class="col-auto" style="width:180px">
            <label class="form-label" for="tipo-bersaglio">Si riferisce a</label>
            <select id="tipo-bersaglio" class="form-select form-select-sm"
                    bind:value={nuovoTipo.flag_id}>
                <option value={null}>— nessuna —</option>
                {#each bersagli as b}<option value={b.id}>{b.nome}</option>{/each}
            </select>
        </div>
        <div class="col-auto">
            <label class="form-check-label small">
                <input type="checkbox" checked={!!nuovoTipo.counting_flag}
                       on:change={e => nuovoTipo.counting_flag = e.target.checked ? 1 : 0} />
                Conta le ore
            </label>
        </div>
        <div class="col-auto">
            <button class="btn btn-primary btn-sm" disabled={!puoAggiungereTipo}
                    on:click={aggiungiTipo}>Aggiungi la voce</button>
        </div>
    </div>
</section>
