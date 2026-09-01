<!--
  ProponiConfigurazione — prendi il vocabolario da un tenant, proponilo a un altro.

  Il master non impone: deposita la proposta e l'amministratore del tenant di
  destinazione decide. Si propongono le parti trasferibili fra reparti —
  fasce orarie e assenze, tipologie turno, tipi richiesta, regole di conflitto
  — non la struttura turni né le persone, che sono di quel posto.

  Props:
    - tenants  : Array — i tenant fra cui scegliere
    - onchiudi : () => void
-->
<script>
    import { masterApi } from '$lib/api.js';

    export let tenants = [];
    export let onchiudi;

    let origineId = null;
    let destinazioneId = null;
    let nome = '';
    let note = '';
    let anteprima = null;
    let inCorso = false;
    let messaggio = '';
    let errore = '';

    $: attivi = tenants.filter(t => t.is_active);
    $: puoInviare = origineId && destinazioneId
        && origineId !== destinazioneId && nome.trim();

    function nomeTenant(id) {
        return attivi.find(t => t.id === id)?.nome ?? '';
    }

    /** Legge dal tenant di origine cosa si porterebbe via. */
    async function leggiOrigine() {
        anteprima = null;
        errore = '';
        if (!origineId) return;

        const r = await masterApi.getConfigurazioneTenant(origineId);
        if (!r.ok) { errore = r.errore || 'Lettura non riuscita.'; return; }

        anteprima = r.configurazione;
        if (!nome.trim()) nome = `Vocabolario di ${nomeTenant(origineId)}`;
    }

    async function invia() {
        if (!puoInviare || inCorso) return;

        inCorso = true;
        errore = '';
        messaggio = '';

        const r = await masterApi.proponiConfigurazione(destinazioneId, {
            nome: nome.trim(),
            configurazione: anteprima,
            note: note.trim(),
        });

        inCorso = false;
        if (!r.ok) { errore = r.errore || 'Invio non riuscito.'; return; }

        messaggio = `Proposta inviata a ${nomeTenant(destinazioneId)}. `
            + 'Sarà il suo amministratore a decidere.';
        note = '';
    }
</script>

<div class="card mb-4">
    <div class="card-header d-flex justify-content-between align-items-center">
        <span class="fw-semibold">
            <i class="bi bi-send me-2"></i>Proponi una configurazione
        </span>
        <button class="btn btn-sm btn-outline-secondary" on:click={onchiudi}>Chiudi</button>
    </div>
    <div class="card-body">
        <p class="text-muted small">
            Prendi il vocabolario di un reparto ben configurato e proponilo a un
            altro. Non viene applicato: l'amministratore del tenant lo confronta
            con il suo e decide. Struttura turni e persone non viaggiano.
        </p>

        {#if errore}<div class="alert alert-danger py-2 small">{errore}</div>{/if}
        {#if messaggio}<div class="alert alert-success py-2 small">{messaggio}</div>{/if}

        <div class="row g-3 align-items-end">
            <div class="col-auto" style="width:230px">
                <label class="form-label small fw-semibold" for="proponi-origine">Da</label>
                <select id="proponi-origine" class="form-select form-select-sm"
                        bind:value={origineId} on:change={leggiOrigine}>
                    <option value={null}>— scegli il reparto modello —</option>
                    {#each attivi as t}<option value={t.id}>{t.nome}</option>{/each}
                </select>
            </div>
            <div class="col-auto" style="width:230px">
                <label class="form-label small fw-semibold" for="proponi-destinazione">A</label>
                <select id="proponi-destinazione" class="form-select form-select-sm"
                        bind:value={destinazioneId}>
                    <option value={null}>— scegli il destinatario —</option>
                    {#each attivi as t}
                        {#if t.id !== origineId}<option value={t.id}>{t.nome}</option>{/if}
                    {/each}
                </select>
            </div>
            <div class="col-auto" style="width:230px">
                <label class="form-label small fw-semibold" for="proponi-nome">Come si chiama</label>
                <input id="proponi-nome" class="form-control form-control-sm" bind:value={nome} />
            </div>
            <div class="col-auto" style="width:280px">
                <label class="form-label small fw-semibold" for="proponi-note">Perché la proponi</label>
                <input id="proponi-note" class="form-control form-control-sm"
                       placeholder="facoltativo" bind:value={note} />
            </div>
            <div class="col-auto">
                <button class="btn btn-primary btn-sm" disabled={!puoInviare || inCorso}
                        on:click={invia}>
                    {inCorso ? 'Invio…' : 'Invia la proposta'}
                </button>
            </div>
        </div>

        {#if anteprima}
            <div class="text-muted small mt-3">
                Si porta con sé:
                {anteprima.flag_turno.length} fra fasce e assenze,
                {anteprima.tipi_qualitativo.length} tipologie,
                {anteprima.tipi_richiesta.length} tipi richiesta,
                {anteprima.regole_conflitto.length} regole.
            </div>
        {/if}
    </div>
</div>
