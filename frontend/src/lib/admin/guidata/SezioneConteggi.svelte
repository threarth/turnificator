<!--
  SezioneConteggi — i conteggi che il manager vede accanto a ogni lavoratore.

  Un conteggio risponde a una domanda ricorrente — "quante notti ha fatto",
  "quanti turni di sabato" — e compare come colonna nel menu di assegnazione.
  Guarda una fascia oraria, con la sua discendenza, oppure una tipologia.

  Scrive subito in `config`, come le altre sezioni globali.

  Props:
    - conteggi    : Array — conteggi configurati
    - fasce       : Array — fasce e concetti selezionabili
    - tipologie   : Array — tipologie turno
    - onaggiornati: (conteggi) => Promise — salva e ricarica nel chiamante
-->
<script>
    import DeleteButton from '../DeleteButton.svelte';

    export let conteggi = [];
    export let fasce = [];
    export let tipologie = [];
    export let onaggiornati;

    // Giorni della settimana come li numera il calendario: 0 = domenica.
    const GIORNI = [
        { valore: null, nome: 'Tutti i giorni' },
        { valore: 1, nome: 'Lunedì' },    { valore: 2, nome: 'Martedì' },
        { valore: 3, nome: 'Mercoledì' }, { valore: 4, nome: 'Giovedì' },
        { valore: 5, nome: 'Venerdì' },   { valore: 6, nome: 'Sabato' },
        { valore: 0, nome: 'Domenica' },
    ];

    let nuovo = conteggioVuoto();
    let errore = '';

    function conteggioVuoto() {
        return { id: '', label: '', tipo: 'fascia', flag_nome: '', ref_id: null,
                 giorno_settimana: null, negato: false, attivo: true };
    }

    /** Un conteggio senza riferimento conterebbe sempre zero. */
    $: haRiferimento = nuovo.tipo === 'tipologia'
        ? nuovo.ref_id != null
        : !!nuovo.flag_nome;
    $: puoAggiungere = nuovo.label.trim() && haRiferimento;

    /** Che cosa guarda un conteggio, in parole. */
    function descrizione(c) {
        if (c.tipo === 'tipologia') {
            return tipologie.find(t => t.id === c.ref_id)?.nome ?? '—';
        }
        return c.flag_nome || '—';
    }

    function nomeGiorno(valore) {
        return GIORNI.find(g => g.valore === valore)?.nome ?? 'Tutti i giorni';
    }

    async function aggiungi() {
        if (!puoAggiungere) return;

        errore = '';
        // L'id serve al manager per nascondere e riordinare la colonna.
        const id = nuovo.id.trim() || nuovo.label.trim().toLowerCase().replace(/\W+/g, '_');
        if (conteggi.some(c => c.id === id)) {
            errore = `Esiste già un conteggio chiamato "${id}".`;
            return;
        }

        await onaggiornati([...conteggi, { ...nuovo, id }]);
        nuovo = conteggioVuoto();
    }

    async function elimina(id) {
        await onaggiornati(conteggi.filter(c => c.id !== id));
    }
</script>

<p class="guidata-intro">
    Un conteggio compare come colonna accanto al lavoratore quando assegni un
    turno, e risponde a una domanda che ti fai spesso: quante notti ha fatto,
    quanti turni di sabato, quante TC.
</p>

{#if errore}<div class="alert alert-danger py-2 small">{errore}</div>{/if}

<section class="guidata-sezione">
    <h6 class="guidata-titolo">I conteggi attivi</h6>

    {#if conteggi.length}
        <table class="table table-sm align-middle mb-0">
            <thead><tr>
                <th style="width:170px">Etichetta</th>
                <th style="width:110px">Guarda</th>
                <th style="width:150px">Quale</th>
                <th style="width:140px">Quando</th>
                <th style="width:80px" title="Conta i turni che NON corrispondono">Negato</th>
                <th style="width:80px">Elimina</th>
            </tr></thead>
            <tbody>
                {#each conteggi as c (c.id)}
                    <tr class:text-muted={!c.attivo}>
                        <td class="fw-semibold">{c.label}</td>
                        <td class="small">{c.tipo === 'tipologia' ? 'tipologia' : 'fascia oraria'}</td>
                        <td class="small">{descrizione(c)}</td>
                        <td class="small">{nomeGiorno(c.giorno_settimana)}</td>
                        <td class="small">{c.negato ? 'sì' : 'no'}</td>
                        <td><DeleteButton ondelete={() => elimina(c.id)} /></td>
                    </tr>
                {/each}
            </tbody>
        </table>
    {:else}
        <p class="guidata-aiuto mb-0">
            Nessun conteggio. Il più utile di solito è "quante notti al mese".
        </p>
    {/if}
</section>

<section class="guidata-sezione guidata-inserimento">
    <h6 class="guidata-titolo">Aggiungi un conteggio</h6>
    <div class="row g-3 align-items-end">
        <div class="col-auto" style="width:180px">
            <label class="form-label" for="conteggio-label">Etichetta</label>
            <input id="conteggio-label" class="form-control form-control-sm"
                   placeholder="es. Notti" bind:value={nuovo.label} />
        </div>
        <div class="col-auto" style="width:150px">
            <label class="form-label" for="conteggio-tipo">Guarda</label>
            <select id="conteggio-tipo" class="form-select form-select-sm" bind:value={nuovo.tipo}>
                <option value="fascia">fascia oraria</option>
                <option value="tipologia">tipologia</option>
            </select>
        </div>
        <div class="col-auto" style="width:190px">
            <label class="form-label" for="conteggio-quale">Quale</label>
            {#if nuovo.tipo === 'tipologia'}
                <select id="conteggio-quale" class="form-select form-select-sm" bind:value={nuovo.ref_id}>
                    <option value={null}>— scegli —</option>
                    {#each tipologie as t}<option value={t.id}>{t.nome}</option>{/each}
                </select>
            {:else}
                <select id="conteggio-quale" class="form-select form-select-sm" bind:value={nuovo.flag_nome}>
                    <option value="">— scegli —</option>
                    {#each fasce as f}
                        <option value={f.nome}>{f.parent_nome ? f.parent_nome + '→' : ''}{f.nome}</option>
                    {/each}
                </select>
            {/if}
        </div>
        <div class="col-auto" style="width:170px">
            <label class="form-label" for="conteggio-giorno">Quando</label>
            <select id="conteggio-giorno" class="form-select form-select-sm"
                    bind:value={nuovo.giorno_settimana}>
                {#each GIORNI as g}<option value={g.valore}>{g.nome}</option>{/each}
            </select>
        </div>
        <div class="col-auto">
            <label class="form-check-label small">
                <input type="checkbox" bind:checked={nuovo.negato} /> Conta il contrario
            </label>
        </div>
        <div class="col-auto">
            <button class="btn btn-primary btn-sm" disabled={!puoAggiungere} on:click={aggiungi}>
                Aggiungi il conteggio
            </button>
        </div>
    </div>
    <p class="guidata-aiuto mt-2 mb-0">
        "Conta il contrario" serve a domande come "quanti turni di sabato che
        non siano notti": scegli la notte e spunta la casella.
    </p>
</section>
