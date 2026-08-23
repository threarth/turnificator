<script>
  /**
   * /manuale — manuale operativo del Turnificator.
   *
   * Il testo vive in $lib/manuale/contenuto.js; qui stanno solo la
   * presentazione (tipografia e colori dell'app, tema chiaro/scuro
   * ereditato da Bootstrap) e il filtro di lettura per ruolo.
   *
   * Nuova feature: documentazione in-app consultabile dalla navbar.
   */
  import { user } from '$lib/auth.js';
  import { SEZIONI, SOMMARIO } from '$lib/manuale/contenuto.js';

  // Ruoli che leggono il manuale per intero: hanno responsabilita' di
  // configurazione o di costruzione della griglia.
  const RUOLI_VISIONE_COMPLETA = ['master_admin', 'admin', 'manager'];

  // Sezioni visibili a chi ha solo funzioni base (lavoratore): l'unica
  // operazione che gli compete e' l'inserimento dei propri desiderata.
  const SEZIONI_RUOLO_BASE = ['desiderata'];

  let visioneCompleta = $derived(RUOLI_VISIONE_COMPLETA.includes($user?.role));

  let sezioniVisibili = $derived(
      visioneCompleta
          ? SEZIONI
          : SEZIONI.filter((s) => SEZIONI_RUOLO_BASE.includes(s.id))
  );
</script>

<svelte:head>
  <title>Manuale — Turnificator</title>
</svelte:head>

<div class="container-fluid py-4">
  <div class="row justify-content-center">
    <div class="col-12 col-xxl-11">

      <header class="mb-4">
        <h1 class="h3 fw-bold mb-2">
          <i class="bi bi-book me-2"></i>Manuale operativo
        </h1>
        <p class="text-secondary mb-0" style="max-width: 70ch;">{SOMMARIO}</p>

        {#if !visioneCompleta}
          <div class="alert alert-info d-flex align-items-start gap-2 mt-3 mb-0">
            <i class="bi bi-info-circle-fill mt-1"></i>
            <div>
              Questa pagina mostra le funzioni che ti riguardano. Le sezioni su
              struttura dei turni, griglia e configurazione sono riservate a chi
              costruisce i turni.
            </div>
          </div>
        {/if}
      </header>

      <div class="row g-4">

        <!-- Indice: elenca solo le sezioni effettivamente leggibili -->
        <nav class="col-12 col-lg-3" aria-label="Indice del manuale">
          <div class="list-group list-group-flush border rounded sticky-lg-top"
               style="top: 5rem;">
            <div class="list-group-item bg-body-tertiary fw-semibold small text-uppercase text-secondary">
              Indice
            </div>
            {#each sezioniVisibili as sezione (sezione.id)}
              <a class="list-group-item list-group-item-action py-2"
                 href="#{sezione.id}">{sezione.titolo}</a>
            {/each}
          </div>
        </nav>

        <div class="col-12 col-lg-9">
          {#each sezioniVisibili as sezione (sezione.id)}
            <section id={sezione.id} class="card mb-4">
              <div class="card-header bg-body-tertiary">
                <h2 class="h5 mb-0 fw-semibold">{sezione.titolo}</h2>
              </div>
              <div class="card-body manuale-corpo">
                {@html sezione.html}
              </div>
            </section>
          {/each}
        </div>

      </div>
    </div>
  </div>
</div>

<style>
  /*
   * Il contenuto arriva da {@html}: lo scoping automatico di Svelte non lo
   * raggiunge, quindi i selettori sono :global() ancorati a .manuale-corpo.
   * Ogni colore passa dalle variabili Bootstrap, cosi' la pagina segue il
   * tema chiaro/scuro dell'app senza duplicare la palette.
   */

  .manuale-corpo :global(h3) {
    font-size: 1rem;
    font-weight: 600;
    margin: 1.75rem 0 .6rem;
    padding-bottom: .3rem;
    border-bottom: 1px solid var(--bs-border-color);
  }

  .manuale-corpo :global(h3:first-child) {
    margin-top: 0;
  }

  .manuale-corpo :global(p) {
    max-width: 78ch;
    line-height: 1.65;
  }

  .manuale-corpo :global(code) {
    font-size: .875em;
    padding: .1rem .3rem;
    border-radius: var(--bs-border-radius-sm);
    background: var(--bs-secondary-bg);
    color: var(--bs-emphasis-color);
  }

  /* --- Etichette di ruolo ------------------------------------------- */

  .manuale-corpo :global(.chip) {
    display: inline-block;
    font-family: var(--bs-font-monospace);
    font-size: .7rem;
    font-weight: 500;
    padding: .1rem .42rem;
    border-radius: var(--bs-border-radius-sm);
    border: 1px solid var(--bs-border-color);
    background: var(--bs-secondary-bg);
    color: var(--bs-secondary-color);
    white-space: nowrap;
  }

  .manuale-corpo :global(.chip-master) {
    background: var(--bs-danger-bg-subtle);
    border-color: var(--bs-danger-border-subtle);
    color: var(--bs-danger-text-emphasis);
  }

  .manuale-corpo :global(.chip-admin) {
    background: var(--bs-primary-bg-subtle);
    border-color: var(--bs-primary-border-subtle);
    color: var(--bs-primary-text-emphasis);
  }

  .manuale-corpo :global(.chip-mgr) {
    background: var(--bs-success-bg-subtle);
    border-color: var(--bs-success-border-subtle);
    color: var(--bs-success-text-emphasis);
  }

  .manuale-corpo :global(.chip-basic) {
    background: var(--bs-secondary-bg);
    border-color: var(--bs-border-color);
    color: var(--bs-secondary-color);
  }

  /* --- Scala gerarchica dei ruoli ----------------------------------- */

  .manuale-corpo :global(.ladder) {
    margin: 1.25rem 0;
  }

  .manuale-corpo :global(.rung) {
    display: flex;
    gap: .85rem;
    margin-bottom: .85rem;
  }

  .manuale-corpo :global(.rung-bar) {
    flex: 0 0 4px;
    border-radius: 2px;
    background: var(--bs-secondary-color);
  }

  .manuale-corpo :global(.rung-1 .rung-bar) { background: var(--bs-danger); }
  .manuale-corpo :global(.rung-2 .rung-bar) { background: var(--bs-primary); }
  .manuale-corpo :global(.rung-3 .rung-bar) { background: var(--bs-success); }
  .manuale-corpo :global(.rung-4 .rung-bar) { background: var(--bs-tertiary-color); }

  .manuale-corpo :global(.rung-head) {
    display: flex;
    align-items: baseline;
    gap: .5rem;
    flex-wrap: wrap;
  }

  .manuale-corpo :global(.rung-name) {
    font-weight: 600;
  }

  .manuale-corpo :global(.rung-where) {
    font-family: var(--bs-font-monospace);
    font-size: .78rem;
    color: var(--bs-secondary-color);
  }

  .manuale-corpo :global(.rung-body p) {
    margin: .3rem 0 0;
  }

  /* --- Diagrammi di flusso ------------------------------------------ */

  .manuale-corpo :global(.flow) {
    display: flex;
    align-items: stretch;
    flex-wrap: wrap;
    gap: .5rem;
    margin: 1.25rem 0;
  }

  .manuale-corpo :global(.node) {
    flex: 1 1 8rem;
    padding: .6rem .75rem;
    border: 1px solid var(--bs-border-color);
    border-radius: var(--bs-border-radius);
    background: var(--bs-body-bg);
  }

  .manuale-corpo :global(.node-accent) {
    border-color: var(--bs-primary-border-subtle);
    background: var(--bs-primary-bg-subtle);
  }

  .manuale-corpo :global(.node-label) {
    display: block;
    font-weight: 600;
    font-size: .9rem;
  }

  .manuale-corpo :global(.node-note) {
    display: block;
    font-size: .8rem;
    color: var(--bs-secondary-color);
  }

  .manuale-corpo :global(.arrow) {
    align-self: center;
    color: var(--bs-tertiary-color);
  }

  /* --- Tabelle ------------------------------------------------------ */

  .manuale-corpo :global(.tw) {
    overflow-x: auto;
    margin: 1.25rem 0 1.75rem;
    border: 1px solid var(--bs-border-color);
    border-radius: var(--bs-border-radius);
  }

  .manuale-corpo :global(table) {
    width: 100%;
    margin: 0;
    border-collapse: collapse;
    font-size: .9rem;
  }

  .manuale-corpo :global(th),
  .manuale-corpo :global(td) {
    padding: .45rem .7rem;
    text-align: left;
    vertical-align: top;
    border-bottom: 1px solid var(--bs-border-color);
  }

  .manuale-corpo :global(thead th) {
    background: var(--bs-secondary-bg);
    font-weight: 600;
    white-space: nowrap;
  }

  .manuale-corpo :global(tbody tr:last-child td) {
    border-bottom: none;
  }

  .manuale-corpo :global(.col-role) {
    white-space: nowrap;
    width: 1%;
  }

  /* --- Riquadri di avvertenza --------------------------------------- */

  .manuale-corpo :global(.note) {
    display: flex;
    gap: .75rem;
    margin: 1.25rem 0;
    padding: .75rem .9rem;
    border: 1px solid var(--bs-border-color);
    border-radius: var(--bs-border-radius);
    background: var(--bs-secondary-bg);
  }

  .manuale-corpo :global(.note-bar) {
    flex: 0 0 3px;
    border-radius: 2px;
    background: var(--bs-secondary-color);
  }

  .manuale-corpo :global(.note-title) {
    display: block;
    font-weight: 600;
    font-size: .875rem;
    margin-bottom: .2rem;
  }

  .manuale-corpo :global(.note-body p) {
    margin: 0;
  }

  .manuale-corpo :global(.note-body p + p) {
    margin-top: .5rem;
  }

  .manuale-corpo :global(.note-info) {
    background: var(--bs-info-bg-subtle);
    border-color: var(--bs-info-border-subtle);
  }

  .manuale-corpo :global(.note-info .note-bar) { background: var(--bs-info); }

  .manuale-corpo :global(.note-warn) {
    background: var(--bs-warning-bg-subtle);
    border-color: var(--bs-warning-border-subtle);
  }

  .manuale-corpo :global(.note-warn .note-bar) { background: var(--bs-warning); }

  .manuale-corpo :global(.note-crit) {
    background: var(--bs-danger-bg-subtle);
    border-color: var(--bs-danger-border-subtle);
  }

  .manuale-corpo :global(.note-crit .note-bar) { background: var(--bs-danger); }

  /* --- Glossari ------------------------------------------------------ */

  .manuale-corpo :global(.terms) {
    margin: 1rem 0;
  }

  .manuale-corpo :global(.term) {
    margin: 0 0 .75rem;
  }

  .manuale-corpo :global(.term dt) {
    font-weight: 600;
    font-size: .9rem;
  }

  .manuale-corpo :global(.term dd) {
    margin: .15rem 0 0;
    color: var(--bs-secondary-color);
  }

  /* --- Legenda dei colori di cella ----------------------------------- */

  .manuale-corpo :global(.swatches) {
    list-style: none;
    padding: 0;
    margin: 1rem 0;
  }

  .manuale-corpo :global(.swatches li) {
    display: flex;
    gap: .6rem;
    margin-bottom: .5rem;
  }

  .manuale-corpo :global(.sw) {
    flex: 0 0 auto;
    width: 14px;
    height: 14px;
    border-radius: 2px;
    margin-top: .22rem;
    border: 1px solid var(--bs-border-color);
  }

  .manuale-corpo :global(.sw-free)  { background: var(--bs-secondary-bg); }
  .manuale-corpo :global(.sw-match) { background: var(--bs-success); }
  .manuale-corpo :global(.sw-mis)   { background: var(--bs-warning); }
  .manuale-corpo :global(.sw-forc)  { background: var(--bs-danger); }
  .manuale-corpo :global(.sw-ns)    { background: var(--bs-primary); }
  .manuale-corpo :global(.sw-nr)    { background: var(--bs-primary-bg-subtle); }

  .manuale-corpo :global(.sw-empty) {
    background: transparent;
    border-style: dashed;
  }

  .manuale-corpo :global(.sw-name) {
    font-weight: 600;
    font-size: .875rem;
  }

  .manuale-corpo :global(.sw-desc) {
    color: var(--bs-secondary-color);
    font-size: .875rem;
  }
</style>
