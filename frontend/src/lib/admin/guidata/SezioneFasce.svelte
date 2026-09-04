<!--
  SezioneFasce — le fasce orarie: da che ora a che ora dura un turno.

  Nuova feature (le due impostazioni qui sotto) piu' estrazione: la sezione
  stava inline in ConfigurazioneGuidata. Non condivide stato con le altre:
  lavora sui flag veri e salva subito, perche' le fasce sono in comune fra
  tutte le strutture turni.

  Oltre agli orari la sezione imposta due cose che servono al riempimento
  automatico:
    - solo su richiesta: la fascia si mette solo dove il lavoratore l'ha
      chiesta, mai di iniziativa del programma;
    - composizione: quali fasce, messe insieme, soddisfano la richiesta di
      un'altra. Si imposta, non si deriva dagli orari.

  Props:
    - fasce       : Array — le fasce agganciabili, gia' ordinate per orario
    - concetti    : Array — i concetti root sotto cui una fascia puo' stare
    - onaggiornate: () => Promise — ricarica i flag nel chiamante
-->
<script>
    import { adminApi } from '$lib/api.js';
    import { minToHm } from '../durate.js';

    export let fasce = [];
    export let concetti = [];
    export let onaggiornate;

    // Pausa obbligatoria di default, in minuti.
    const PAUSA_DEFAULT_MINUTI = 10;

    let errore = '';

    // Form di creazione di una fascia nuova.
    let nuova = fasciaVuota();

    // Modifiche in corso, per id fascia. Restano in sospeso finche' non si
    // preme Salva: cambiare un orario e' una correzione, non un gesto.
    let modifiche = {};

    // La fascia di cui e' aperto l'editor di composizione, o null.
    let composizioneAperta = null;

    function fasciaVuota() {
        return {
            nome: '', parent_id: null,
            orario_inizio: '', orario_fine: '', pausa_minuti: PAUSA_DEFAULT_MINUTI,
        };
    }

    $: if (!nuova.parent_id && concetti.length) {
        nuova.parent_id = concetti[0].id;
    }

    /** Una fascia e' pronta se ha nome, categoria ed entrambi gli orari. */
    $: nuovaCompleta = nuova.nome.trim()
        && nuova.parent_id
        && nuova.orario_inizio.trim()
        && nuova.orario_fine.trim();

    /** Il valore in vigore per un campo: la modifica in sospeso, o il salvato. */
    function valore(fascia, campo) {
        return modifiche[fascia.id]?.[campo] ?? fascia[campo];
    }

    /** I nomi delle fasce che compongono questa, per il riepilogo di riga. */
    function nomiComponenti(fascia) {
        const ids = valore(fascia, 'componenti') ?? [];
        return ids
            .map(id => fasce.find(f => f.id === id)?.nome)
            .filter(Boolean);
    }

    async function aggiungi() {
        if (!nuovaCompleta) return;

        errore = '';
        const r = await adminApi.creaFlagTurno({ ...nuova, tipo: 'lavorativo' });
        if (!r.ok) { errore = r.errore || 'Creazione della fascia non riuscita.'; return; }

        nuova = fasciaVuota();
        await onaggiornate();
    }

    /** Registra la modifica di un campo senza salvarla: serve il pulsante. */
    function modifica(fascia, campo, valoreNuovo) {
        const corrente = modifiche[fascia.id] ?? {
            orario_inizio: fascia.orario_inizio ?? '',
            orario_fine: fascia.orario_fine ?? '',
            pausa_minuti: fascia.pausa_minuti ?? PAUSA_DEFAULT_MINUTI,
            solo_su_richiesta: fascia.solo_su_richiesta ?? 0,
            componenti: [...(fascia.componenti ?? [])],
        };
        modifiche = { ...modifiche, [fascia.id]: { ...corrente, [campo]: valoreNuovo } };
    }

    /** Aggiunge o toglie una fascia dalla composizione di un'altra. */
    function commutaComponente(fascia, componente) {
        const attuali = valore(fascia, 'componenti') ?? [];
        const nuovi = attuali.includes(componente.id)
            ? attuali.filter(id => id !== componente.id)
            : [...attuali, componente.id];
        modifica(fascia, 'componenti', nuovi);
    }

    async function salva(fascia) {
        const pendente = modifiche[fascia.id];
        if (!pendente) return;

        errore = '';
        const r = await adminApi.editFlagTurno(fascia.id, pendente);
        if (!r.ok) { errore = r.errore || 'Modifica della fascia non riuscita.'; return; }

        const { [fascia.id]: _salvata, ...resto } = modifiche;
        modifiche = resto;
        await onaggiornate();
    }
</script>

<p class="guidata-intro">
    Una fascia oraria è l'orario di un turno: da che ora a che ora.
    Bastano quelli — durata, ore e peso li ricava il programma da sé.
</p>

{#if errore}
    <div class="alert alert-danger py-2 small">{errore}</div>
{/if}

<section class="guidata-sezione">
    <h6 class="guidata-titolo">Le fasce già disponibili</h6>
    <p class="guidata-aiuto">
        Se un orario non corrisponde ai tuoi turni, correggilo qui.
        Le fasce sono in comune: la correzione vale per ogni struttura
        turni, non solo per quella che stai creando.
    </p>

    <table class="table table-sm align-middle mb-0">
        <thead><tr>
            <th style="width:130px">Fascia</th>
            <th style="width:105px">Categoria</th>
            <th style="width:90px">Inizio</th>
            <th style="width:90px">Fine</th>
            <th style="width:95px">Pausa (min)</th>
            <th style="width:80px">Durata</th>
            <th style="width:95px" title="Il riempimento automatico non la propone da sé">
                Su richiesta
            </th>
            <th style="width:190px">Composta da</th>
            <th style="width:70px"></th>
        </tr></thead>
        <tbody>
            {#each fasce as f (f.id)}
                {@const pendente = modifiche[f.id]}
                {@const componenti = nomiComponenti(f)}
                <tr class:table-warning={pendente}>
                    <td class="fw-semibold">{f.nome}</td>
                    <td class="small text-muted">{f.parent_nome || '—'}</td>
                    <td><input class="form-control form-control-sm" aria-label="Inizio di {f.nome}"
                               value={pendente?.orario_inizio ?? f.orario_inizio ?? ''}
                               on:input={e => modifica(f, 'orario_inizio', e.target.value)} /></td>
                    <td><input class="form-control form-control-sm" aria-label="Fine di {f.nome}"
                               value={pendente?.orario_fine ?? f.orario_fine ?? ''}
                               on:input={e => modifica(f, 'orario_fine', e.target.value)} /></td>
                    <td><input class="form-control form-control-sm" type="number" min="0"
                               aria-label="Pausa di {f.nome}"
                               value={pendente?.pausa_minuti ?? f.pausa_minuti ?? 0}
                               on:input={e => modifica(f, 'pausa_minuti', e.target.value)} /></td>
                    <td class="small text-muted">{minToHm(f.durata_totale_minuti) || '—'}</td>
                    <td class="text-center">
                        <input class="form-check-input" type="checkbox"
                               aria-label="{f.nome}: solo su richiesta"
                               checked={!!valore(f, 'solo_su_richiesta')}
                               on:change={e => modifica(f, 'solo_su_richiesta', e.target.checked ? 1 : 0)} />
                    </td>
                    <td>
                        <button class="btn btn-link btn-sm p-0 text-decoration-none small"
                                on:click={() => composizioneAperta = composizioneAperta === f.id ? null : f.id}>
                            {#if componenti.length}
                                = {componenti.join(' + ')}
                            {:else}
                                Imposta…
                            {/if}
                        </button>
                    </td>
                    <td>
                        {#if pendente}
                            <button class="btn btn-warning btn-sm py-0" on:click={() => salva(f)}>
                                Salva
                            </button>
                        {/if}
                    </td>
                </tr>

                {#if composizioneAperta === f.id}
                    <tr class="guidata-composizione">
                        <td colspan="9">
                            <p class="guidata-aiuto mb-2">
                                Quali fasce, messe insieme, soddisfano una richiesta di
                                <strong>{f.nome}</strong>. Chi la chiede può ricevere quelle
                                al suo posto: la richiesta è soddisfatta quando le ha tutte.
                            </p>
                            <div class="d-flex flex-wrap gap-3">
                                {#each fasce.filter(c => c.id !== f.id) as c (c.id)}
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox"
                                               id="comp-{f.id}-{c.id}"
                                               checked={(valore(f, 'componenti') ?? []).includes(c.id)}
                                               on:change={() => commutaComponente(f, c)} />
                                        <label class="form-check-label small" for="comp-{f.id}-{c.id}">
                                            {c.nome}
                                        </label>
                                    </div>
                                {/each}
                            </div>
                        </td>
                    </tr>
                {/if}
            {/each}
        </tbody>
    </table>

    <p class="guidata-aiuto mt-2 mb-0">
        <strong>Su richiesta</strong> è un'impostazione per il riempimento
        automatico: la fascia non viene proposta di sua iniziativa, ma solo a
        chi l'ha chiesta. È il caso della lunga.
    </p>
</section>

<section class="guidata-sezione guidata-inserimento">
    <h6 class="guidata-titolo">Aggiungi una fascia</h6>
    <div class="row g-3 align-items-end">
        <div class="col-auto" style="width:180px">
            <label class="form-label" for="fascia-nome">Nome</label>
            <input id="fascia-nome" class="form-control form-control-sm"
                   placeholder="es. sera" bind:value={nuova.nome} />
        </div>
        <div class="col-auto" style="width:170px">
            <label class="form-label" for="fascia-categoria">Categoria</label>
            <select id="fascia-categoria" class="form-select form-select-sm" bind:value={nuova.parent_id}>
                {#each concetti as c}
                    <option value={c.id}>{c.nome}</option>
                {/each}
            </select>
        </div>
        <div class="col-auto" style="width:110px">
            <label class="form-label" for="fascia-inizio">Inizio</label>
            <input id="fascia-inizio" class="form-control form-control-sm"
                   placeholder="16:00" bind:value={nuova.orario_inizio} />
        </div>
        <div class="col-auto" style="width:110px">
            <label class="form-label" for="fascia-fine">Fine</label>
            <input id="fascia-fine" class="form-control form-control-sm"
                   placeholder="22:20" bind:value={nuova.orario_fine} />
        </div>
        <div class="col-auto" style="width:110px">
            <label class="form-label" for="fascia-pausa">Pausa (min)</label>
            <input id="fascia-pausa" class="form-control form-control-sm" type="number" min="0"
                   bind:value={nuova.pausa_minuti} />
        </div>
        <div class="col-auto">
            <button class="btn btn-primary btn-sm" disabled={!nuovaCompleta} on:click={aggiungi}>
                Aggiungi la fascia
            </button>
        </div>
    </div>
    <p class="guidata-aiuto mt-2 mb-0">
        La categoria dice se la fascia è diurna, notturna o di guardia.
        Il programma la usa per applicare le regole da sé: dopo una
        notte, per esempio, il riposo del giorno dopo è obbligatorio.
    </p>
</section>

<style>
    .guidata-composizione td {
        background: #f8f9fa;
    }
</style>
