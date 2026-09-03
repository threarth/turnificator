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
    import { etichettaManager } from '$lib/etichette.js';

    export let utenti = [];
    export let strutture = [];
    export let etichetta = { singolare: 'Struttura', plurale: 'Strutture' };
    export let onaggiornati;

    // Come si chiama chi pianifica i turni: cambia con il reparto, e la
    // parola scelta vale in tutto il programma.
    const NOMI_PIANIFICATORE = [
        'Caposala', 'Capotecnico', 'Primario', 'Pianificatore',
    ];

    // I ruoli detti per quello che permettono di fare, non con i nomi interni.
    $: RUOLI = [
        { valore: 'basic',   nome: 'Lavoratore',
          aiuto: 'Esprime i propri desiderata e vede i turni assegnati.' },
        { valore: 'manager', nome: $etichettaManager,
          aiuto: 'Assegna i turni e lavora sui desiderata.' },
        { valore: 'admin',   nome: 'Amministratore',
          aiuto: 'Configura tutto: struttura, calendari, utenti.' },
    ];

    let etichettaLibera = false;

    async function scegliNomePianificatore(nome) {
        etichettaLibera = nome === null;
        if (!nome) return;

        etichettaManager.set(nome);
        await adminApi.setConfig({ etichetta_manager: nome });
    }

    /** Salva la parola digitata a mano, quando l'utente smette di scrivere. */
    async function salvaNomeLibero() {
        const nome = $etichettaManager.trim();
        if (nome) await adminApi.setConfig({ etichetta_manager: nome });
    }

    let nuovo = utenteVuoto();
    let errore = '';

    // Inserimento in blocco: si incolla la colonna delle sigle da un foglio.
    let sigleIncollate = '';
    let bloccoRuolo = 'basic';
    let bloccoStruttura = null;
    let inCorso = false;
    let credenziali = [];

    // Lunghezza della password provvisoria generata per ogni persona.
    const CIFRE_PASSWORD = 10;
    const ALFABETO = 'abcdefghijkmnopqrstuvwxyz23456789';

    /** Sigle separate da spazi, virgole o a capo — come vengono da un incolla. */
    $: sigleDaCreare = [...new Set(
        sigleIncollate.split(/[\s,;]+/)
            .map(s => s.trim().toUpperCase())
            .filter(Boolean)
    )];

    $: sigleGiaPresenti = sigleDaCreare.filter(
        s => utenti.some(u => (u.sigla || '').toUpperCase() === s)
    );
    $: sigleNuove = sigleDaCreare.filter(s => !sigleGiaPresenti.includes(s));

    /** Una password provvisoria leggibile, diversa per ciascuno. */
    function passwordProvvisoria() {
        const numeri = crypto.getRandomValues(new Uint32Array(CIFRE_PASSWORD));
        return [...numeri].map(n => ALFABETO[n % ALFABETO.length]).join('');
    }

    async function creaInBlocco() {
        if (!sigleNuove.length || inCorso) return;

        inCorso = true;
        errore = '';
        credenziali = [];

        const falliti = [];
        for (const sigla of sigleNuove) {
            const password = passwordProvvisoria();
            const r = await adminApi.createUser({
                username: sigla.toLowerCase(), sigla, password,
                role: bloccoRuolo, sovragruppo_id: bloccoStruttura,
            });

            if (r.ok) credenziali = [...credenziali, { sigla, username: sigla.toLowerCase(), password }];
            else falliti.push(`${sigla}: ${r.errore || 'errore'}`);
        }

        inCorso = false;
        if (falliti.length) errore = falliti.join(' · ');
        if (credenziali.length) sigleIncollate = '';

        await onaggiornati();
    }

    /** Sposta una persona in un'altra struttura. */
    async function cambiaStruttura(utente, sovragruppoId) {
        errore = '';
        const r = await adminApi.editUtente(utente.id, {
            ...utente, sovragruppo_id: sovragruppoId || null,
        });
        if (!r.ok) { errore = r.errore || 'Modifica non riuscita.'; return; }

        await onaggiornati();
    }

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
    <h6 class="guidata-titolo">Come chiami chi pianifica i turni</h6>
    <p class="guidata-aiuto">
        A seconda del reparto è un caposala, un capotecnico o un primario. La
        parola che scegli comparirà ovunque il programma nomini quel ruolo.
    </p>
    <div class="d-flex gap-2 align-items-center flex-wrap">
        {#each NOMI_PIANIFICATORE as nome}
            <button class="btn btn-sm {!etichettaLibera && $etichettaManager === nome
                                       ? 'btn-primary' : 'btn-outline-secondary'}"
                    on:click={() => scegliNomePianificatore(nome)}>{nome}</button>
        {/each}
        <button class="btn btn-sm {etichettaLibera ? 'btn-primary' : 'btn-outline-secondary'}"
                on:click={() => scegliNomePianificatore(null)}>Un'altra parola…</button>
    </div>
    {#if etichettaLibera}
        <div class="mt-2" style="width:220px">
            <label class="form-label visually-hidden" for="nome-pianificatore">Come lo chiami</label>
            <input id="nome-pianificatore" class="form-control form-control-sm"
                   placeholder="es. Coordinatore"
                   bind:value={$etichettaManager} on:blur={salvaNomeLibero} />
        </div>
    {/if}
</section>

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
                        <td>
                            {#if strutture.length}
                                <select class="form-select form-select-sm"
                                        value={u.sovragruppo_id ?? ''}
                                        on:change={e => cambiaStruttura(u, e.target.value ? +e.target.value : null)}>
                                    <option value="">— nessuna —</option>
                                    {#each strutture as s}
                                        <option value={s.id}>{s.nome}</option>
                                    {/each}
                                </select>
                            {:else}
                                <span class="text-muted small">—</span>
                            {/if}
                        </td>
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
    <h6 class="guidata-titolo">Inserisci un elenco di sigle</h6>
    <p class="guidata-aiuto">
        Incolla la colonna delle sigle da un foglio di calcolo. Il nome utente
        è la sigla in minuscolo, e per ciascuno viene generata una password
        provvisoria diversa, che ti compare qui sotto da consegnare.
    </p>

    <div class="row g-3 align-items-end">
        <div class="col-auto" style="width:300px">
            <label class="form-label" for="sigle-blocco">Sigle</label>
            <textarea id="sigle-blocco" class="form-control form-control-sm" rows="4"
                      placeholder="ROS&#10;BIA&#10;VER" bind:value={sigleIncollate}></textarea>
        </div>
        <div class="col-auto" style="width:170px">
            <label class="form-label" for="blocco-ruolo">Ruolo</label>
            <select id="blocco-ruolo" class="form-select form-select-sm" bind:value={bloccoRuolo}>
                {#each RUOLI as r}<option value={r.valore}>{r.nome}</option>{/each}
            </select>
        </div>
        {#if strutture.length}
            <div class="col-auto" style="width:190px">
                <label class="form-label" for="blocco-struttura">{etichetta.singolare}</label>
                <select id="blocco-struttura" class="form-select form-select-sm"
                        bind:value={bloccoStruttura}>
                    <option value={null}>— nessuna —</option>
                    {#each strutture as s}<option value={s.id}>{s.nome}</option>{/each}
                </select>
            </div>
        {/if}
        <div class="col-auto">
            <button class="btn btn-primary btn-sm" disabled={!sigleNuove.length || inCorso}
                    on:click={creaInBlocco}>
                {inCorso ? 'Creo…' : `Crea ${sigleNuove.length || ''} persone`.trim()}
            </button>
        </div>
    </div>

    {#if sigleGiaPresenti.length}
        <p class="guidata-aiuto mt-2 mb-0">
            Già presenti, verranno saltate: {sigleGiaPresenti.join(', ')}
        </p>
    {/if}

    {#if credenziali.length}
        <div class="mt-3">
            <div class="fw-semibold small mb-1">Password provvisorie da consegnare</div>
            <p class="guidata-aiuto">
                Compaiono una volta sola: copiale adesso. Ciascuno la cambierà al
                primo accesso.
            </p>
            <table class="table table-sm align-middle mb-0" style="max-width:420px">
                <thead><tr>
                    <th style="width:90px">Sigla</th>
                    <th style="width:140px">Nome utente</th>
                    <th style="width:160px">Password</th>
                </tr></thead>
                <tbody>
                    {#each credenziali as c}
                        <tr>
                            <td class="fw-semibold">{c.sigla}</td>
                            <td class="small">{c.username}</td>
                            <td><code>{c.password}</code></td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
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
