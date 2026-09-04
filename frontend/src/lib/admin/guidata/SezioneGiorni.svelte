<!--
  SezioneGiorni — quali giorni si lavora, quali sono festivi, e quanti turni
  ne discendono.

  È la base del conteggio: i **turni dovuti** di un mese sono i suoi giorni
  lavorativi, e da lì il sistema ricava il tetto mensile di ogni persona.
  Prima la regola era fissa — tutto tranne domenica e festività — e un
  reparto che chiude il sabato non aveva modo di dirlo.

  Convenzione dei giorni: 0 = lunedì, 6 = domenica.

  Le festivita' sono ricorrenze, non date: o cadono sempre nello stesso
  giorno dell'anno, o si contano dalla Pasqua, che si sposta. Stanno nel
  tenant perche' il santo patrono e' un dato dell'installazione: erano
  scritte nel codice, e il patrono di Roma risultava festivo dappertutto.

  Props:
    - config      : object — parametri di sistema del tenant
    - onaggiornata: () => Promise — ricarica la config nel chiamante
-->
<script>
    import { onMount } from 'svelte';
    import { adminApi } from '$lib/api.js';
    import DeleteButton from '../DeleteButton.svelte';

    export let config = {};
    export let onaggiornata;

    const MESI = [
        'gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
        'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre',
    ];

    // Le date si mostrano per l'anno in corso: una ricorrenza legata alla
    // Pasqua non ha una data sola, e va vista su un anno concreto.
    const ANNO = new Date().getFullYear();

    let festivita = [];
    let nuova = festivitaVuota();
    let erroreFestivita = '';

    function festivitaVuota() {
        return { nome: '', modo: 'fissa', giorno: 1, mese: 1, offset_pasqua: 0 };
    }

    onMount(caricaFestivita);

    async function caricaFestivita() {
        const r = await adminApi.getFestivita(ANNO);
        if (r.ok) festivita = r.festivita ?? [];
    }

    /** Come si legge una ricorrenza: «25 aprile» oppure «Pasqua +1». */
    function quando(f) {
        if (f.offset_pasqua !== null && f.offset_pasqua !== undefined) {
            if (f.offset_pasqua === 0) return 'Pasqua';
            const segno = f.offset_pasqua > 0 ? '+' : '−';
            return `Pasqua ${segno}${Math.abs(f.offset_pasqua)}`;
        }
        return `${f.giorno} ${MESI[(f.mese ?? 1) - 1]}`;
    }

    /** La data che assume quest'anno, per far vedere dove cade. */
    function dataLeggibile(f) {
        if (!f.data) return '—';
        const d = new Date(f.data + 'T00:00:00');
        return d.toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'short' });
    }

    $: nuovaCompleta = nuova.nome.trim().length > 0;

    async function aggiungiFestivita() {
        if (!nuovaCompleta) return;

        erroreFestivita = '';
        const corpo = nuova.modo === 'pasqua'
            ? { nome: nuova.nome.trim(), offset_pasqua: nuova.offset_pasqua }
            : { nome: nuova.nome.trim(), giorno: nuova.giorno, mese: nuova.mese };

        const r = await adminApi.creaFestivita(corpo);
        if (!r.ok) { erroreFestivita = r.errore || 'Aggiunta non riuscita.'; return; }

        nuova = festivitaVuota();
        await caricaFestivita();
    }

    /** Spegne o riaccende una ricorrenza, senza cancellarla. */
    async function commutaFestivita(f) {
        erroreFestivita = '';
        const r = await adminApi.editFestivita(f.id, { is_active: f.is_active ? 0 : 1 });
        if (!r.ok) { erroreFestivita = r.errore || 'Modifica non riuscita.'; return; }

        await caricaFestivita();
    }

    async function eliminaFestivita(id) {
        erroreFestivita = '';
        const r = await adminApi.delFestivita(id);
        if (!r.ok) { erroreFestivita = r.errore || 'Eliminazione non riuscita.'; return; }

        await caricaFestivita();
    }

    const GIORNI = [
        { numero: 0, nome: 'Lunedì' },   { numero: 1, nome: 'Martedì' },
        { numero: 2, nome: 'Mercoledì' }, { numero: 3, nome: 'Giovedì' },
        { numero: 4, nome: 'Venerdì' },  { numero: 5, nome: 'Sabato' },
        { numero: 6, nome: 'Domenica' },
    ];

    // Sei giorni su sette: quello che il sistema faceva prima.
    const DEFAULT = [0, 1, 2, 3, 4, 5];

    let errore = '';

    $: lavorativi = leggi(config['giorni_lavorativi_settimana']);

    function leggi(grezzo) {
        if (!grezzo) return [...DEFAULT];

        const numeri = String(grezzo).split(',')
            .map(p => parseInt(p.trim(), 10))
            .filter(n => Number.isInteger(n) && n >= 0 && n <= 6);

        return numeri.length ? numeri : [...DEFAULT];
    }

    async function salva(nuoviGiorni) {
        errore = '';
        const r = await adminApi.setConfig({
            giorni_lavorativi_settimana: nuoviGiorni.sort((a, b) => a - b).join(','),
        });
        if (!r.ok) { errore = r.errore || 'Salvataggio non riuscito.'; return; }

        await onaggiornata();
    }

    function commutaGiorno(numero) {
        const nuovi = lavorativi.includes(numero)
            ? lavorativi.filter(n => n !== numero)
            : [...lavorativi, numero];
        // Un mese senza giorni lavorativi darebbe zero turni dovuti a tutti.
        if (!nuovi.length) { errore = 'Almeno un giorno deve essere lavorativo.'; return; }

        salva(nuovi);
    }
</script>

<p class="guidata-intro">
    Da qui discende il conteggio dei <strong>turni dovuti</strong>: sono i
    giorni lavorativi del mese, e su quel numero il sistema calcola quanti
    turni spettano a ciascuno.
</p>

{#if errore}<div class="alert alert-danger py-2 small">{errore}</div>{/if}

<section class="guidata-sezione guidata-inserimento">
    <h6 class="guidata-titolo">In che giorni si lavora</h6>
    <div class="d-flex gap-3 flex-wrap">
        {#each GIORNI as g}
            <label class="form-check-label small d-flex align-items-center gap-1">
                <input type="checkbox" checked={lavorativi.includes(g.numero)}
                       on:change={() => commutaGiorno(g.numero)} />
                {g.nome}
            </label>
        {/each}
    </div>

</section>

<section class="guidata-sezione guidata-inserimento">
    <h6 class="guidata-titolo">Aggiungi una festività</h6>
    <p class="guidata-aiuto">
        Una festività o cade sempre nello stesso giorno dell'anno, o si conta
        dalla Pasqua, che si sposta. Il santo patrono è di qui: quello di
        un'altra città si toglie dall'elenco sotto.
    </p>

    {#if erroreFestivita}
        <div class="alert alert-danger py-2 small">{erroreFestivita}</div>
    {/if}

    <div class="row g-3 align-items-end">
        <div class="col-auto" style="width:220px">
            <label class="form-label" for="fest-nome">Nome</label>
            <input id="fest-nome" class="form-control form-control-sm"
                   placeholder="es. San Giovanni" bind:value={nuova.nome} />
        </div>
        <div class="col-auto" style="width:170px">
            <label class="form-label" for="fest-modo">Quando cade</label>
            <select id="fest-modo" class="form-select form-select-sm" bind:value={nuova.modo}>
                <option value="fissa">A una data fissa</option>
                <option value="pasqua">Contata dalla Pasqua</option>
            </select>
        </div>

        {#if nuova.modo === 'fissa'}
            <div class="col-auto" style="width:100px">
                <label class="form-label" for="fest-giorno">Giorno</label>
                <input id="fest-giorno" class="form-control form-control-sm" type="number"
                       min="1" max="31" bind:value={nuova.giorno} />
            </div>
            <div class="col-auto" style="width:150px">
                <label class="form-label" for="fest-mese">Mese</label>
                <select id="fest-mese" class="form-select form-select-sm" bind:value={nuova.mese}>
                    {#each MESI as nome, i}
                        <option value={i + 1}>{nome}</option>
                    {/each}
                </select>
            </div>
        {:else}
            <div class="col-auto" style="width:190px">
                <label class="form-label" for="fest-offset">Giorni dalla Pasqua</label>
                <input id="fest-offset" class="form-control form-control-sm" type="number"
                       bind:value={nuova.offset_pasqua} />
            </div>
        {/if}

        <div class="col-auto">
            <button class="btn btn-primary btn-sm" disabled={!nuovaCompleta}
                    on:click={aggiungiFestivita}>
                Aggiungi la festività
            </button>
        </div>
    </div>
</section>

<hr class="giorni-separatore" />

<section class="guidata-sezione">
    <h6 class="guidata-titolo">Le festività di questa organizzazione</h6>
    <p class="guidata-aiuto">
        Le domeniche non sono qui: quelle il calendario le sa già. Togliere la
        spunta spegne una ricorrenza senza cancellarla. Le date mostrate sono
        quelle del {ANNO}, e i calendari già creati non cambiano.
    </p>

    {#if festivita.length}
        <table class="table table-sm align-middle mb-0">
            <thead><tr>
                <th style="width:220px">Festività</th>
                <th style="width:150px">Quando</th>
                <th style="width:150px">Nel {ANNO}</th>
                <th style="width:80px">Attiva</th>
                <th style="width:80px">Elimina</th>
            </tr></thead>
            <tbody>
                {#each festivita as f (f.id)}
                    <tr class:text-muted={!f.is_active}>
                        <td class="fw-semibold">{f.nome}</td>
                        <td class="small">{quando(f)}</td>
                        <td class="small text-muted">{dataLeggibile(f)}</td>
                        <td class="text-center">
                            <input class="form-check-input" type="checkbox"
                                   aria-label="{f.nome} attiva"
                                   checked={!!f.is_active}
                                   on:change={() => commutaFestivita(f)} />
                        </td>
                        <td><DeleteButton ondelete={() => eliminaFestivita(f.id)} /></td>
                    </tr>
                {/each}
            </tbody>
        </table>
    {:else}
        <p class="guidata-aiuto mb-0">
            Nessuna festività: solo le domeniche non saranno lavorative.
        </p>
    {/if}
</section>

<section class="guidata-sezione">
    <h6 class="guidata-titolo">Come viene il conto</h6>
    <p class="guidata-aiuto mb-0">
        Il sistema guarda tutti i giorni del mese uno per uno: segna che
        giorno della settimana è, se è una festività o una domenica, e lo conta
        fra i dovuti solo se cade in un giorno in cui si lavora.
        <br /><br />
        Un mese di 30 giorni con quattro domeniche e nessuna festività, lavorando
        dal lunedì al sabato, fa <strong>26 turni dovuti</strong>. Chiudendo
        anche il sabato ne fa 22.
        <br /><br />
        <strong>Festivi e superfestivi non sono mai dovuti.</strong> Lavorare un
        festivo è sempre un turno in più, che matura un recupero: il sistema
        conta quello che è stato svolto sommando i <em>pesi</em> dei turni
        assegnati, dove una lunga o una notte valgono due.
        <br /><br />
        I dovuti sono il tetto di ciascuno. Nella sezione <em>Vincoli</em> si
        può scostarlo in più o in meno, per tutti o per una persona sola.
    </p>
</section>

<style>
    /* Sotto questa riga si guardano le festivita' che ci sono gia'. */
    .giorni-separatore {
        margin: 0 0 1rem;
        border-top: 1px dashed var(--bs-border-color);
        opacity: 1;
    }
</style>
