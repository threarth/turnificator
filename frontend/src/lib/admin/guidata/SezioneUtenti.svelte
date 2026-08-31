<!--
  SezioneUtenti — chi lavora nei turni.

  Senza persone la struttura resta vuota: questa e' la sezione che rende il
  calendario compilabile. I ruoli si spiegano da cosa permettono di fare,
  non con i nomi interni.

  Scrive subito: gli utenti sono dati del tenant, non c'e' niente da
  confermare alla fine.

  Props:
    - utenti      : Array — utenti esistenti
    - strutture   : Array — sovragruppi a cui assegnarli, se gia' esistono
    - etichetta   : {singolare, plurale} — come l'utente chiama le strutture
    - onaggiornati: () => Promise — ricarica l'elenco nel chiamante
-->
<script>
    import { adminApi } from '$lib/api.js';

    export let utenti = [];
    export let strutture = [];
    export let etichetta = { singolare: 'Struttura', plurale: 'Strutture' };
    export let onaggiornati;

    // I ruoli detti per quello che permettono di fare.
    const RUOLI = [
        { valore: 'basic',   nome: 'Lavoratore',
          aiuto: 'Esprime i propri desiderata e vede i turni assegnati.' },
        { valore: 'manager', nome: 'Caposala',
          aiuto: 'Assegna i turni e lavora sui desiderata.' },
        { valore: 'admin',   nome: 'Amministratore',
          aiuto: 'Configura tutto: struttura, calendari, utenti.' },
    ];

    let nuovo = utenteVuoto();
    let errore = '';

    function utenteVuoto() {
        return { username: '', password: '', sigla: '', role: 'basic', sovragruppo_id: null };
    }

    $: puoAggiungere = nuovo.username.trim() && nuovo.password.trim() && nuovo.sigla.trim();
    $: aiutoRuolo = RUOLI.find(r => r.valore === nuovo.role)?.aiuto ?? '';

    /** La sigla e' quella che comparira' nelle celle del calendario. */
    function proponiSigla() {
        if (nuovo.sigla.trim()) return;
        nuovo.sigla = nuovo.username.trim().slice(0, 3).toUpperCase();
    }

    function nomeRuolo(valore) {
        return RUOLI.find(r => r.valore === valore)?.nome ?? valore;
    }

    async function aggiungi() {
        if (!puoAggiungere) return;

        errore = '';
        const r = await adminApi.createUser({ ...nuovo });
        if (!r.ok) { errore = r.errore || 'Creazione non riuscita.'; return; }

        nuovo = utenteVuoto();
        await onaggiornati();
    }
</script>

<p class="guidata-intro">
    Chi lavora nei turni. Senza persone il calendario resta vuoto: i
    lavoratori esprimono i desiderata, i caposala assegnano i turni.
</p>

{#if errore}<div class="alert alert-danger py-2 small">{errore}</div>{/if}

<section class="guidata-sezione">
    <h6 class="guidata-titolo">Le persone già inserite</h6>

    {#if utenti.length}
        <table class="table table-sm align-middle mb-0">
            <thead><tr>
                <th style="width:90px">Sigla</th>
                <th style="width:180px">Nome utente</th>
                <th style="width:150px">Ruolo</th>
                <th style="width:170px">{etichetta.singolare}</th>
                <th style="width:90px">Attivo</th>
            </tr></thead>
            <tbody>
                {#each utenti as u (u.id)}
                    <tr class:text-muted={!u.is_active}>
                        <td class="fw-semibold">{u.sigla}</td>
                        <td>{u.username}</td>
                        <td class="small">{nomeRuolo(u.role)}</td>
                        <td class="small">{u.sovragruppo_nome || '—'}</td>
                        <td class="small">{u.is_active ? 'sì' : 'no'}</td>
                    </tr>
                {/each}
            </tbody>
        </table>
    {:else}
        <p class="guidata-aiuto mb-0">
            Nessuna persona inserita. Comincia da te stesso o da un caposala.
        </p>
    {/if}
</section>

<section class="guidata-sezione guidata-inserimento">
    <h6 class="guidata-titolo">Aggiungi una persona</h6>
    <div class="row g-3 align-items-end">
        <div class="col-auto" style="width:180px">
            <label class="form-label" for="utente-username">Nome utente</label>
            <input id="utente-username" class="form-control form-control-sm"
                   placeholder="es. rossi.mario" bind:value={nuovo.username}
                   on:blur={proponiSigla} />
        </div>
        <div class="col-auto" style="width:110px">
            <label class="form-label" for="utente-sigla">Sigla</label>
            <input id="utente-sigla" class="form-control form-control-sm"
                   placeholder="es. ROS" bind:value={nuovo.sigla} />
        </div>
        <div class="col-auto" style="width:180px">
            <label class="form-label" for="utente-password">Password iniziale</label>
            <input id="utente-password" class="form-control form-control-sm"
                   bind:value={nuovo.password} />
        </div>
        <div class="col-auto" style="width:170px">
            <label class="form-label" for="utente-ruolo">Ruolo</label>
            <select id="utente-ruolo" class="form-select form-select-sm" bind:value={nuovo.role}>
                {#each RUOLI as r}<option value={r.valore}>{r.nome}</option>{/each}
            </select>
        </div>
        {#if strutture.length}
            <div class="col-auto" style="width:190px">
                <label class="form-label" for="utente-struttura">{etichetta.singolare}</label>
                <select id="utente-struttura" class="form-select form-select-sm"
                        bind:value={nuovo.sovragruppo_id}>
                    <option value={null}>— nessuna —</option>
                    {#each strutture as s}<option value={s.id}>{s.nome}</option>{/each}
                </select>
            </div>
        {/if}
        <div class="col-auto">
            <button class="btn btn-primary btn-sm" disabled={!puoAggiungere} on:click={aggiungi}>
                Aggiungi la persona
            </button>
        </div>
    </div>
    <p class="guidata-aiuto mt-2 mb-0">
        {aiutoRuolo} La sigla è quella che comparirà nelle celle del calendario.
        La password è provvisoria: la persona la cambierà al primo accesso.
    </p>
</section>
