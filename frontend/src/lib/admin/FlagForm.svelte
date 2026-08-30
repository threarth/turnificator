<!--
  FlagForm — form di creazione di un flag turno.

  Serve entrambe le tabelle della configurazione: le fasce orarie, che hanno
  orari e pausa, e le assenze, che non ne hanno. La differenza sta tutta nella
  prop `mostraOrari`, cosi' il form esiste in un posto solo.

  Props:
    - flag        : object — stato del nuovo flag (bindable)
    - concetti    : Array — concetti root fra cui scegliere il padre; se vuoto
                    il flag nasce alla radice e il menu non compare
    - assenza     : boolean — flag assenza: niente orari ne' pausa
    - oncreate    : () => void — conferma la creazione
    - oncancel    : () => void — chiude il form
-->
<script>
    import { focusOnMount } from './actions.js';

    export let flag;
    export let concetti = [];
    export let assenza = false;
    export let oncreate;
    export let oncancel;

    // Invio conferma la creazione da qualunque campo di testo.
    function invioConferma(e) {
        if (e.key === 'Enter') oncreate();
    }
</script>

<div class="d-flex gap-2 mb-2 align-items-center flex-wrap">
    <input class="form-control form-control-sm" use:focusOnMount placeholder="Nome"
           bind:value={flag.nome} style="width:150px" on:keydown={invioConferma} />
    <input class="form-control form-control-sm" placeholder="Descrizione"
           bind:value={flag.descrizione} style="width:150px" on:keydown={invioConferma} />
    {#if concetti.length}
        <select class="form-select form-select-sm" style="width:150px" bind:value={flag.parent_id}>
            <option value={null}>— concetto radice —</option>
            {#each concetti as c}
                <option value={c.id}>{c.nome}</option>
            {/each}
        </select>
    {/if}
    {#if !assenza}
        <input class="form-control form-control-sm" placeholder="Inizio"
               bind:value={flag.orario_inizio} style="width:75px" on:keydown={invioConferma} />
        <input class="form-control form-control-sm" placeholder="Fine"
               bind:value={flag.orario_fine} style="width:75px" on:keydown={invioConferma} />
        <input class="form-control form-control-sm" type="number" min="0"
               title="Pausa obbligatoria (minuti)" placeholder="Pausa"
               bind:value={flag.pausa_minuti} style="width:70px" />
    {:else}
        <input class="form-control form-control-sm" placeholder="Ore (h:mm)"
               bind:value={flag._ore_turno} style="width:80px" on:keydown={invioConferma} />
    {/if}
    <input class="form-control form-control-sm" placeholder="1° (h:mm)"
           bind:value={flag._ore_primo} style="width:75px" on:keydown={invioConferma} />
    <input class="form-control form-control-sm" placeholder="Ult (h:mm)"
           bind:value={flag._ore_ultimo} style="width:75px" on:keydown={invioConferma} />
    <button class="btn btn-success btn-sm" title="Crea" on:click={oncreate}><i class="bi bi-check-lg"></i></button>
    <button class="btn btn-secondary btn-sm" title="Annulla" on:click={oncancel}><i class="bi bi-x"></i></button>
</div>
{#if !assenza}
    <div class="form-text small mb-2">
        Ore, durata e peso non si digitano: li ricava il sistema dagli orari e dalla pausa.
    </div>
{/if}
