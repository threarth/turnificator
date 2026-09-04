<!--
  SezioneModello — la struttura turni presa da un foglio Excel.

  Nuova feature. Chi arriva da un foglio di calcolo ha gia' tutto scritto li':
  i turni, come sono raggruppati, chi ci lavora. Ridigitarlo nelle sezioni
  successive e' un lavoro lungo e un'occasione di sbagliare.

  Due tempi. Prima il foglio si legge e si racconta — quante strutture, quanti
  turni, quante persone, e cosa non e' stato capito — senza scrivere niente.
  Poi, se il quadro torna, si crea.

  Il foglio resta nel tenant: diventa il modello in cui riesportare i mesi
  programmati, e la struttura appena creata gli combacia riga per riga.

  Props:
    - onstrutturacreata: (presetId) => void — struttura creata dal foglio
    - onaggiornati     : () => Promise — ricarica utenti e tipologie
-->
<script>
    import { adminApi } from '$lib/api.js';

    export let onstrutturacreata = () => {};
    export let onaggiornati = async () => {};

    const TESTI = {
        intro: "Se i turni li tieni già in un foglio Excel, il programma può "
             + "leggerli da lì: strutture, turni, tipologie e persone, "
             + "nell'ordine in cui il foglio li dispone.",
        scegli: 'Il foglio',
        analizza: 'Leggi il foglio',
        nomePreset: 'Nome della struttura turni',
        crea: 'Crea la struttura',
        rileggi: 'Cambia foglio',
    };

    let file = null;
    let letto = null;
    let esito = null;
    let nomePreset = '';
    let errore = '';
    let inCorso = false;

    function scegliFile(e) {
        file = e.target.files?.[0] ?? null;
        letto = null;
        esito = null;
        errore = '';
        if (file && !nomePreset) nomePreset = file.name.replace(/\.xlsx?$/i, '');
    }

    async function analizza() {
        if (!file || inCorso) return;

        inCorso = true;
        errore = '';
        const r = await adminApi.analizzaModello(file);
        inCorso = false;

        if (!r.ok) { errore = r.errore || 'Il foglio non si legge.'; return; }
        letto = r;
    }

    async function crea() {
        if (!file || !nomePreset.trim() || inCorso) return;

        inCorso = true;
        errore = '';
        const r = await adminApi.applicaModello(file, nomePreset.trim());
        inCorso = false;

        if (!r.ok) { errore = r.errore || 'Creazione non riuscita.'; return; }

        esito = r;
        letto = null;
        await onaggiornati();
        onstrutturacreata(r.preset_id);
    }

    /** Quanti turni per fascia, per il riepilogo di cio' che si e' letto. */
    function perFascia(turni) {
        const conta = {};
        for (const t of turni) conta[t.fascia] = (conta[t.fascia] ?? 0) + 1;

        return Object.entries(conta).map(([f, n]) => `${n} di ${f}`).join(', ');
    }
</script>

<p class="guidata-intro">{TESTI.intro}</p>

{#if errore}<div class="alert alert-danger py-2 small">{errore}</div>{/if}

{#if esito}
    <section class="guidata-sezione">
        <h6 class="guidata-titolo">Struttura creata</h6>
        <p class="guidata-aiuto">
            {esito.strutture} strutture, {esito.turni} turni e
            {esito.tipologie} tipologie. Il foglio è stato conservato: sarà il
            modello in cui riesportare i mesi programmati.
            <br />
            Le sezioni <strong>{'Strutture'}</strong> e <strong>I turni</strong>
            di questa procedura puoi saltarle: quello che avresti costruito lì
            c'è già.
        </p>

        {#if esito.avvisi?.length}
            <div class="alert alert-warning py-2 small mb-3">
                {#each esito.avvisi as a}<div>{a}</div>{/each}
            </div>
        {/if}

        {#if esito.persone_create?.length}
            <h6 class="guidata-titolo">Password provvisorie da consegnare</h6>
            <p class="guidata-aiuto">
                Compaiono una volta sola. Copiale adesso: ciascuno la cambierà
                al primo accesso.
            </p>
            <table class="table table-sm align-middle mb-0">
                <thead><tr>
                    <th style="width:100px">Sigla</th>
                    <th style="width:160px">Nome utente</th>
                    <th style="width:200px">Password</th>
                </tr></thead>
                <tbody>
                    {#each esito.persone_create as c (c.sigla)}
                        <tr>
                            <td class="fw-semibold">{c.sigla}</td>
                            <td class="small">{c.username}</td>
                            <td><code>{c.password}</code></td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        {/if}
    </section>
{:else}
    <section class="guidata-sezione guidata-inserimento">
        <h6 class="guidata-titolo">{TESTI.scegli}</h6>
        <div class="d-flex gap-3 align-items-end flex-wrap">
            <div style="width:340px">
                <label class="form-label" for="modello-file">Foglio Excel (.xlsx)</label>
                <input id="modello-file" class="form-control form-control-sm"
                       type="file" accept=".xlsx" on:change={scegliFile} />
            </div>
            <button class="btn btn-primary btn-sm" disabled={!file || inCorso}
                    on:click={analizza}>
                {#if inCorso}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
                {TESTI.analizza}
            </button>
        </div>
        <p class="guidata-aiuto mt-2 mb-0">
            Leggere il foglio non cambia niente: serve a farti vedere cosa il
            programma ci ha trovato, prima di decidere.
        </p>
    </section>
{/if}

{#if letto}
    <section class="guidata-sezione">
        <h6 class="guidata-titolo">Cosa c'è nel foglio</h6>

        <div class="row g-3 mb-3">
            <div class="col-auto"><div class="modello-cifra">
                <span class="modello-numero">{letto.strutture.length}</span> strutture
            </div></div>
            <div class="col-auto"><div class="modello-cifra">
                <span class="modello-numero">{letto.turni.length}</span> turni
                <span class="text-muted small">({perFascia(letto.turni)})</span>
            </div></div>
            <div class="col-auto"><div class="modello-cifra">
                <span class="modello-numero">{letto.persone.length}</span> persone
            </div></div>
            <div class="col-auto"><div class="modello-cifra">
                <span class="modello-numero">{letto.tipologie.length}</span> tipologie
            </div></div>
        </div>

        <p class="guidata-aiuto">
            <strong>Strutture:</strong> {letto.strutture.map(s => s.nome).join(' · ')}
        </p>

        {#if letto.persone_gia_presenti?.length}
            <p class="guidata-aiuto">
                Queste persone ci sono già e non verranno toccate:
                {letto.persone_gia_presenti.join(', ')}.
            </p>
        {/if}

        {#if letto.avvisi?.length}
            <div class="alert alert-warning py-2 small">
                {#each letto.avvisi as a}<div>{a}</div>{/each}
            </div>
        {/if}

        <div class="d-flex gap-3 align-items-end flex-wrap">
            <div style="width:280px">
                <label class="form-label" for="modello-nome">{TESTI.nomePreset}</label>
                <input id="modello-nome" class="form-control form-control-sm"
                       bind:value={nomePreset} />
            </div>
            <button class="btn btn-success btn-sm"
                    disabled={!nomePreset.trim() || inCorso} on:click={crea}>
                {#if inCorso}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
                {TESTI.crea}
            </button>
        </div>
    </section>
{/if}

<style>
    .modello-cifra {
        border: 1px solid var(--bs-border-color);
        border-radius: .5rem;
        padding: .4rem .8rem;
        font-size: .8rem;
        color: var(--bs-secondary-color);
    }

    .modello-numero {
        font-size: 1.3rem;
        font-weight: 700;
        color: var(--bs-body-color);
        margin-right: .2rem;
    }
</style>
