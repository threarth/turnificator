<!--
  RiepilogoCalendario — i conteggi del mese, sotto la griglia.

  Nuova feature. Cinque blocchi, gli stessi del foglio da cui nasce: turni
  feriali e festivi, solo weekend, globale, per struttura, per settimana.
  Nei primi tre i lavoratori stanno in colonna e le voci in riga, come nel
  foglio; negli ultimi due in riga, perche' le colonne sono le strutture e le
  settimane.

  I conteggi arrivano da lib/riepilogo.js, che lavora sui dati gia' in pagina:
  il riepilogo si aggiorna mentre si costruisce il turno.

  Props:
    - sovragruppi   : Array — gerarchia del calendario
    - giorni        : Array — [{giorno, is_lavorativo, tipo}]
    - assegnazioni  : object — `${turno_id}-${giorno}` → {user_id}
    - utenti        : Array — [{id, sigla}], nell'ordine della griglia
    - desiderata    : Array — working desiderata
    - tipiRichiesta : Array — tipi richiesta dello snapshot
    - fasce         : Array — flag_turno dello snapshot, con gli orari
    - mappaFlag     : Map — gerarchia dei flag
    - dow           : (giorno) => number — giorno della settimana, 0=Dom
    - etichetta     : {plurale} — come l'utente chiama le strutture
-->
<script>
    import { calcolaRiepilogo } from '$lib/riepilogo.js';
    import { decToHm } from '$lib/admin/durate.js';

    let {
        sovragruppi = [], giorni = [], assegnazioni = {}, utenti = [],
        desiderata = [], tipiRichiesta = [], fasce = [], mappaFlag = new Map(),
        dow, etichetta = { plurale: 'Strutture' },
    } = $props();

    // Le voci dei primi tre blocchi: etichetta e campo della riga calcolata.
    const VOCI_TURNI = [
        { campo: 'nottiFeriali',  etichetta: 'Notti feriali' },
        { campo: 'nottiFestive',  etichetta: 'Notti festive' },
        { campo: 'giorniFeriali', etichetta: 'Giorni feriali' },
        { campo: 'giorniFestivi', etichetta: 'Giorni festivi' },
    ];

    const VOCI_WEEKEND = [
        { campo: 'diurniWeekend', etichetta: 'Diurni sab o dom' },
        { campo: 'nottiSabato',   etichetta: 'Notti sab' },
        { campo: 'nottiDomenica', etichetta: 'Notti dom' },
    ];

    const VOCI_GLOBALE = [
        { campo: 'lavorati',     etichetta: 'Lavorati' },
        { campo: 'giustificate', etichetta: 'Assenze giustif.' },
        { campo: 'totale',       etichetta: 'Totale' },
    ];

    const TESTI = {
        titolo: 'Riepilogo del mese',
        mostra: 'Mostra',
        nascondi: 'Nascondi',
        pesi: 'Si contano i pesi: una notte o una lunga valgono due turni.',
        turni: 'Turni feriali e festivi',
        weekend: 'Solo turni di weekend',
        ore: 'Ore',
        globale: 'Turni lavorati e giustificati',
        dovuti: 'Turni da svolgere',
        perSettimana: 'Per settimana',
        settimaneDovuti: 'Dovuti',
        totaleColonna: 'Tot',
        vuoto: 'Nessun lavoratore da riepilogare.',
    };

    let aperto = $state(true);

    let dati = $derived(calcolaRiepilogo({
        sovragruppi, giorni, assegnazioni, utenti, desiderata,
        tipiRichiesta, fasce, mappaFlag, dow,
    }));

    /** Uno zero si legge meglio come un trattino: si nota chi ha qualcosa. */
    function n(valore) {
        return valore ? valore : '—';
    }

    /** Il totale a confronto con i turni dovuti: sotto, pari o sopra. */
    function scostamento(totale) {
        if (!dati.turniDovuti || totale === dati.turniDovuti) return '';
        return totale < dati.turniDovuti ? 'sotto' : 'sopra';
    }

    /** Somma dei turni di un lavoratore su tutte le strutture. */
    function totaleStrutture(riga) {
        return Object.values(riga.perStruttura).reduce((s, v) => s + v, 0);
    }
</script>

<section class="riepilogo">
    <header class="riepilogo-testa">
        <h5 class="riepilogo-titolo">{TESTI.titolo}</h5>
        <span class="riepilogo-nota">{TESTI.pesi}</span>
        <button class="btn btn-sm btn-outline-secondary ms-auto"
                onclick={() => aperto = !aperto}>
            {aperto ? TESTI.nascondi : TESTI.mostra}
        </button>
    </header>

    {#if aperto}
        {#if !dati.righe.length}
            <p class="riepilogo-vuoto">{TESTI.vuoto}</p>
        {:else}
            <!-- ═══ Turni feriali e festivi ═══ -->
            <div class="riepilogo-blocco">
                <h6 class="riepilogo-sottotitolo">{TESTI.turni}</h6>
                <div class="riepilogo-scroll">
                    <table class="riepilogo-tabella">
                        <thead><tr>
                            <th class="voce"></th>
                            {#each dati.righe as r (r.user_id)}<th>{r.sigla}</th>{/each}
                        </tr></thead>
                        <tbody>
                            {#each VOCI_TURNI as v (v.campo)}
                                <tr>
                                    <th class="voce">{v.etichetta}</th>
                                    {#each dati.righe as r (r.user_id)}<td>{n(r[v.campo])}</td>{/each}
                                </tr>
                            {/each}
                            <!-- Le fasce che valgono due turni, ciascuna col suo nome:
                                 «12h» sarebbe un'etichetta che nessuno ha scelto. -->
                            {#each dati.fasceLunghe as nome (nome)}
                                <tr>
                                    <th class="voce">{nome}</th>
                                    {#each dati.righe as r (r.user_id)}<td>{n(r.lunghe[nome])}</td>{/each}
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- ═══ Solo weekend ═══ -->
            <div class="riepilogo-blocco">
                <h6 class="riepilogo-sottotitolo">{TESTI.weekend}</h6>
                <div class="riepilogo-scroll">
                    <table class="riepilogo-tabella">
                        <thead><tr>
                            <th class="voce"></th>
                            {#each dati.righe as r (r.user_id)}<th>{r.sigla}</th>{/each}
                        </tr></thead>
                        <tbody>
                            {#each VOCI_WEEKEND as v (v.campo)}
                                <tr>
                                    <th class="voce">{v.etichetta}</th>
                                    {#each dati.righe as r (r.user_id)}<td>{n(r[v.campo])}</td>{/each}
                                </tr>
                            {/each}
                            <tr>
                                <th class="voce">{TESTI.ore}</th>
                                {#each dati.righe as r (r.user_id)}
                                    <td>{r.oreWeekend ? decToHm(r.oreWeekend) : '—'}</td>
                                {/each}
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- ═══ Globale ═══ -->
            <div class="riepilogo-blocco">
                <h6 class="riepilogo-sottotitolo">
                    {TESTI.globale}
                    <span class="riepilogo-dovuti">{TESTI.dovuti}: {dati.turniDovuti}</span>
                </h6>
                <div class="riepilogo-scroll">
                    <table class="riepilogo-tabella">
                        <thead><tr>
                            <th class="voce"></th>
                            {#each dati.righe as r (r.user_id)}<th>{r.sigla}</th>{/each}
                        </tr></thead>
                        <tbody>
                            {#each VOCI_GLOBALE as v (v.campo)}
                                <tr class:totale={v.campo === 'totale'}>
                                    <th class="voce">{v.etichetta}</th>
                                    {#each dati.righe as r (r.user_id)}
                                        <td class={v.campo === 'totale' ? scostamento(r.totale) : ''}>
                                            {n(r[v.campo])}
                                        </td>
                                    {/each}
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- ═══ Per struttura ═══ -->
            <div class="riepilogo-blocco">
                <h6 class="riepilogo-sottotitolo">{etichetta.plurale}</h6>
                <div class="riepilogo-scroll">
                    <table class="riepilogo-tabella">
                        <thead><tr>
                            <th class="voce"></th>
                            {#each dati.strutture as s (s.id)}<th title={s.nome}>{s.sigla}</th>{/each}
                            <th class="totale">{TESTI.totaleColonna}</th>
                        </tr></thead>
                        <tbody>
                            {#each dati.righe as r (r.user_id)}
                                <tr>
                                    <th class="voce">{r.sigla}</th>
                                    {#each dati.strutture as s (s.id)}
                                        <td>{n(r.perStruttura[s.id])}</td>
                                    {/each}
                                    <td class="totale">{n(totaleStrutture(r))}</td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- ═══ Per settimana ═══ -->
            <div class="riepilogo-blocco">
                <h6 class="riepilogo-sottotitolo">{TESTI.perSettimana}</h6>
                <div class="riepilogo-scroll">
                    <table class="riepilogo-tabella">
                        <thead>
                            <tr>
                                <th class="voce"></th>
                                {#each dati.settimane as s (s.dal)}<th>{s.etichetta}</th>{/each}
                                <th class="totale">{TESTI.totaleColonna}</th>
                            </tr>
                            <tr class="dovuti">
                                <th class="voce">{TESTI.settimaneDovuti}</th>
                                {#each dati.settimane as s (s.dal)}<td>{s.dovuti}</td>{/each}
                                <td class="totale">{dati.turniDovuti}</td>
                            </tr>
                        </thead>
                        <tbody>
                            {#each dati.righe as r (r.user_id)}
                                <tr>
                                    <th class="voce">{r.sigla}</th>
                                    {#each r.perSettimana as quanti, i (i)}<td>{n(quanti)}</td>{/each}
                                    <td class="totale">{n(r.lavorati)}</td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </div>
        {/if}
    {/if}
</section>

<style>
    .riepilogo {
        margin-top: 1.5rem;
        border-top: 2px solid var(--bs-border-color, #dee2e6);
        padding-top: .75rem;
    }

    .riepilogo-testa {
        display: flex;
        align-items: baseline;
        gap: .75rem;
        margin-bottom: .5rem;
    }

    .riepilogo-titolo {
        margin: 0;
        font-size: 1rem;
    }

    .riepilogo-nota,
    .riepilogo-vuoto {
        font-size: .78rem;
        color: var(--bs-secondary-color, #6c757d);
    }

    .riepilogo-blocco {
        margin-bottom: 1rem;
    }

    .riepilogo-sottotitolo {
        font-size: .8rem;
        text-transform: uppercase;
        letter-spacing: .04em;
        color: var(--bs-secondary-color, #6c757d);
        margin-bottom: .25rem;
    }

    .riepilogo-dovuti {
        text-transform: none;
        letter-spacing: 0;
        font-weight: 600;
        color: var(--bs-body-color, #212529);
        margin-left: .5rem;
    }

    /* Le tabelle sono larghe quanto i lavoratori: scorrono dentro il loro
       riquadro, senza trascinarsi dietro la pagina. */
    .riepilogo-scroll {
        overflow-x: auto;
    }

    .riepilogo-tabella {
        border-collapse: collapse;
        font-size: .75rem;
        white-space: nowrap;
    }

    .riepilogo-tabella th,
    .riepilogo-tabella td {
        border: 1px solid var(--bs-border-color, #dee2e6);
        padding: .1rem .4rem;
        text-align: center;
        min-width: 2.6rem;
    }

    .riepilogo-tabella thead th {
        background: var(--bs-tertiary-bg, #f8f9fa);
        font-weight: 600;
    }

    /* La prima colonna resta ferma: senza, si perde la voce che si sta leggendo. */
    .riepilogo-tabella .voce {
        position: sticky;
        left: 0;
        z-index: 1;
        background: var(--bs-tertiary-bg, #f8f9fa);
        text-align: left;
        min-width: 8rem;
        font-weight: 600;
    }

    .riepilogo-tabella tr.totale td,
    .riepilogo-tabella .totale {
        font-weight: 700;
    }

    .riepilogo-tabella tr.dovuti td {
        font-style: italic;
        color: var(--bs-secondary-color, #6c757d);
    }

    /* Chi e' sotto o sopra i turni dovuti: un'indicazione, non un errore. */
    .riepilogo-tabella td.sotto  { background: #fff3cd; }
    .riepilogo-tabella td.sopra  { background: #d1e7dd; }
</style>
