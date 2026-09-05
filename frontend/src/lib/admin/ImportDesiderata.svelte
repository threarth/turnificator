<!--
  ImportDesiderata — le richieste di un mese, prese da un foglio Excel.

  Nuova feature. I lavoratori compilano i desiderata in un foglio di calcolo:
  ridigitarli nella griglia e' un lavoro lungo su dati che esistono gia'.

  Due tempi, perche' l'import **sostituisce il mese intero**: prima si legge
  e si racconta — di che mese parla, quante richieste porta, quante ne
  cancellerebbe, e se le persone sono le stesse — poi si decide. Con
  discrepanze fra le persone del foglio e quelle del programma serve una
  conferma esplicita: quello che non si riconosce resta fuori.

  Props:
    - onimportati: () => Promise — i desiderata del mese sono cambiati
-->
<script>
    import { adminApi } from '$lib/api.js';

    export let onimportati = async () => {};

    const NOMI_MESI = ['', 'gennaio', 'febbraio', 'marzo', 'aprile', 'maggio',
        'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'];

    let file = null;
    let esame = null;
    let esito = null;
    let errore = '';
    let inCorso = false;

    function scegliFile(e) {
        file = e.target.files?.[0] ?? null;
        esame = null;
        esito = null;
        errore = '';
    }

    async function analizza() {
        if (!file || inCorso) return;

        inCorso = true;
        errore = '';
        const r = await adminApi.analizzaDesiderata(file);
        inCorso = false;

        if (!r.ok) { errore = r.errore || 'Il foglio non si legge.'; return; }
        esame = r;
    }

    async function importa() {
        if (!file || inCorso) return;

        inCorso = true;
        errore = '';
        const r = await adminApi.importaDesiderata(file, esame?.discrepanze);
        inCorso = false;

        if (!r.ok) { errore = r.errore || 'Import non riuscito.'; return; }

        esito = r;
        esame = null;
        await onimportati();
    }

    function mese(m, a) {
        return `${NOMI_MESI[m] ?? m} ${a}`;
    }
</script>

<div class="card mb-3">
    <div class="card-header fw-semibold">
        <i class="bi bi-file-earmark-spreadsheet me-1"></i>Importa i desiderata da un foglio
    </div>
    <div class="card-body">
        {#if errore}<div class="alert alert-danger py-2 small">{errore}</div>{/if}

        {#if esito}
            <div class="alert alert-success py-2 small mb-2">
                {esito.importate} richieste importate in {mese(esito.mese, esito.anno)}.
                {#if esito.sostituite}
                    Ne ha sostituite {esito.sostituite} che c'erano prima.
                {/if}
                {#if esito.saltate}
                    <br />{esito.saltate} richieste saltate: erano di persone o con
                    sigle che il programma non riconosce.
                {/if}
                {#if esito.copia_di_lavoro_rifatta}
                    <br />I desiderata erano congelati: la copia di lavoro è stata
                    rifatta sulle richieste appena importate.
                {/if}
            </div>
        {/if}

        <div class="d-flex gap-3 align-items-end flex-wrap">
            <div style="width:320px">
                <label class="form-label small mb-1" for="des-file">Foglio Excel (.xlsx)</label>
                <input id="des-file" class="form-control form-control-sm"
                       type="file" accept=".xlsx" on:change={scegliFile} />
            </div>
            <button class="btn btn-primary btn-sm" disabled={!file || inCorso}
                    on:click={analizza}>
                {#if inCorso}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
                Leggi il foglio
            </button>
        </div>

        {#if esame}
            <hr />
            <div class="d-flex gap-4 flex-wrap small mb-2">
                <span><strong>Mese:</strong> {mese(esame.mese, esame.anno)}</span>
                <span><strong>Richieste:</strong> {esame.richieste_importabili}
                    {#if esame.richieste_importabili !== esame.richieste_nel_foglio}
                        <span class="text-muted">su {esame.richieste_nel_foglio}</span>
                    {/if}
                </span>
                <span><strong>Persone:</strong> {esame.persone_nel_foglio}</span>
            </div>

            {#if !esame.calendario}
                <div class="alert alert-warning py-2 small mb-2">
                    Non c'è un calendario per {mese(esame.mese, esame.anno)}:
                    crealo qui sopra, poi torna a importare.
                </div>
            {:else}
                {#if esame.desiderata_da_sostituire}
                    <div class="alert alert-warning py-2 small mb-2">
                        Quel mese ha già {esame.desiderata_da_sostituire} richieste:
                        l'import <strong>le sostituisce tutte</strong>.
                        {#if esame.calendario.desiderata_congelati}
                            <br />I desiderata sono congelati: anche la copia di lavoro
                            verrà rifatta, e le modifiche fatte su quella andranno perse.
                        {/if}
                    </div>
                {/if}

                {#if esame.discrepanze}
                    <div class="alert alert-danger py-2 small mb-2">
                        <div class="fw-semibold mb-1">
                            Il foglio e il programma non parlano delle stesse persone.
                        </div>
                        {#if esame.persone_sconosciute.length}
                            <div>Nel foglio ma non nel programma —
                                le loro richieste restano fuori:
                                <strong>{esame.persone_sconosciute.join(', ')}</strong></div>
                        {/if}
                        {#if esame.persone_senza_riga.length}
                            <div>Nel programma ma senza riga nel foglio —
                                resteranno senza richieste:
                                <strong>{esame.persone_senza_riga.join(', ')}</strong></div>
                        {/if}
                        {#if esame.codici_sconosciuti.length}
                            <div>Sigle di richiesta che non riconosco:
                                <strong>{esame.codici_sconosciuti.join(', ')}</strong></div>
                        {/if}
                    </div>
                {/if}

                {#each esame.avvisi ?? [] as a}
                    <div class="alert alert-warning py-2 small mb-2">{a}</div>
                {/each}

                <button class="btn btn-sm {esame.discrepanze ? 'btn-danger' : 'btn-success'}"
                        disabled={inCorso} on:click={importa}>
                    {#if inCorso}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
                    {esame.discrepanze
                        ? 'Importa comunque, sostituendo il mese'
                        : 'Importa, sostituendo il mese'}
                </button>
            {/if}
        {/if}
    </div>
</div>
