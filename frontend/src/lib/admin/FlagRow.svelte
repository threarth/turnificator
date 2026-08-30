<!--
  FlagRow — una riga della tabella dei flag turno (concetti root e fasce orarie).

  Concetti root e fasce figlie differiscono solo per rientro, colonna parent e
  pulsanti: il resto delle celle e' identico, e in piu' ogni riga esiste in due
  versioni, vista e modifica. Tenerle in un unico componente evita di ripetere
  quattro volte le stesse quattordici celle.

  Durata netta, ore e peso sono derivati dagli orari: si mostrano in sola
  lettura sulle fasce che li derivano, e restano digitabili sui flag che non
  hanno orari (assenze e concetti senza durata propria).

  Props:
    - flag            : object — riga flag_turno
    - assenza         : boolean — la riga e' un flag assenza: niente orari,
                        niente pausa, netta o peso, e mai in struttura turni
    - figlio          : boolean — riga di una fascia oraria sotto il suo concetto
    - parentNome      : string — nome del concetto padre ('' sulle root)
    - haFigli         : boolean — la root ha fasce figlie
    - espanso         : boolean — le figlie sono visibili
    - editing         : object|null — flag in modifica (bindable)
    - autoFocus       : action Svelte per il focus sul campo cliccato
    - ontogglecollapse: () => void — apri/chiudi le figlie
    - onstartedit     : (MouseEvent) => void — entra in modifica
    - onsave          : () => void — salva le modifiche
    - oncancel        : () => void — annulla le modifiche
    - ondelete        : () => void — elimina il flag
    - onaddchild      : (() => void)|null — aggiungi una fascia (solo sui concetti)
-->
<script>
    import DeleteButton from './DeleteButton.svelte';
    import { editRowKeydown } from './actions.js';
    import { decToHm, minToHm } from './durate.js';
    import { NOME_TURNO_TIPO } from '$lib/fasceOrarie.js';

    export let flag;
    export let assenza = false;
    export let figlio = false;
    export let parentNome = '';
    export let haFigli = false;
    export let espanso = true;
    export let editing = null;
    export let autoFocus;
    export let ontogglecollapse = null;
    export let onstartedit;
    export let onsave;
    export let oncancel;
    export let ondelete;
    export let onaddchild = null;

    // Rientro delle fasce sotto il concetto che le raggruppa.
    const RIENTRO_FIGLIO = '20px';

    $: inModifica = editing?.id === flag.id;

    // Una fascia con orari — o il turno tipo, che ha solo la durata netta —
    // ricava ore e peso dal calcolo: digitarli non avrebbe effetto.
    $: derivato = !!(flag.orario_inizio && flag.orario_fine)
                  || flag.durata_netta_minuti != null;

    // La netta si digita solo dove non discende dagli orari: e' il caso del
    // turno tipo, la cui durata e' il metro su cui si misura ogni peso.
    $: nettaDigitabile = !(flag.orario_inizio && flag.orario_fine);

    // Il turno tipo non classifica turni: e' il metro con cui si misura il
    // peso degli altri, quello che dice se una lunga vale due turni e se una
    // notte pure. Se ne cambia la durata, non il nome — il ricalcolo lo cerca
    // per nome — e non si elimina.
    $: turnoTipo = flag.nome === NOME_TURNO_TIPO;

    const SPIEGAZIONE_TURNO_TIPO =
        'Il metro con cui si misura il peso degli altri turni: quanti turni '
        + 'tipo vale una lunga, una notte, una guardia. Se ne può cambiare la '
        + 'durata, non il nome.';

    $: tastiRiga = editRowKeydown(onsave, oncancel);
</script>

<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
<tr class={inModifica ? 'table-warning' : 'editable-row'}
    on:click={e => { if (!inModifica) onstartedit(e); }}>
    {#if inModifica}
        {#if turnoTipo}
            <td class="fw-semibold" title={SPIEGAZIONE_TURNO_TIPO}>{flag.nome}</td>
        {:else}
            <td><input class="form-control form-control-sm" use:autoFocus={'nome'}
                       bind:value={editing.nome}
                       style={figlio ? `padding-left:${RIENTRO_FIGLIO}` : ''}
                       on:keydown={tastiRiga} /></td>
        {/if}
        <td><input class="form-control form-control-sm" use:autoFocus={'descrizione'}
                   bind:value={editing.descrizione} on:keydown={tastiRiga} /></td>
        <td class="small">{figlio ? parentNome : '—'}</td>
        {#if !assenza}
            <td><input class="form-control form-control-sm" use:autoFocus={'orario_inizio'}
                       bind:value={editing.orario_inizio} placeholder="hh:mm"
                       style="min-width:55px" on:keydown={tastiRiga} /></td>
            <td><input class="form-control form-control-sm" use:autoFocus={'orario_fine'}
                       bind:value={editing.orario_fine} placeholder="hh:mm"
                       style="min-width:55px" on:keydown={tastiRiga} /></td>
            <td><input class="form-control form-control-sm" use:autoFocus={'pausa_minuti'} type="number"
                       bind:value={editing.pausa_minuti} min="0"
                       style="min-width:50px" on:keydown={tastiRiga} /></td>
            {#if nettaDigitabile}
                <td><input class="form-control form-control-sm" use:autoFocus={'durata_netta'}
                           bind:value={editing._netta} placeholder="h:mm"
                           style="min-width:55px" on:keydown={tastiRiga} /></td>
            {:else}
                <td class="small text-muted">{minToHm(flag.durata_netta_minuti) || '—'}</td>
            {/if}
        {/if}
        {#if derivato}
            <td class="small text-muted">{decToHm(flag.ore_turno) || '—'}</td>
        {:else}
            <td><input class="form-control form-control-sm" use:autoFocus={'ore_turno'}
                       bind:value={editing._ore_turno} placeholder="h:mm"
                       style="min-width:55px" on:keydown={tastiRiga} /></td>
        {/if}
        {#if !assenza}
            {#if derivato}
                <td class="small text-muted">{flag.peso_turno ?? '—'}</td>
            {:else}
                <td><input class="form-control form-control-sm" use:autoFocus={'peso_turno'} type="number"
                           bind:value={editing.peso_turno}
                           style="min-width:50px" on:keydown={tastiRiga} /></td>
            {/if}
        {/if}
        <td><input class="form-control form-control-sm" use:autoFocus={'ore_primo'}
                   bind:value={editing._ore_primo} placeholder="h:mm"
                   style="min-width:55px" on:keydown={tastiRiga} /></td>
        <td><input class="form-control form-control-sm" use:autoFocus={'ore_ultimo'}
                   bind:value={editing._ore_ultimo} placeholder="h:mm"
                   style="min-width:55px" on:keydown={tastiRiga} /></td>
        <td>
            <select class="form-select form-select-sm" style="min-width:90px"
                    bind:value={editing.tipo} on:keydown={tastiRiga}>
                <option value="lavorativo">lavorativo</option>
                <option value="assenza">assenza</option>
            </select>
        </td>
        {#if !assenza}
            <td class="text-center"><input type="checkbox"
                       bind:checked={editing.mostra_in_struttura} on:keydown={tastiRiga} /></td>
        {/if}
        <td style="white-space:nowrap" on:click|stopPropagation>
            <button class="btn btn-success btn-sm py-0" title="Salva" on:click={onsave}><i class="bi bi-check-lg"></i></button>
            <button class="btn btn-secondary btn-sm py-0" title="Annulla" on:click={oncancel}><i class="bi bi-x"></i></button>
        </td>
    {:else}
        <td class={figlio ? '' : 'fw-semibold'} data-field="nome"
            title={turnoTipo ? SPIEGAZIONE_TURNO_TIPO : ''}
            style={figlio ? `padding-left:${RIENTRO_FIGLIO}` : ''}>
            {#if haFigli}
                <!-- svelte-ignore a11y-click-events-have-key-events -->
                <!-- svelte-ignore a11y-no-static-element-interactions -->
                <span class="me-1" style="cursor:pointer;user-select:none"
                      on:click|stopPropagation={ontogglecollapse}>
                    <i class="bi bi-chevron-{espanso ? 'down' : 'right'} small"></i>
                </span>
            {/if}{figlio ? '└ ' : ''}{flag.nome}
        </td>
        <td class="small text-muted" data-field="descrizione">{flag.descrizione || '—'}</td>
        <td class="small">{figlio ? parentNome : '—'}</td>
        {#if !assenza}
            <td class="small" data-field="orario_inizio">{flag.orario_inizio || '—'}</td>
            <td class="small" data-field="orario_fine">{flag.orario_fine || '—'}</td>
            <td class="small" data-field="pausa_minuti">{flag.pausa_minuti ?? '—'}</td>
            <td class="small {nettaDigitabile ? '' : 'text-muted'}" data-field="durata_netta">{minToHm(flag.durata_netta_minuti) || '—'}</td>
        {/if}
        <td class="small {derivato ? 'text-muted' : ''}" data-field="ore_turno">{decToHm(flag.ore_turno) || '—'}</td>
        {#if !assenza}
            <td class="small {derivato ? 'text-muted' : ''}" data-field="peso_turno">{flag.peso_turno ?? '—'}</td>
        {/if}
        <td class="small" data-field="ore_primo">{decToHm(flag.ore_primo_giorno) || '—'}</td>
        <td class="small" data-field="ore_ultimo">{decToHm(flag.ore_ultimo_giorno) || '—'}</td>
        <td class="small" data-field="tipo">{flag.tipo || 'lavorativo'}</td>
        {#if !assenza}
            <td class="text-center" data-field="mostra_in_struttura">{flag.mostra_in_struttura ? '✓' : '—'}</td>
        {/if}
        <td style="white-space:nowrap" on:click|stopPropagation>
            {#if onaddchild}
                <button class="btn btn-outline-success btn-sm py-0 px-1" title="Aggiungi fascia oraria"
                        on:click={onaddchild}><i class="bi bi-plus"></i></button>
            {/if}
            {#if !turnoTipo}
                <DeleteButton ondelete={ondelete} stopPropagation />
            {/if}
        </td>
    {/if}
</tr>
