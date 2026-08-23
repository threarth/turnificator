<!--
  VincoliSolver — Gestione vincoli solver (globali + per utente).

  Pattern edit: click-to-edit per-riga (come EditableTable / regole conflitto).
  Per-utente: copia-on-edit, salva con pulsante OK, annulla ripristina originale.

  Props:
    - adminApi         : object — API admin
    - flagTurno        : Array — lista flag turno
    - tipiQualitativo  : Array — lista tipi qualitativi
    - initGlobali      : Array — vincoli globali gia' caricati
    - initSolver       : Array — vincoli solver gia' caricati
    - onmsg            : (text, ok) => void — callback messaggi
-->
<script>
  import DeleteButton from './DeleteButton.svelte';

  let {
    adminApi,
    flagTurno = [],
    tipiQualitativo = [],
    initGlobali = [],
    initSolver = [],
    onmsg,
  } = $props();

  // Stato interno
  let vincoliGlobali = $state(initGlobali);
  let vincoliSolver = $state(initSolver);
  let solverUtentiRiepilogo = $state([]);

  // Edit state main tables (per-row, come editingRegola in admin)
  let editingGlobaleIdx = $state(null);     // indice riga in editing
  let editingGlobale = $state(null);        // copia oggetto in editing
  let editingSolverIdx = $state(null);
  let editingSolver = $state(null);

  // Espansione utente + copia-on-edit
  let vincoliUtenteId = $state(null);
  let vincoliUtenteOriginal = $state(null);      // snapshot originali per annulla
  let editVincoliUtente = $state([]);            // copia editabile
  let editGiorniEsclusi = $state([]);            // copia editabile
  let editVincoliSolverUtente = $state([]);      // copia editabile

  // Sync props → state quando cambiano dall'esterno
  $effect(() => { vincoliGlobali = initGlobali; });
  $effect(() => { vincoliSolver = initSolver; });

  // Carica riepilogo utenti al mount
  $effect(() => { caricaRiepilogoUtenti(); });

  // ─────────────────────────────────────────────────────────────
  // VINCOLI GLOBALI — click-to-edit per riga
  // ─────────────────────────────────────────────────────────────
  function startEditGlobale(idx) {
    editingGlobaleIdx = idx;
    editingGlobale = { ...vincoliGlobali[idx] };
  }
  function cancelEditGlobale() {
    editingGlobaleIdx = null;
    editingGlobale = null;
  }
  async function salvaEditGlobale() {
    if (editingGlobaleIdx == null) return;
    vincoliGlobali[editingGlobaleIdx] = { ...editingGlobale };
    vincoliGlobali = vincoliGlobali;
    const r = await adminApi.setVincoliGlobali(vincoliGlobali);
    if (r.ok) onmsg('Vincoli globali salvati.', true);
    else onmsg(r.errore, false);
    editingGlobaleIdx = null;
    editingGlobale = null;
  }

  // ─────────────────────────────────────────────────────────────
  // VINCOLI SOLVER (limiti flag/qualitativo) — click-to-edit per riga
  // ─────────────────────────────────────────────────────────────
  function startEditSolver(idx) {
    editingSolverIdx = idx;
    editingSolver = { ...vincoliSolver[idx] };
  }
  function cancelEditSolver() {
    // Se e' una riga appena aggiunta (senza id e senza ref_id), rimuovila
    if (editingSolverIdx != null) {
      const row = vincoliSolver[editingSolverIdx];
      if (row && !row.id && row.ref_id == null) {
        vincoliSolver = vincoliSolver.filter((_, i) => i !== editingSolverIdx);
      }
    }
    editingSolverIdx = null;
    editingSolver = null;
  }
  async function salvaEditSolver() {
    if (editingSolverIdx == null) return;
    vincoliSolver[editingSolverIdx] = { ...editingSolver };
    vincoliSolver = vincoliSolver;
    const r = await adminApi.setVincoliSolver(vincoliSolver);
    if (r.ok) onmsg('Limiti solver salvati.', true);
    else onmsg(r.errore, false);
    editingSolverIdx = null;
    editingSolver = null;
  }
  function addVincoloSolver(tipo) {
    vincoliSolver = [...vincoliSolver, { tipo, ref_id: null, max_n: 0, is_active: 1, descrizione: '' }];
    startEditSolver(vincoliSolver.length - 1);
  }
  async function removeVincoloSolver(idx) {
    const v = vincoliSolver[idx];
    if (v.id) await adminApi.delVincoloSolver(v.id);
    vincoliSolver = vincoliSolver.filter((_, i) => i !== idx);
    const r = await adminApi.setVincoliSolver(vincoliSolver);
    if (r.ok) onmsg('Limite rimosso.', true);
    else onmsg(r.errore, false);
  }

  // ─────────────────────────────────────────────────────────────
  // RIEPILOGO UTENTI
  // ─────────────────────────────────────────────────────────────
  async function caricaRiepilogoUtenti() {
    try {
      const r = await adminApi.getSolverUtentiRiepilogo();
      solverUtentiRiepilogo = r.utenti ?? [];
    } catch { solverUtentiRiepilogo = []; }
  }

  // ─────────────────────────────────────────────────────────────
  // ESPANSIONE UTENTE — copia-on-edit
  // ─────────────────────────────────────────────────────────────
  async function espandiUtente(uid) {
    if (vincoliUtenteId === uid) {
      // Click sulla stessa riga: annulla e chiudi
      chiudiUtente();
      return;
    }
    vincoliUtenteId = uid;
    await caricaVincoliUtente();
  }

  function chiudiUtente() {
    vincoliUtenteId = null;
    vincoliUtenteOriginal = null;
    editVincoliUtente = [];
    editGiorniEsclusi = [];
    editVincoliSolverUtente = [];
  }

  async function caricaVincoliUtente() {
    if (!vincoliUtenteId) { chiudiUtente(); return; }
    const [rv, rg, rvs] = await Promise.all([
      adminApi.getVincoliUtente(vincoliUtenteId),
      adminApi.getGiorniEsclusi(vincoliUtenteId),
      adminApi.getVincoliSolverUtente(vincoliUtenteId),
    ]);
    const origVincoli = rv.vincoli ?? [];
    const origGiorni = rg.giorni_esclusi ?? [];
    const origSolver = rvs.vincoli ?? [];
    // Snapshot originali per annulla
    vincoliUtenteOriginal = {
      vincoli: origVincoli.map(v => ({ ...v })),
      giorni: [...origGiorni],
      solver: origSolver.map(v => ({ ...v })),
    };
    // Copie editabili
    editVincoliUtente = origVincoli.map(v => ({ ...v }));
    editGiorniEsclusi = [...origGiorni];
    editVincoliSolverUtente = origSolver.map(v => ({ ...v }));
  }

  function _aggiornaRiepilogoUtente(vincoli, giorni, solver) {
    const idx = solverUtentiRiepilogo.findIndex(u => u.id === vincoliUtenteId);
    if (idx >= 0) {
      solverUtentiRiepilogo[idx] = {
        ...solverUtentiRiepilogo[idx],
        vincoli: vincoli.filter(v => v.chiave && v.valore),
        giorni_esclusi: [...giorni],
        vincoli_solver: solver.filter(v => v.ref_id).map(v => ({
          ...v, ref_nome: v.ref_nome || _refNome(v.tipo, v.ref_id)
        })),
      };
      solverUtentiRiepilogo = solverUtentiRiepilogo;
    }
  }

  function _refNome(tipo, refId) {
    if (tipo === 'flag') return flagTurno.find(f => f.id === refId)?.nome || '?';
    return tipiQualitativo.find(t => t.id === refId)?.nome || '?';
  }

  // ── Vincoli override utente ──
  function addVincoloUtente() {
    editVincoliUtente = [...editVincoliUtente, { chiave: '', valore: '', note: '' }];
  }
  function removeVincoloUtenteLocal(idx) {
    editVincoliUtente = editVincoliUtente.filter((_, i) => i !== idx);
  }

  // ── Vincoli solver utente ──
  function addVincoloSolverUtente(tipo) {
    editVincoliSolverUtente = [...editVincoliSolverUtente, { tipo, ref_id: null, max_n: 0, note: '' }];
  }
  function removeVincoloSolverUtenteLocal(idx) {
    editVincoliSolverUtente = editVincoliSolverUtente.filter((_, i) => i !== idx);
  }

  // ── Giorni esclusi ──
  // 0=Lun..6=Dom (Python calendar.weekday convention)
  const GIORNI_LABELS = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'];

  function toggleGiornoEscluso(dow) {
    if (editGiorniEsclusi.includes(dow)) {
      editGiorniEsclusi = editGiorniEsclusi.filter(d => d !== dow);
    } else {
      editGiorniEsclusi = [...editGiorniEsclusi, dow];
    }
  }

  // ── Salva tutto (vincoli + giorni + solver utente) ──
  async function salvaUtente() {
    if (!vincoliUtenteId) return;
    const [rv, rg, rvs] = await Promise.all([
      adminApi.setVincoliUtente(vincoliUtenteId, editVincoliUtente),
      adminApi.setGiorniEsclusi(vincoliUtenteId, editGiorniEsclusi),
      adminApi.setVincoliSolverUtente(vincoliUtenteId, editVincoliSolverUtente),
    ]);
    const okTutti = rv.ok && rg.ok && rvs.ok;
    if (okTutti) {
      onmsg('Vincoli utente salvati.', true);
      _aggiornaRiepilogoUtente(editVincoliUtente, editGiorniEsclusi, editVincoliSolverUtente);
      chiudiUtente();
    } else {
      const err = rv.errore || rg.errore || rvs.errore || 'Errore salvataggio.';
      onmsg(err, false);
    }
  }

  function annullaUtente() {
    chiudiUtente();
  }

  // ── Click-outside: chiudi e annulla ──
  let vincoliRoot = $state(null);
  let globaliRoot = $state(null);
  let solverRoot = $state(null);

  function handleWindowMousedown(e) {
    // Utente espanso: click fuori → annulla
    if (vincoliUtenteId && vincoliRoot && !vincoliRoot.contains(e.target)) {
      chiudiUtente();
    }
    // Edit vincoli globali: click fuori → annulla
    if (editingGlobaleIdx != null && globaliRoot && !globaliRoot.contains(e.target)) {
      cancelEditGlobale();
    }
    // Edit vincoli solver: click fuori → annulla
    if (editingSolverIdx != null && solverRoot && !solverRoot.contains(e.target)) {
      cancelEditSolver();
    }
  }

  function handleKeyEdit(e, saveFn, cancelFn) {
    if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') saveFn();
    if (e.key === 'Escape') cancelFn();
  }
</script>

<svelte:window onmousedown={handleWindowMousedown} />

<!-- ═══════════════ VINCOLI GLOBALI ═══════════════ -->
<p class="small text-muted mb-2">Vincoli globali applicati dal solver automatico durante l'auto-riempimento turni.</p>
<div bind:this={globaliRoot}>
<table class="table table-sm table-hover mb-3" style="font-size:.85rem">
  <thead>
    <tr>
      <th>Vincolo</th>
      <th style="width:100px">Valore</th>
      <th>Descrizione</th>
      <th style="width:60px">Attivo</th>
      <th style="width:70px"></th>
    </tr>
  </thead>
  <tbody>
  {#each vincoliGlobali as v, i (v.chiave)}
    {#if editingGlobaleIdx === i}
      <!-- Edit mode -->
      <tr class="table-warning" onkeydown={e => handleKeyEdit(e, salvaEditGlobale, cancelEditGlobale)}>
        <td class="font-monospace small">{v.chiave}</td>
        <td><input class="form-control form-control-sm" type="number" bind:value={editingGlobale.valore} /></td>
        <td class="small text-muted">{v.descrizione || ''}{v.chiave === 'max_n_turni_mese' ? ' (offset)' : ''}</td>
        <td><input type="checkbox" checked={!!editingGlobale.is_active}
                   onchange={() => editingGlobale.is_active = editingGlobale.is_active ? 0 : 1} /></td>
        <td style="white-space:nowrap">
          <button class="btn btn-success btn-sm py-0" onclick={salvaEditGlobale}><i class="bi bi-check-lg"></i></button>
          <button class="btn btn-secondary btn-sm py-0" onclick={cancelEditGlobale}><i class="bi bi-x"></i></button>
        </td>
      </tr>
    {:else}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <tr class="editable-row" style="cursor:pointer" onclick={() => startEditGlobale(i)}>
        <td class="font-monospace small">{v.chiave}</td>
        <td>{v.valore}</td>
        <td class="small text-muted">{v.descrizione || ''}{v.chiave === 'max_n_turni_mese' ? ' (offset)' : ''}</td>
        <td>{v.is_active ? '✓' : '—'}</td>
        <td></td>
      </tr>
    {/if}
  {/each}
  </tbody>
</table>
</div>

<!-- ═══════════════ LIMITI MENSILI (flag + qualitativo) ═══════════════ -->
<div bind:this={solverRoot}>

<!-- Limiti mensili max per caratteristica temporale -->
<h6 class="mt-3 mb-2" style="font-size:.85rem">
  Limiti mensili max per caratteristica temporale
  <button class="btn btn-sm btn-outline-primary ms-2" onclick={() => addVincoloSolver('flag')}>
    <i class="bi bi-plus me-1"></i>Aggiungi
  </button>
</h6>
{#if vincoliSolver.filter(v => v.tipo === 'flag').length}
  <table class="table table-sm table-hover mb-2" style="font-size:.85rem">
    <thead><tr><th>Flag</th><th style="width:80px">Max N</th><th style="width:50px">Attivo</th><th style="width:80px"></th></tr></thead>
    <tbody>
    {#each vincoliSolver as vs, i}
      {#if vs.tipo === 'flag'}
        {#if editingSolverIdx === i}
          <tr class="table-warning" onkeydown={e => handleKeyEdit(e, salvaEditSolver, cancelEditSolver)}>
            <td>
              <select class="form-select form-select-sm" bind:value={editingSolver.ref_id}>
                <option value={null}>— seleziona flag —</option>
                {#each flagTurno.filter(f => f.mostra_in_struttura) as f}
                  <option value={f.id}>{f.nome}{f.parent_nome ? ` (${f.parent_nome})` : ''}</option>
                {/each}
              </select>
            </td>
            <td><input class="form-control form-control-sm" type="number" bind:value={editingSolver.max_n} /></td>
            <td><input type="checkbox" checked={!!editingSolver.is_active}
                       onchange={() => editingSolver.is_active = editingSolver.is_active ? 0 : 1} /></td>
            <td style="white-space:nowrap">
              <button class="btn btn-success btn-sm py-0" onclick={salvaEditSolver}><i class="bi bi-check-lg"></i></button>
              <button class="btn btn-secondary btn-sm py-0" onclick={cancelEditSolver}><i class="bi bi-x"></i></button>
            </td>
          </tr>
        {:else}
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
          <tr class="editable-row" style="cursor:pointer" onclick={() => startEditSolver(i)}>
            <td>{_refNome('flag', vs.ref_id)}</td>
            <td>{vs.max_n}</td>
            <td>{vs.is_active ? '✓' : '—'}</td>
            <td onclick={e => e.stopPropagation()}>
              <DeleteButton ondelete={() => removeVincoloSolver(i)} />
            </td>
          </tr>
        {/if}
      {/if}
    {/each}
    </tbody>
  </table>
{:else}
  <div class="text-muted small mb-2">Nessun limite flag configurato.</div>
{/if}

<!-- Limiti mensili max per caratteristica qualitativa -->
<h6 class="mt-3 mb-2" style="font-size:.85rem">
  Limiti mensili max per caratteristica qualitativa
  <button class="btn btn-sm btn-outline-primary ms-2" onclick={() => addVincoloSolver('qualitativo')}>
    <i class="bi bi-plus me-1"></i>Aggiungi
  </button>
</h6>
{#if vincoliSolver.filter(v => v.tipo === 'qualitativo').length}
  <table class="table table-sm table-hover mb-3" style="font-size:.85rem">
    <thead><tr><th>Tipo</th><th style="width:80px">Max N</th><th style="width:50px">Attivo</th><th style="width:80px"></th></tr></thead>
    <tbody>
    {#each vincoliSolver as vs, i}
      {#if vs.tipo === 'qualitativo'}
        {#if editingSolverIdx === i}
          <tr class="table-warning" onkeydown={e => handleKeyEdit(e, salvaEditSolver, cancelEditSolver)}>
            <td>
              <select class="form-select form-select-sm" bind:value={editingSolver.ref_id}>
                <option value={null}>— seleziona tipo —</option>
                {#each tipiQualitativo as tq}
                  <option value={tq.id}>{tq.nome}</option>
                {/each}
              </select>
            </td>
            <td><input class="form-control form-control-sm" type="number" bind:value={editingSolver.max_n} /></td>
            <td><input type="checkbox" checked={!!editingSolver.is_active}
                       onchange={() => editingSolver.is_active = editingSolver.is_active ? 0 : 1} /></td>
            <td style="white-space:nowrap">
              <button class="btn btn-success btn-sm py-0" onclick={salvaEditSolver}><i class="bi bi-check-lg"></i></button>
              <button class="btn btn-secondary btn-sm py-0" onclick={cancelEditSolver}><i class="bi bi-x"></i></button>
            </td>
          </tr>
        {:else}
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
          <tr class="editable-row" style="cursor:pointer" onclick={() => startEditSolver(i)}>
            <td>{_refNome('qualitativo', vs.ref_id)}</td>
            <td>{vs.max_n}</td>
            <td>{vs.is_active ? '✓' : '—'}</td>
            <td onclick={e => e.stopPropagation()}>
              <DeleteButton ondelete={() => removeVincoloSolver(i)} />
            </td>
          </tr>
        {/if}
      {/if}
    {/each}
    </tbody>
  </table>
{:else}
  <div class="text-muted small mb-2">Nessun limite tipo qualitativo configurato.</div>
{/if}

</div>

<hr class="my-3" />

<!-- ═══════════════ VINCOLI PER UTENTE ═══════════════ -->
<h6 class="mt-3 mb-2" style="font-size:.85rem">Vincoli per utente</h6>
<div class="small text-muted mb-2">Clicca su un utente per entrare in edit mode. Salva con <i class="bi bi-check-lg"></i> o annulla cliccando fuori.</div>
{#if solverUtentiRiepilogo.length === 0}
  <div class="text-muted small fst-italic">Nessun utente basic attivo trovato.</div>
{:else}
  <div style="max-height:500px;overflow-y:auto" bind:this={vincoliRoot}>
  <table class="table table-sm table-hover mb-0" style="font-size:.8rem">
    <thead class="table-light"><tr>
      <th>Utente</th><th>Vincoli override</th><th>Limiti flag/tipo</th><th>Giorni esclusi</th>
    </tr></thead>
    <tbody>
    {#each solverUtentiRiepilogo as u}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <tr class="{vincoliUtenteId === u.id ? 'table-warning' : 'editable-row'}" style="cursor:pointer"
          onclick={() => espandiUtente(u.id)}>
        <td class="fw-semibold">{u.sigla || u.username}</td>
        <td>
          {#if u.vincoli?.length}
            {#each u.vincoli as v}
              <span class="badge bg-info text-dark me-1 mb-1">{v.chiave}={v.valore}</span>
            {/each}
          {:else}<span class="text-muted fst-italic">—</span>{/if}
        </td>
        <td>
          {#if u.vincoli_solver?.length}
            {#each u.vincoli_solver as vs}
              <span class="badge me-1 mb-1" class:bg-warning={vs.tipo==='flag'} class:bg-primary={vs.tipo==='qualitativo'}
                    class:text-dark={vs.tipo==='flag'} title={vs.note||''}>{vs.ref_nome}&le;{vs.max_n}</span>
            {/each}
          {:else}<span class="text-muted fst-italic">—</span>{/if}
        </td>
        <td>
          {#if u.giorni_esclusi?.length}
            {#each u.giorni_esclusi as dow}
              <span class="badge bg-danger me-1 mb-1">{GIORNI_LABELS[dow]}</span>
            {/each}
          {:else}<span class="text-muted fst-italic">—</span>{/if}
        </td>
      </tr>
      {#if vincoliUtenteId === u.id}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <tr><td colspan="4" class="bg-light p-3" onclick={e => e.stopPropagation()}>

          <!-- Vincoli override globali -->
          <div class="d-flex align-items-center gap-2 mb-1">
            <strong class="small">Vincoli override</strong>
            <button class="btn btn-sm btn-outline-primary py-0 px-1" style="font-size:.75rem" onclick={addVincoloUtente}>
              <i class="bi bi-plus"></i>
            </button>
          </div>
          {#if editVincoliUtente.length}
            <table class="table table-sm mb-2" style="font-size:.8rem">
              <thead><tr><th>Chiave</th><th>Valore</th><th>Note</th><th></th></tr></thead>
              <tbody>
              {#each editVincoliUtente as vu, i}
                <tr>
                  <td>
                    <select class="form-select form-select-sm" style="font-size:.8rem" bind:value={vu.chiave}>
                      <option value="">—</option>
                      {#each vincoliGlobali as vg}<option value={vg.chiave}>{vg.chiave}</option>{/each}
                    </select>
                  </td>
                  <td><input class="form-control form-control-sm" type="number" bind:value={vu.valore} /></td>
                  <td><input class="form-control form-control-sm" bind:value={vu.note} /></td>
                  <td><DeleteButton ondelete={() => removeVincoloUtenteLocal(i)} /></td>
                </tr>
              {/each}
              </tbody>
            </table>
          {:else}<div class="text-muted small mb-2">Nessun override.</div>{/if}

          <!-- Limiti flag/tipo -->
          <div class="d-flex align-items-center gap-2 mb-1">
            <strong class="small">Limiti flag/tipo</strong>
            <button class="btn btn-sm btn-outline-primary py-0 px-1" style="font-size:.75rem" onclick={() => addVincoloSolverUtente('flag')}>
              <i class="bi bi-plus"></i> Flag
            </button>
            <button class="btn btn-sm btn-outline-primary py-0 px-1" style="font-size:.75rem" onclick={() => addVincoloSolverUtente('qualitativo')}>
              <i class="bi bi-plus"></i> Tipo
            </button>
          </div>
          {#if editVincoliSolverUtente.length}
            <table class="table table-sm mb-2" style="font-size:.8rem">
              <thead><tr><th>Tipo</th><th>Rif.</th><th style="width:70px">Max N</th><th>Note</th><th></th></tr></thead>
              <tbody>
              {#each editVincoliSolverUtente as vsu, i}
                <tr>
                  <td class="small">{vsu.tipo === 'flag' ? 'Flag' : 'Qual.'}</td>
                  <td>
                    {#if vsu.tipo === 'flag'}
                      <select class="form-select form-select-sm" style="font-size:.8rem" bind:value={vsu.ref_id}>
                        <option value={null}>—</option>
                        {#each flagTurno.filter(f => f.mostra_in_struttura) as f}<option value={f.id}>{f.nome}</option>{/each}
                      </select>
                    {:else}
                      <select class="form-select form-select-sm" style="font-size:.8rem" bind:value={vsu.ref_id}>
                        <option value={null}>—</option>
                        {#each tipiQualitativo as tq}<option value={tq.id}>{tq.nome}</option>{/each}
                      </select>
                    {/if}
                  </td>
                  <td><input class="form-control form-control-sm" type="number" bind:value={vsu.max_n} /></td>
                  <td><input class="form-control form-control-sm" bind:value={vsu.note} placeholder="Note" /></td>
                  <td><DeleteButton ondelete={() => removeVincoloSolverUtenteLocal(i)} /></td>
                </tr>
              {/each}
              </tbody>
            </table>
          {:else}<div class="text-muted small mb-2">Nessun limite.</div>{/if}

          <!-- Giorni esclusi -->
          <div class="d-flex align-items-center gap-2 mb-1">
            <strong class="small">Giorni esclusi (settimana)</strong>
          </div>
          <div class="d-flex gap-2 flex-wrap mb-2" style="font-size:.8rem">
            {#each [0, 1, 2, 3, 4, 5, 6] as dow}
              <label class="form-check-label d-flex align-items-center gap-1" style="cursor:pointer">
                <input type="checkbox" class="form-check-input"
                       checked={editGiorniEsclusi.includes(dow)}
                       onchange={() => toggleGiornoEscluso(dow)} />
                {GIORNI_LABELS[dow]}
              </label>
            {/each}
          </div>

          <!-- Salva / Annulla tutto -->
          <div class="d-flex gap-2 mt-2 border-top pt-2">
            <button class="btn btn-success btn-sm" onclick={salvaUtente}>
              <i class="bi bi-check-lg me-1"></i>Salva tutto
            </button>
            <button class="btn btn-secondary btn-sm" onclick={annullaUtente}>
              <i class="bi bi-x me-1"></i>Annulla
            </button>
          </div>

        </td></tr>
      {/if}
    {/each}
    </tbody>
  </table>
  </div>
{/if}
