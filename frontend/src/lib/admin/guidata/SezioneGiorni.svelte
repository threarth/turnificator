<!--
  SezioneGiorni — quali giorni si lavora, e quanti turni ne discendono.

  È la base del conteggio: i **turni dovuti** di un mese sono i suoi giorni
  lavorativi, e da lì il sistema ricava il tetto mensile di ogni persona.
  Prima la regola era fissa — tutto tranne domenica e festività — e un
  reparto che chiude il sabato non aveva modo di dirlo.

  Convenzione dei giorni: 0 = lunedì, 6 = domenica.

  Props:
    - config      : object — parametri di sistema del tenant
    - onaggiornata: () => Promise — ricarica la config nel chiamante
-->
<script>
    import { adminApi } from '$lib/api.js';

    export let config = {};
    export let onaggiornata;

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
