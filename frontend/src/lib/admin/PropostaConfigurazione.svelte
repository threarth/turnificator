<!--
  PropostaConfigurazione — la proposta arrivata dal gestore, da accettare o no.

  Il gestore dell'installazione può proporre il vocabolario di un altro
  reparto: fasce orarie, tipologie, tipi richiesta e regole. Non applica
  niente da sé — qui l'amministratore vede cosa cambierebbe e decide.

  Il confronto è il punto: senza, accettare sarebbe una scommessa.

  Props:
    - proposta  : object|null — con `differenze`, come la restituisce l'API
    - ondecisa  : () => Promise — ricarica dopo accettazione o rifiuto
-->
<script>
    import { adminApi } from '$lib/api.js';

    export let proposta = null;
    export let ondecisa;

    let aperta = false;
    let inCorso = false;
    let errore = '';

    /** Il nome di un campo come lo legge l'utente. */
    const NOMI_CAMPO = {
        orario_inizio: 'inizio', orario_fine: 'fine', pausa_minuti: 'pausa',
        descrizione: 'descrizione', tipo: 'tipo', categoria: 'severità',
        counting_flag: 'conta le ore', ordine: 'ordine',
        mostra_in_struttura: 'in struttura turni',
        blocca_inserimento: 'blocca', peso_numerico: 'peso',
        offset_giorni: 'giorni di scarto', carico_lavoro: 'carico',
        tipo_regola: 'tipo di regola',
    };

    function nomeCampo(campo) {
        return NOMI_CAMPO[campo] ?? campo;
    }

    function valore(v) {
        if (v === null || v === undefined || v === '') return 'vuoto';
        if (v === 0) return 'no';
        if (v === 1) return 'sì';
        return String(v);
    }

    /** Le parti che hanno qualcosa da dire: le altre non si mostrano. */
    $: partiConCambi = (proposta?.differenze ?? []).filter(
        p => p.nuove.length || p.modificate.length
    );

    async function decidi(azione) {
        inCorso = true;
        errore = '';

        const r = azione === 'accetta'
            ? await adminApi.accettaProposta(proposta.id)
            : await adminApi.rifiutaProposta(proposta.id);

        inCorso = false;
        if (!r.ok) { errore = r.errore || 'Operazione non riuscita.'; return; }

        aperta = false;
        await ondecisa();
    }
</script>

{#if proposta}
    <div class="card border-primary mb-4" style="max-width:840px">
        <div class="card-body">
            <div class="d-flex align-items-start justify-content-between gap-3">
                <div>
                    <div class="fw-semibold">
                        <i class="bi bi-envelope-paper me-2"></i>Il gestore propone una configurazione
                    </div>
                    <div class="text-muted small">
                        <strong>{proposta.nome}</strong>, da {proposta.proposta_da}.
                        {#if proposta.note}<br />{proposta.note}{/if}
                    </div>
                </div>
                <button class="btn btn-outline-primary btn-sm text-nowrap"
                        on:click={() => aperta = !aperta}>
                    {aperta ? 'Nascondi' : 'Vedi cosa cambia'}
                </button>
            </div>

            {#if errore}<div class="alert alert-danger py-2 small mt-3 mb-0">{errore}</div>{/if}

            {#if aperta}
                <hr />
                {#if proposta.senza_effetto}
                    <p class="text-muted small mb-3">
                        La proposta coincide con quello che hai già: accettarla non
                        cambierebbe nulla.
                    </p>
                {:else}
                    {#each partiConCambi as parte}
                        <div class="mb-3">
                            <div class="fw-semibold small">{parte.etichetta}</div>
                            <ul class="small mb-1 ps-3">
                                {#each parte.nuove as n}
                                    <li><strong>{n.nome}</strong> — nuova</li>
                                {/each}
                                {#each parte.modificate as m}
                                    <li>
                                        <strong>{m.nome}</strong> —
                                        {#each m.cambi as c, i}{i ? '; ' : ''}{nomeCampo(c.campo)}
                                            da {valore(c.prima)} a {valore(c.dopo)}{/each}
                                    </li>
                                {/each}
                            </ul>
                            {#if parte.solo_qui.length}
                                <div class="text-muted" style="font-size:.75rem">
                                    Resta com'è: {parte.solo_qui.join(', ')}
                                </div>
                            {/if}
                        </div>
                    {/each}
                    <p class="text-muted mb-3" style="font-size:.8rem">
                        Accettare non cancella niente: quello che hai in più resta dov'è.
                        La struttura turni, le persone, i vincoli e i conteggi non
                        vengono toccati.
                    </p>
                {/if}

                <div class="d-flex gap-2">
                    <button class="btn btn-success btn-sm" disabled={inCorso}
                            on:click={() => decidi('accetta')}>
                        {inCorso ? 'Applico…' : 'Accetta la proposta'}
                    </button>
                    <button class="btn btn-outline-secondary btn-sm" disabled={inCorso}
                            on:click={() => decidi('rifiuta')}>
                        Rifiuta
                    </button>
                </div>
            {/if}
        </div>
    </div>
{/if}
