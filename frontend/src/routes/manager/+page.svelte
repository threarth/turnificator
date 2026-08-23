<script>
  import { onMount, onDestroy } from 'svelte';
  import { managerApi, adminApi, exportApi } from '$lib/api.js';
  import { getToken } from '$lib/auth.js';
  import {
    connectSocket, disconnectSocket, joinCalendario, leaveCalendario,
    onAssegnazioneChanged, onUndoRedo, onSolverCompleted, removeAllListeners, isConnected, onStatusChange,
    onDesiderataChanged, onPrivacyChanged
  } from '$lib/socket.js';
  import { user as userStore } from '$lib/auth.js';
  import StyleContextMenu from '$lib/StyleContextMenu.svelte';
  import CellEditor from '$lib/CellEditor.svelte';
  import { clickOutside } from '$lib/admin/actions.js';
  import AppearanceEditor, { APPEARANCE_DEFAULT } from '$lib/admin/AppearanceEditor.svelte';
  import DesiderataInserimento from '$lib/DesiderataInserimento.svelte';

  // ── Stato principale ──────────────────────────────────────────
  let calendari  = $state([]);
  let calId      = $state(null);
  let struttura  = $state(null);
  let loading    = $state(false);

  // Lista piatta di tutti gli utenti basic (id → sigla).
  // L'ordine e' quello definito dalla modalità desiderata (manuale /
  // alfabetico_globale / alfabetico_intragruppo), ripreso dalla pagina basic
  // per coerenza tra viste working, originali e in corso di inserimento.
  let utenti     = $state([]);   // [ { id, sigla, sovragruppo_id, ordine_desiderata, ... } ]
  let modalitaDesOrd = $state('alfabetico_intragruppo');
  let sovragruppiOrd = $state([]);  // [{id, ordine, ordine_desiderata}]
  let riordinoDesOn  = $state(false);  // toggle chevron riordino SG/utente (solo modalita='manuale')

  // Stato locale assegnazioni: chiave `turno_id-giorno` → { user_id, conflitti }
  // Aggiornato ottimisticamente, poi confermato/rollback dal server
  let localAss   = $state({});

  // Stato sincronizzazione per cella: '' | 'saving' | 'ok' | 'err'
  let syncStatus = $state({});

  // Regole conflitto (caricate all'avvio)
  let regoleConflitto = $state([]);

  // History
  let history    = $state({ can_undo: false, can_redo: false });

  // Toast globale
  let toast      = $state('');
  let toastErr   = $state(false);

  // Vista attiva
  let vista = $state('griglia');  // 'griglia' | 'working' | 'originali' | 'inserisci'

  // Workflow CHIUSO/EFFETTIVO
  let effettivoInfo = $state(null);  // { id, stato, chiuso_il, ha_modifiche } o null
  let calTab = $state('principale');  // 'principale' | 'effettivo'

  let calStato = $derived(struttura?.calendario?.stato ?? 'APERTO');
  let calTipo = $derived(struttura?.calendario?.tipo ?? 'programmato');
  let isReadOnly = $derived(calStato !== 'APERTO');
  let isEffettivo = $derived(calTipo === 'effettivo');

  // Griglia trasposta (giorni per riga, turni per colonna)
  let trasposto = $state(false);
  function toggleTrasposto() {
    trasposto = !trasposto;
    localStorage.setItem('grigliaTrasposta', trasposto ? '1' : '0');
  }

  // Trasposizione griglia desiderata (WD + Originali); chiave separata condivisa con /basic
  let desTrasposto = $state(false);
  if (typeof localStorage !== 'undefined') {
    desTrasposto = localStorage.getItem('desiderataTrasposta') === '1';
  }
  function toggleDesTrasposto() {
    desTrasposto = !desTrasposto;
    try { localStorage.setItem('desiderataTrasposta', desTrasposto ? '1' : '0'); } catch {}
  }

  // Rimappa direzione freccia in base all'orientamento della griglia desiderata:
  // default (utenti-righe × giorni-colonne) → left/right = giorni, up/down = utenti
  // trasposto (giorni-righe × utenti-colonne) → up/down = giorni, left/right = utenti
  function _remapDesDir(dir) {
    if (!desTrasposto) return dir;
    if (dir === 'right') return 'down';
    if (dir === 'left')  return 'up';
    if (dir === 'down')  return 'right';
    if (dir === 'up')    return 'left';
    return dir;
  }

  // Dati desiderata (caricati insieme alla struttura)
  let wdFull  = $state([]);   // working_desiderata arricchiti
  let desFull = $state([]);   // desiderata originali arricchiti
  let wdHistory = $state({ can_undo: false, can_redo: false });
  let tipi    = $state([]);   // tipi richiesta (per dropdown WD)

  // ── Solver ─────────────────────────────────────────────────
  let solverOpen    = $state(false);
  let solverOpts    = $state({ solo_vuote: true, solo_indispensabili: false, fonte_desiderata: 'working' });
  let solverResult  = $state(null);
  let solverLoading = $state(false);
  let solverMultiStart = $state(0);
  let solverTopK       = $state(3);
  let solverNRuns      = $state(10);
  let solverCriteri    = $state([]);  // criteri ordinamento: [{tipo, flag_nome?, valori?}]
  let solverEditRegola   = $state(null);          // regola in editing inline
  let solverRegoleDirty  = $state(false);         // snapshot regole modificato
  let solverShowAddRegola = $state(false);        // mostra form nuova regola
  let solverNuovaRegola  = $state(null);          // dati nuova regola
  let solverUtenti  = $state([]);               // riepilogo utenti con vincoli/esclusioni
  let solverTab     = $state('opzioni');         // 'opzioni' | 'regole' | 'vincoli' | 'utenti' | ...
  let solverEditUid     = $state(null);          // utente espanso per editing
  let solverEditVincoli = $state([]);            // vincoli override in editing
  let solverEditVSolver = $state([]);            // vincoli solver in editing
  let solverEditEscl    = $state([]);            // esclusioni in editing
  let solverFlagTurno   = $state([]);            // flag per dropdown
  let solverTipiQual    = $state([]);            // tipi qualitativo per dropdown
  let solverVincoliGlob = $state([]);            // chiavi vincoli globali per dropdown
  let solverOrfani      = $state(null);          // orfani accesso manager
  // Config snapshot (vincoli snapshottati nel calendario)
  let configSnapshot       = $state({});            // intero config_snapshot
  let snapVincoliGlobali   = $state([]);            // vincoli globali dallo snapshot
  let snapVincoliSolver    = $state([]);            // vincoli solver dallo snapshot
  let snapVincoliDirty     = $state(false);         // flag modifiche vincoli snapshot
  let solverTurniSel    = $state([]);            // turni selezionati per solver (local_id)
  let solverTurniTutti  = $state(true);          // true = tutti i turni (non invia filtro)

  // Escludi turno — gestione snapshot esclusioni per-utente per-turno/gruppo/sg
  let etData          = $state([]);   // [{user_id, tipo, target_id}] da configSnapshot
  let etDirty         = $state(false);
  let etLoading       = $state(false);
  let etForm          = $state({ users: [], tipo: 'turno', target_id: null });
  let etUserDropOpen  = $state(false);  // dropdown utenti del form add
  let etEditIdx       = $state(null);   // indice riga in editing (null = nessuna)
  let etEditForm      = $state({ users: [], tipo: 'turno', target_id: null });
  let etEditDropOpen  = $state(false);  // dropdown utenti dell'edit row

  // Selezione turni per optimizer
  let optTurniSel    = $state([]);               // turni selezionati per optimizer (local_id)
  let optTurniTutti  = $state(true);             // true = tutti i turni

  // Helper: tutti i local_id accessibili
  function _turniAllLocalIds() {
    const ids = [];
    for (const sg of (struttura?.sovragruppi ?? []))
      for (const g of sg.gruppi)
        for (const t of g.turni)
          if (t.accessibile !== false) ids.push(t.local_id);
    return ids;
  }

  // Toggle functions per selezione turni (riutilizzabili)
  function _turniToggleSG(sel, sg) {
    const ids = sg.gruppi.flatMap(g => g.turni.filter(t => t.accessibile !== false).map(t => t.local_id));
    const allIn = ids.every(id => sel.includes(id));
    return allIn ? sel.filter(id => !ids.includes(id)) : [...sel, ...ids.filter(id => !sel.includes(id))];
  }
  function _turniToggleGruppo(sel, g) {
    const ids = g.turni.filter(t => t.accessibile !== false).map(t => t.local_id);
    const allIn = ids.every(id => sel.includes(id));
    return allIn ? sel.filter(id => !ids.includes(id)) : [...sel, ...ids.filter(id => !sel.includes(id))];
  }
  function _turniToggleTurno(sel, lid) {
    return sel.includes(lid) ? sel.filter(id => id !== lid) : [...sel, lid];
  }
  function _turniToggleTutti(sel) {
    const all = _turniAllLocalIds();
    return sel.length === all.length ? [] : [...all];
  }

  // ── Posti Fissi ───────────────────────────────────────────
  let pfOpen = $state(false);
  let pfData = $state([]);
  let pfLoading = $state(false);
  let pfResult = $state(null);
  let pfOpts = $state({ sovrascrivi: false, ignora_festivi: true, ignora_superfestivi: true, rispetta_desiderata: true });
  let pfEditId = $state(null);       // id del posto in modifica, 'new' per nuovo
  let pfForm = $state({ preset_turno_id: null, giorno_settimana: 0, nome: '', utenti: [] });
  const giorniSettimana = ['Lunedì','Martedì','Mercoledì','Giovedì','Venerdì','Sabato','Domenica'];

  async function pfApri() {
    pfOpen = true;
    pfResult = null;
    pfEditId = null;
    pfLoading = true;
    try {
      const presetId = struttura?.calendario?.preset_id;
      if (!presetId) { pfLoading = false; return; }
      const r = await managerApi.getPostiFissi(presetId);
      pfData = r.posti_fissi ?? [];
    } catch { pfData = []; }
    pfLoading = false;
  }

  function pfNuovo() {
    pfEditId = 'new';
    pfForm = { preset_turno_id: null, giorno_settimana: 0, nome: '', utenti: [] };
  }

  function pfModifica(pf) {
    pfEditId = pf.id;
    pfForm = {
      preset_turno_id: pf.preset_turno_id,
      giorno_settimana: pf.giorno_settimana,
      nome: pf.nome,
      utenti: pf.utenti.map(u => u.user_id),
    };
  }

  async function pfSalva() {
    const presetId = struttura?.calendario?.preset_id;
    if (!presetId) return;
    if (!pfForm.preset_turno_id || pfForm.utenti.length === 0) {
      showToast('Seleziona turno e almeno un utente.', true);
      return;
    }
    if (pfEditId === 'new') {
      const r = await managerApi.creaPostoFisso(presetId, pfForm);
      if (!r.ok) { showToast(r.errore, true); return; }
    } else {
      const r = await managerApi.aggiornaPostoFisso(pfEditId, pfForm);
      if (!r.ok) { showToast(r.errore, true); return; }
    }
    pfEditId = null;
    const r = await managerApi.getPostiFissi(presetId);
    pfData = r.posti_fissi ?? [];
  }

  async function pfElimina(id) {
    await managerApi.eliminaPostoFisso(id);
    const presetId = struttura?.calendario?.preset_id;
    const r = await managerApi.getPostiFissi(presetId);
    pfData = r.posti_fissi ?? [];
  }

  async function pfToggleActive(pf) {
    await managerApi.aggiornaPostoFisso(pf.id, { is_active: pf.is_active ? 0 : 1 });
    const presetId = struttura?.calendario?.preset_id;
    const r = await managerApi.getPostiFissi(presetId);
    pfData = r.posti_fissi ?? [];
  }

  async function pfApplica(ids = null) {
    pfLoading = true;
    const payload = { ...pfOpts };
    if (ids) {
      payload.posti_fissi_ids = ids;
    } else {
      // Applica solo quelli attivi (selezionati)
      payload.posti_fissi_ids = pfData.filter(p => p.is_active).map(p => p.id);
    }
    const r = await managerApi.applicaPostiFissi(calId, payload);
    pfLoading = false;
    if (r.ok) {
      pfResult = r;
      showToast(`Posti fissi: ${r.inseriti} inseriti, ${r.saltati} saltati`, false);
      // Ricarica griglia
      const rs = await managerApi.getStruttura(calId);
      if (rs.ok) {
        struttura = rs;
        initLocalAss(rs.assegnazioni ?? []);
      }
    } else {
      showToast(r.errore, true);
    }
  }

  function _pfTurniList() {
    // Elenco turni accessibili dal preset (flatten dalla struttura corrente)
    const list = [];
    for (const sg of (struttura?.sovragruppi ?? [])) {
      for (const g of sg.gruppi) {
        for (const t of g.turni) {
          if (t.accessibile !== false)
            list.push({ id: t.local_id, sigla: t.sigla, sg: sg.sigla, g: g.sigla });
        }
      }
    }
    return list;
  }

  function _pfToggleUtente(uid) {
    const idx = pfForm.utenti.indexOf(uid);
    if (idx >= 0) pfForm.utenti = pfForm.utenti.filter(u => u !== uid);
    else pfForm.utenti = [...pfForm.utenti, uid];
  }

  let azzeraOpen = $state(false);
  let azzeraSel = $state([]);   // turno_id selezionati (array)
  let azzeraLoading = $state(false);

  function _azAllIds() {
    const ids = [];
    for (const sg of (struttura?.sovragruppi ?? []))
      for (const g of sg.gruppi)
        for (const t of g.turni)
          if (t.accessibile !== false) ids.push(t.id);
    return ids;
  }

  function azzeraApri() {
    azzeraSel = _azAllIds();
    azzeraOpen = true;
  }

  function _azHas(id) { return azzeraSel.includes(id); }

  function _azzeraToggleSG(sg) {
    const ids = sg.gruppi.flatMap(g => g.turni.filter(t => t.accessibile !== false).map(t => t.id));
    const allIn = ids.every(id => azzeraSel.includes(id));
    if (allIn) {
      azzeraSel = azzeraSel.filter(id => !ids.includes(id));
    } else {
      azzeraSel = [...azzeraSel, ...ids.filter(id => !azzeraSel.includes(id))];
    }
  }

  function _azzeraToggleGruppo(g) {
    const ids = g.turni.filter(t => t.accessibile !== false).map(t => t.id);
    const allIn = ids.every(id => azzeraSel.includes(id));
    if (allIn) {
      azzeraSel = azzeraSel.filter(id => !ids.includes(id));
    } else {
      azzeraSel = [...azzeraSel, ...ids.filter(id => !azzeraSel.includes(id))];
    }
  }

  function _azzeraToggleTurno(tid) {
    if (azzeraSel.includes(tid)) {
      azzeraSel = azzeraSel.filter(id => id !== tid);
    } else {
      azzeraSel = [...azzeraSel, tid];
    }
  }

  function _azzeraToggleTutti() {
    const all = _azAllIds();
    azzeraSel = azzeraSel.length === all.length ? [] : [...all];
  }

  async function azzeraConferma() {
    if (azzeraSel.length === 0) return;
    azzeraLoading = true;
    const r = await managerApi.azzeraAssegnazioni(calId, { turni_ids: azzeraSel });
    azzeraLoading = false;
    if (r.ok) {
      showToast(r.messaggio, false);
      azzeraOpen = false;
      const rs = await managerApi.getStruttura(calId);
      if (rs.ok) {
        struttura = rs;
        initLocalAss(rs.assegnazioni ?? []);
      }
    } else {
      showToast(r.errore, true);
    }
  }

  function _solverPayload(dryRun) {
    const congelati = !!struttura?.calendario?.desiderata_congelati;
    const payload = {
      ...solverOpts,
      fonte_desiderata: congelati ? solverOpts.fonte_desiderata : 'originali',
      dry_run: dryRun,
    };
    if (solverMultiStart > 0) {
      payload.multi_start = solverNRuns;
      payload.top_k = solverTopK;
    }
    if (solverCriteri.length > 0) {
      payload.criteri_ordinamento = solverCriteri;
    }
    if (!solverTurniTutti && solverTurniSel.length > 0) {
      payload.turni_ids = solverTurniSel;
    }
    return payload;
  }

  async function solverApri() {
    solverOpen = true;
    solverResult = null;
    solverTab = 'opzioni';
    solverEditUid = null;
    solverTurniSel = _turniAllLocalIds();
    solverTurniTutti = true;
    solverOrfani = null;
    // Carica riepilogo utenti, riferimenti e esclusioni giorno
    try {
      const [rU, rF, rT, rV, rA, rE] = await Promise.all([
        adminApi.getSolverUtentiRiepilogo(),
        adminApi.getFlagTurno(),
        adminApi.getTipiQualitativo(),
        adminApi.getVincoliGlobali(),
        adminApi.getAccessoManager(),
        managerApi.getEsclusioni(calId),
      ]);
      solverUtenti = rU.utenti ?? [];
      solverFlagTurno = rF.flags ?? [];
      solverTipiQual = rT.tipi ?? [];
      solverVincoliGlob = rV.vincoli ?? [];
      solverOrfani = rA.orfani ?? null;
      esclusioni = rE.esclusioni ?? [];
    } catch { solverUtenti = []; }
    // Inizializza esclusioni turno dallo snapshot corrente
    etData         = [...(configSnapshot.esclusioni_turno ?? [])];
    etDirty        = false;
    etEditIdx      = null;
    etForm         = { users: [], tipo: 'turno', target_id: null };
    etUserDropOpen = false;
  }

  function _solverRefNome(tipo, refId) {
    if (tipo === 'flag') return solverFlagTurno.find(f => f.id === refId)?.nome || '?';
    return solverTipiQual.find(t => t.id === refId)?.nome || '?';
  }
  function _solverAggiornaRiepilogo() {
    const idx = solverUtenti.findIndex(u => u.id === solverEditUid);
    if (idx >= 0) {
      solverUtenti[idx] = {
        ...solverUtenti[idx],
        vincoli: solverEditVincoli.filter(v => v.chiave && v.valore),
        esclusioni: solverEditEscl.filter(e => e.flag_id),
        vincoli_solver: solverEditVSolver.filter(v => v.ref_id).map(v => ({
          ...v, ref_nome: v.ref_nome || _solverRefNome(v.tipo, v.ref_id)
        })),
      };
    }
  }

  async function solverAnteprima() {
    if (!calId) return;
    solverLoading = true;
    solverResult = null;
    const r = await managerApi.lanciaSolver(calId, _solverPayload(true));
    solverResult = r;
    solverLoading = false;
  }

  async function solverEsegui() {
    if (!calId) return;
    solverLoading = true;
    const r = await managerApi.lanciaSolver(calId, _solverPayload(false));
    solverResult = r;
    solverLoading = false;
    if (r.ok) {
      showToast(`Solver: ${r.celle_riempite}/${r.celle_totali} celle riempite (${r.durata_ms}ms)`, false);
      solverOpen = false;
      solverResult = null;
      await caricaCalendario(calId);
    } else {
      showToast(r.errore || 'Errore solver', true);
    }
  }

  // ── Regole snapshot editor ──────────────────────────────────
  let solverFlagOrdinati = $derived((() => {
    const radice = solverFlagTurno.filter(f => !f.parent_id);
    return radice.flatMap(r => [r, ...solverFlagTurno.filter(f => f.parent_id === r.id)]);
  })());

  function solverFlagLabel(nameOrId) {
    if (!nameOrId && nameOrId !== 0) return '\u2014';
    const f = typeof nameOrId === 'number'
      ? solverFlagTurno.find(x => x.id === nameOrId)
      : solverFlagTurno.find(x => x.nome === nameOrId);
    if (!f) return String(nameOrId);
    return f.parent_nome ? `${f.parent_nome}\u2192${f.nome}` : f.nome;
  }

  function solverRegolaStyle(r) {
    try {
      const st = typeof r.stile === 'string' ? JSON.parse(r.stile || '{}') : (r.stile || {});
      return `background-color:${st.backgroundColor || '#6c757d'};color:${st.color || '#fff'}`;
    } catch { return ''; }
  }

  function solverRegolaStileParsed(r) {
    try {
      return typeof r.stile === 'string' ? JSON.parse(r.stile || '{}') : { ...(r.stile || {}) };
    } catch { return {}; }
  }

  function solverStartEditRegola(r) {
    solverEditRegola = { ...r };
  }

  function solverApplicaEditRegola() {
    if (!solverEditRegola) return;
    const idx = regoleConflitto.findIndex(x => x.id === solverEditRegola.id);
    if (idx >= 0) {
      regoleConflitto[idx] = { ...solverEditRegola };
      regoleConflitto = [...regoleConflitto];
    }
    solverEditRegola = null;
    solverRegoleDirty = true;
  }

  function solverEliminaRegola(id) {
    regoleConflitto = regoleConflitto.filter(r => r.id !== id);
    solverRegoleDirty = true;
  }

  function solverAggiungiRegola() {
    const maxId = regoleConflitto.reduce((m, r) => Math.max(m, r.id || 0), 0);
    solverNuovaRegola = {
      id: maxId + 1,
      nome: '',
      tipo_regola: 'tipo_vs_tipo',
      flag_a_id: null,
      flag_b_id: null,
      flag_a_nome: null,
      flag_b_nome: null,
      offset_giorni: 0,
      categoria: 'consigliata',
      stile: '{"backgroundColor":"#ffc107","color":"#000"}',
      blocca_inserimento: 1,
      peso_numerico: 1,
      is_active: 1,
    };
    solverShowAddRegola = true;
  }

  function solverConfermaAggiungi() {
    if (!solverNuovaRegola || !solverNuovaRegola.nome) return;
    // Resolve flag names
    if (solverNuovaRegola.flag_a_id) {
      const f = solverFlagTurno.find(x => x.id === solverNuovaRegola.flag_a_id);
      solverNuovaRegola.flag_a_nome = f?.nome || null;
    }
    if (solverNuovaRegola.flag_b_id) {
      const f = solverFlagTurno.find(x => x.id === solverNuovaRegola.flag_b_id);
      solverNuovaRegola.flag_b_nome = f?.nome || null;
    }
    regoleConflitto = [...regoleConflitto, solverNuovaRegola];
    solverShowAddRegola = false;
    solverNuovaRegola = null;
    solverRegoleDirty = true;
  }

  async function solverSalvaRegoleSnapshot() {
    if (!calId) return;
    // Resolve flag names before saving
    const regoleFinali = regoleConflitto.map(r => {
      const copia = { ...r };
      if (copia.flag_a_id) {
        const f = solverFlagTurno.find(x => x.id === copia.flag_a_id);
        copia.flag_a_nome = f?.nome || copia.flag_a_nome || null;
      }
      if (copia.flag_b_id) {
        const f = solverFlagTurno.find(x => x.id === copia.flag_b_id);
        copia.flag_b_nome = f?.nome || copia.flag_b_nome || null;
      }
      return copia;
    });
    const r = await managerApi.salvaRegoleSnapshot(calId, regoleFinali);
    if (r.ok) {
      regoleConflitto = regoleFinali;
      solverRegoleDirty = false;
      showToast('Regole snapshot salvate');
    } else {
      showToast(r.errore || 'Errore salvataggio regole', true);
    }
  }

  async function solverResetRegole() {
    const rs = await managerApi.getStruttura(calId);
    if (rs.ok) {
      regoleConflitto = rs.regole_conflitto ?? [];
      solverRegoleDirty = false;
    }
  }

  // ── Vincoli snapshot editor ────────────────────────────────
  function snapAddVincoloSolver(tipo) {
    snapVincoliSolver = [...snapVincoliSolver, { tipo, ref_id: null, max_n: 0, is_active: 1 }];
    snapVincoliDirty = true;
  }

  function snapRemoveVincoloSolver(idx) {
    snapVincoliSolver = snapVincoliSolver.filter((_, i) => i !== idx);
    snapVincoliDirty = true;
  }

  function _buildConfigSnapshot() {
    // Unisce vincoli globali, solver, e dati per-utente (gia' aggiornati
    // in configSnapshot dalla tab Utenti)
    return {
      ...configSnapshot,
      vincoli_globali: snapVincoliGlobali,
      vincoli_solver: snapVincoliSolver,
    };
  }

  async function snapSalvaVincoli() {
    if (!calId) return;
    const config = _buildConfigSnapshot();
    const r = await managerApi.salvaConfigSnapshot(calId, config);
    if (r.ok) {
      configSnapshot = config;
      snapVincoliDirty = false;
      showToast('Vincoli snapshot salvati');
    } else {
      showToast(r.errore || 'Errore salvataggio vincoli', true);
    }
  }

  async function snapResetVincoli() {
    const rs = await managerApi.getStruttura(calId);
    if (rs.ok) {
      configSnapshot = rs.config_snapshot ?? {};
      snapVincoliGlobali = [...(configSnapshot.vincoli_globali ?? [])];
      snapVincoliSolver = [...(configSnapshot.vincoli_solver ?? [])];
      snapVincoliDirty = false;
    }
  }

  // ── Escludi turno — esclusioni per-utente per-turno/gruppo/sg ──────────────

  /** Elenca tutti i target selezionabili in base al tipo corrente. */
  function _etTargets(tipo) {
    const sgs = struttura?.sovragruppi ?? [];
    if (tipo === 'sovragruppo') {
      return sgs.map(sg => ({ id: sg.id, label: `${sg.sigla} — ${sg.nome}` }));
    }
    if (tipo === 'gruppo') {
      return sgs.flatMap(sg =>
        sg.gruppi.map(g => ({ id: g.id, label: `${g.sigla} — ${g.nome}` }))
      );
    }
    // tipo === 'turno'
    return sgs.flatMap(sg =>
      sg.gruppi.flatMap(g =>
        g.turni.map(t => ({ id: t.local_id, label: `${t.sigla} — ${t.descrizione || t.sigla}` }))
      )
    );
  }

  /** Trova la label di un'esclusione per la visualizzazione. */
  function _etLabel(esc) {
    const targets = _etTargets(esc.tipo);
    const found = targets.find(t => t.id === esc.target_id);
    return found?.label ?? `id:${esc.target_id}`;
  }

  /**
   * Ritorna i figli/nipoti selezionabili come eccezioni per una esclusione gruppo/SG.
   * Per gruppo: turni del gruppo. Per SG: gruppi e turni del SG.
   */
  function _etFigli(esc) {
    const sgs = struttura?.sovragruppi ?? [];
    if (esc.tipo === 'gruppo') {
      for (const sg of sgs) {
        const g = sg.gruppi.find(g => g.id === esc.target_id);
        if (g) return g.turni.map(t => ({ id: t.local_id, label: t.sigla }));
      }
      return [];
    }
    if (esc.tipo === 'sovragruppo') {
      const sg = sgs.find(sg => sg.id === esc.target_id);
      if (!sg) return [];
      const result = [];
      for (const g of sg.gruppi) {
        result.push({ id: g.id, label: g.sigla });
        for (const t of g.turni) {
          result.push({ id: t.local_id, label: `  ${t.sigla}` });
        }
      }
      return result;
    }
    return [];
  }

  /** Toggle eccezione figlio in una esclusione (modifica locale, setta dirty). */
  function etToggleEccezione(idx, childId) {
    const esc = etData[idx];
    const ecc = esc.eccezioni ?? [];
    esc.eccezioni = ecc.includes(childId)
      ? ecc.filter(e => e !== childId)
      : [...ecc, childId];
    etData = [...etData];
    etDirty = true;
  }

  /** Toggle utente nella lista users del form specificato. */
  function _etToggleUser(form, uid) {
    const idx = form.users.indexOf(uid);
    if (idx >= 0) form.users = form.users.filter(u => u !== uid);
    else form.users = [...form.users, uid];
  }

  /** Aggiunge esclusioni per tutti gli utenti selezionati nel form add. */
  function etAggiungi() {
    if (etForm.users.length === 0 || !etForm.target_id) return;
    const duplicati = etForm.users.filter(uid =>
      etData.some(e => e.user_id === uid && e.tipo === etForm.tipo && e.target_id === etForm.target_id)
    );
    if (duplicati.length > 0) {
      const sigle = duplicati.map(uid => utenti.find(u => u.id === uid)?.sigla ?? uid).join(', ');
      alert(`Esclusione già presente per: ${sigle}`);
      return;
    }
    const nuove = etForm.users.map(uid => ({ user_id: uid, tipo: etForm.tipo, target_id: etForm.target_id, eccezioni: [] }));
    etData = [...etData, ...nuove];
    etForm = { ...etForm, target_id: null, users: [] };
    etUserDropOpen = false;
    etDirty = true;
  }

  /** Apre l'editing inline di una riga (aggrega righe dello stesso tipo+target). */
  function etAvviaEdit(idx) {
    const esc = etData[idx];
    etEditIdx = idx;
    etEditForm = { users: [esc.user_id], tipo: esc.tipo, target_id: esc.target_id };
    etEditDropOpen = false;
  }

  /** Salva l'editing di una riga: sostituisce la riga corrente con le nuove. */
  function etSalvaEdit() {
    if (etEditForm.users.length === 0 || !etEditForm.target_id) return;
    // Check duplicati escludendo la riga corrente
    const altreDati = etData.filter((_, i) => i !== etEditIdx);
    const duplicati = etEditForm.users.filter(uid =>
      altreDati.some(e => e.user_id === uid && e.tipo === etEditForm.tipo && e.target_id === etEditForm.target_id)
    );
    if (duplicati.length > 0) {
      const sigle = duplicati.map(uid => utenti.find(u => u.id === uid)?.sigla ?? uid).join(', ');
      alert(`Esclusione già presente per: ${sigle}`);
      return;
    }
    const nuove = etEditForm.users.map(uid => ({
      user_id: uid, tipo: etEditForm.tipo, target_id: etEditForm.target_id, eccezioni: []
    }));
    etData = [...altreDati.slice(0, etEditIdx), ...nuove, ...altreDati.slice(etEditIdx)];
    etEditIdx = null;
    etEditDropOpen = false;
    etDirty = true;
  }

  /** Annulla editing inline. */
  function etAnnullaEdit() {
    etEditIdx = null;
    etEditDropOpen = false;
  }

  /** Rimuove una esclusione dalla lista locale. */
  function etRimuovi(idx) {
    if (etEditIdx === idx) { etEditIdx = null; }
    etData = etData.filter((_, i) => i !== idx);
    etDirty = true;
  }

  /** Salva le esclusioni nel config_snapshot del calendario. */
  async function etSalva() {
    if (!calId) return;
    etLoading = true;
    const config = { ...configSnapshot, esclusioni_turno: etData };
    const r = await managerApi.salvaConfigSnapshot(calId, config);
    etLoading = false;
    if (r.ok) {
      configSnapshot = config;
      etDirty = false;
      showToast('Esclusioni turno salvate');
    } else {
      showToast(r.errore || 'Errore salvataggio esclusioni', true);
    }
  }

  /** Annulla le modifiche ricaricando dallo snapshot corrente. */
  function etAnnulla() {
    etData = [...(configSnapshot.esclusioni_turno ?? [])];
    etDirty = false;
    etEditIdx = null;
    etForm = { users: [], tipo: 'turno', target_id: null };
    etUserDropOpen = false;
  }

  // ── Utenti (vincoli per-utente dallo snapshot) ─────────────
  function _snapUtentiForUser(uid) {
    const vu = (configSnapshot.vincoli_utente ?? []).filter(v => v.user_id === uid);
    const vsu = (configSnapshot.vincoli_solver_utente ?? []).filter(v => v.user_id === uid);
    const eu = (configSnapshot.esclusioni_utente ?? []).filter(e => e.user_id === uid);
    return { vincoli: vu, vincoli_solver: vsu, esclusioni: eu };
  }

  function solverEspandiUtente(uid) {
    if (solverEditUid === uid) { solverEditUid = null; return; }
    solverEditUid = uid;
    const dati = _snapUtentiForUser(uid);
    solverEditVincoli = [...dati.vincoli];
    solverEditVSolver = [...dati.vincoli_solver];
    solverEditEscl = [...dati.esclusioni];
  }

  function _solverSalvaUtentiSnapshot() {
    if (!solverEditUid) return;
    const uid = solverEditUid;
    // Rimuovi i vecchi dati dell'utente dallo snapshot
    const snap = { ...configSnapshot };
    snap.vincoli_utente = [
      ...(snap.vincoli_utente ?? []).filter(v => v.user_id !== uid),
      ...solverEditVincoli.filter(v => v.chiave && v.valore).map(v => ({ ...v, user_id: uid })),
    ];
    snap.vincoli_solver_utente = [
      ...(snap.vincoli_solver_utente ?? []).filter(v => v.user_id !== uid),
      ...solverEditVSolver.filter(v => v.ref_id).map(v => ({ ...v, user_id: uid })),
    ];
    snap.esclusioni_utente = [
      ...(snap.esclusioni_utente ?? []).filter(e => e.user_id !== uid),
      ...solverEditEscl.filter(e => e.flag_id).map(e => ({ ...e, user_id: uid })),
    ];
    configSnapshot = snap;
    // Aggiorna riepilogo
    _solverAggiornaRiepilogo();
    snapVincoliDirty = true;
  }

  function solverSalvaVincoli() { _solverSalvaUtentiSnapshot(); }
  function solverSalvaVSolver() { _solverSalvaUtentiSnapshot(); }
  function solverSalvaEscl() { _solverSalvaUtentiSnapshot(); }

  // ── Optimizer ──────────────────────────────────────────────
  let optOpen      = $state(false);
  let optPresets   = $state([]);
  let optPresetId  = $state(null);
  let optMaxIter   = $state(1000);
  let optPreview   = $state(false);
  let optResult    = $state(null);
  let optLoading   = $state(false);
  let optUsaSA     = $state(false);
  let optTempIni   = $state(0.1);
  let optRaffredd  = $state(0.995);

  // ── Aspetto griglia + colori export Excel ─────────────────
  let exportHeaderBg   = $state('#1F4E79');
  let exportHeaderFg   = $state('#FFFFFF');
  let appModalOpen     = $state(false);
  let appLocal         = $state({ ...APPEARANCE_DEFAULT });
  let appLocalDirty    = $state(false);
  let appLocalLoading  = $state(false);

  function apriAppModal() {
    appLocal = { ...APPEARANCE_DEFAULT, ...(struttura?.calendario?.appearance ?? {}) };
    appLocalDirty   = false;
    appLocalLoading = false;
    appModalOpen    = true;
  }

  function onAppChange(newApp) {
    appLocal      = newApp;
    appLocalDirty = true;
  }

  async function salvaApp() {
    if (!calId || !appLocalDirty) return;
    appLocalLoading = true;
    const r = await managerApi.salvaAppearanceSnapshot(calId, appLocal);
    appLocalLoading = false;
    if (r.ok) {
      struttura = {
        ...struttura,
        calendario: { ...struttura.calendario, appearance: { ...r.appearance } },
      };
      appLocalDirty = false;
      showToast('Aspetto salvato.');
    } else {
      showToast(r.errore || 'Errore salvataggio aspetto.', true);
    }
  }

  async function optApri() {
    if (!calId) return;
    optOpen = true;
    optResult = null;
    optLoading = false;
    optTurniSel = _turniAllLocalIds();
    optTurniTutti = true;
    // Carica preset attivi
    try {
      const r = await adminApi.getPresetOttimizzazione();
      optPresets = (r.preset ?? []).filter(p => p.is_active);
      if (optPresets.length > 0 && !optPresetId) {
        optPresetId = optPresets[0].id;
      }
    } catch { optPresets = []; }
  }

  async function optEsegui() {
    if (!calId) return;
    optLoading = true;
    optResult = null;
    const opzioni = {
      preset_id: optPresetId,
      max_iterazioni: optMaxIter,
      preview: optPreview,
    };
    if (optUsaSA) {
      opzioni.temperatura_iniziale = optTempIni;
      opzioni.raffreddamento = optRaffredd;
    }
    if (!optTurniTutti && optTurniSel.length > 0) {
      opzioni.turni_ids = optTurniSel;
    }
    const r = await managerApi.ottimizza(calId, opzioni);
    optResult = r;
    optLoading = false;
    if (r.ok && !optPreview && r.swap_count > 0) {
      showToast(`Optimizer: ${r.swap_count} swap, costo ${r.delta_pct > 0 ? '-' : ''}${Math.abs(r.delta_pct)}% (${r.durata_ms}ms)`, false);
      optOpen = false;
      optResult = null;
      await caricaCalendario(calId);
    }
  }

  // ── Esclusioni manuali (Escludi giorno) ─────────────────────
  let esclusioni = $state([]);
  let esclNuova = $state({ tipo: 'giorno', user_id: null, giorno: 1, giorno_da: 1, giorno_a: 28, giorni_settimana: [], motivo: '' });

  function esclAggiungi() {
    const e = { ...esclNuova };
    if (!e.user_id) return;
    if (e.tipo === 'giorno') { delete e.giorno_da; delete e.giorno_a; delete e.giorni_settimana; }
    else if (e.tipo === 'intervallo') { delete e.giorno; delete e.giorni_settimana; }
    else if (e.tipo === 'giorno_settimana') { delete e.giorno; delete e.giorno_da; delete e.giorno_a; }
    esclusioni = [...esclusioni, e];
    esclNuova = { tipo: 'giorno', user_id: null, giorno: 1, giorno_da: 1, giorno_a: 28, giorni_settimana: [], motivo: '' };
  }

  function esclRimuovi(idx) {
    esclusioni = esclusioni.filter((_, i) => i !== idx);
  }

  async function esclSalva() {
    const r = await managerApi.setEsclusioni(calId, esclusioni);
    if (r.ok) showToast('Esclusioni giorno salvate');
    else showToast(r.errore || 'Errore', true);
  }

  // Helper: toggle giorno settimana per esclusione giorno_settimana
  function esclToggleDow(dow) {
    const gs = [...(esclNuova.giorni_settimana || [])];
    const idx = gs.indexOf(dow);
    if (idx >= 0) gs.splice(idx, 1); else gs.push(dow);
    esclNuova.giorni_settimana = gs;
  }

  // ── Celle bloccate ────────────────────────────────────────────
  let celleBloccate = $state(new Set());  // set di "turno_id-giorno"

  async function caricaCelleBloccate() {
    if (!calId) return;
    const r = await managerApi.getCelleBloccate(calId);
    const celle = r.celle ?? [];
    celleBloccate = new Set(celle.map(c => `${c.turno_id}-${c.giorno}`));
  }

  async function toggleCellaBloccata(turnoId, giorno) {
    const key = `${turnoId}-${giorno}`;
    const nuove = new Set(celleBloccate);
    if (nuove.has(key)) nuove.delete(key); else nuove.add(key);
    celleBloccate = nuove;
    // Salva
    const celle = [...nuove].map(k => {
      const [tid, g] = k.split('-').map(Number);
      return { turno_id: tid, giorno: g };
    });
    await managerApi.setCelleBloccate(calId, celle);
  }

  function isCellaBloccata(turnoId, giorno) {
    return celleBloccate.has(`${turnoId}-${giorno}`);
  }

  // ── Aperture straordinarie ──────────────────────────────────
  let apertureOpen = $state(false);
  let apertureTurni = $state([]);  // copia locale per editing
  let apertureSaving = $state(false);

  async function apertureApri() {
    if (!calId) return;
    apertureOpen = true;
    apertureSaving = false;
    // Costruisci lista turni con i dati correnti dalla struttura
    const turni = [];
    for (const sg of (struttura?.sovragruppi ?? []))
      for (const g of sg.gruppi)
        for (const t of g.turni)
          turni.push({
            turno_id: t.id,
            sigla: t.sigla,
            descrizione: t.descrizione || t.sigla,
            gruppo: g.nome,
            apri_festivi: t.apri_festivi || 0,
            apri_superfestivi: t.apri_superfestivi || 0,
            aperture_straordinarie: [...(t.aperture_straordinarie || [])],
          });
    apertureTurni = turni;
  }

  function apertureToggleGiorno(turnoIdx, giorno) {
    const t = apertureTurni[turnoIdx];
    const ap = new Set(t.aperture_straordinarie);
    if (ap.has(giorno)) ap.delete(giorno); else ap.add(giorno);
    apertureTurni[turnoIdx] = { ...t, aperture_straordinarie: [...ap].sort((a, b) => a - b) };
  }

  async function apertureSalva() {
    if (!calId) return;
    apertureSaving = true;
    const payload = apertureTurni.map(t => ({
      turno_id: t.id,
      apri_festivi: t.apri_festivi,
      apri_superfestivi: t.apri_superfestivi,
      aperture_straordinarie: t.aperture_straordinarie,
    }));
    const r = await managerApi.salvaAperture(calId, payload);
    apertureSaving = false;
    if (r.ok) {
      showToast('Aperture salvate', false);
      apertureOpen = false;
      // Aggiorna i dati nella struttura locale
      const map = {};
      for (const t of apertureTurni) map[t.id] = t;
      for (const sg of struttura.sovragruppi)
        for (const g of sg.gruppi)
          for (const t of g.turni) {
            const m = map[t.id];
            if (m) {
              t.apri_festivi = m.apri_festivi;
              t.apri_superfestivi = m.apri_superfestivi;
              t.aperture_straordinarie = m.aperture_straordinarie;
            }
          }
      struttura = { ...struttura };
    } else {
      showToast(r.errore || 'Errore salvataggio', true);
    }
  }

  // ── Costanti ─────────────────────────────────────────────────
  const NOMI_MESI = ['','Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
                     'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'];
  const NOMI_GG   = ['Dom','Lun','Mar','Mer','Gio','Ven','Sab'];

  function _fmtArchDate(iso) {
    if (!iso) return '';
    // SQLite datetime usa spazio come separatore: "YYYY-MM-DD HH:MM:SS" → sostituisci con T per compatibilità
    const d = new Date(iso.replace(' ', 'T'));
    if (isNaN(d)) return iso;
    return d.toLocaleDateString('it-IT', { day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit' });
  }

  // ── Derivati ─────────────────────────────────────────────────

  /** Valori appearance correnti — reactive, aggiorna border functions. */
  let appVals = $derived(struttura?.calendario?.appearance ?? {});

  /** CSS custom properties generate dall'appearance del calendario. */
  let gridCssVars = $derived(
    `--gc-festivi-bg:${appVals.festivi_bg ?? '#fff3cd'};` +
    `--gc-superfestivi-bg:${appVals.superfestivi_bg ?? '#f8d7da'};` +
    `--gc-prima-riga-bg:${appVals.prima_riga_bg ?? '#f8f9fa'};` +
    `--gc-cella-bordo:${appVals.cella_bordo_spessore ?? 1}px solid ${appVals.cella_bordo_colore ?? '#dee2e6'};` +
    `--gc-bordo-esterno:${appVals.bordo_esterno_spessore ?? 2}px solid ${appVals.bordo_esterno_colore ?? '#adb5bd'}`
  );

  let numGiorni = $derived(struttura?.calendario
    ? new Date(struttura.calendario.anno, struttura.calendario.mese, 0).getDate()
    : 0);

  // ── Giorno settimana per ogni giorno del mese (0=Dom ... 6=Sab) ──
  let giornoSettimana = $derived.by(() => {
    if (!struttura?.calendario) return {};
    const { anno, mese } = struttura.calendario;
    const map = {};
    for (let g = 1; g <= numGiorni; g++) {
      map[g] = new Date(anno, mese - 1, g).getDay(); // 0=Dom, 6=Sab
    }
    return map;
  });

  // ── Notti mese precedente ────────────────────────────────────
  // Mappa local_id → true per turni notturni del calendario corrente
  let nottiLocalIds = $derived.by(() => {
    if (!struttura?.sovragruppi) return new Set();
    const s = new Set();
    for (const sg of struttura.sovragruppi)
      for (const g of sg.gruppi)
        for (const t of g.turni)
          if ((t.flag_nome || '').toLowerCase() === 'notturno') s.add(t.local_id);
    return s;
  });
  // true = ci sono turni notturni nel calendario
  let hasNotti = $derived(nottiLocalIds.size > 0);
  // notti_mese_prec: { local_id → user_id } | null (null = nessun calendario precedente)
  let nottiMesePrec = $derived(struttura?.notti_mese_prec ?? null);
  // Helper: sigla utente assegnato alla notte dell'ultimo giorno del mese prec per un dato turno
  function nottePrec(turno) {
    if (!nottiLocalIds.has(turno.local_id)) return null; // non è notturno
    if (nottiMesePrec === null) return undefined; // nessun calendario precedente
    if (!(turno.local_id in nottiMesePrec)) return undefined; // turno non presente nel mese prec
    const uid = nottiMesePrec[turno.local_id];
    if (uid == null) return ''; // slot vuoto (non assegnato)
    return utenti.find(u => u.id === uid)?.sigla ?? '';
  }

  // ── Conteggi configurabili context menu ──────────────────────
  let conteggiConfig = $state([]);

  // ── Riepilogo turni per lavoratore ─────────────────────────

  // Ore per giorno: mappa giorno → ore_lavorative (o default)
  let _oreMap = $derived.by(() => {
    if (!struttura) return {};
    const oreDefault = struttura.calendario?.ore_giornaliere_default ?? 6.5;
    const map = {};
    for (const g of (struttura.giorni ?? [])) {
      map[g.giorno] = g.ore_lavorative != null ? g.ore_lavorative : oreDefault;
    }
    map._default = oreDefault;
    return map;
  });
  function oreGiorno(g) { return _oreMap[g] ?? _oreMap._default ?? 6.5; }

  // Turni dovuti = numero di giorni lavorativi nel mese
  let turniDovuti = $derived(
    struttura?.giorni?.filter(g => g.is_lavorativo).length ?? 0
  );

  // Ore dovute = somma ore_lavorative dei giorni lavorativi
  let oreDovute = $derived.by(() => {
    if (!struttura?.giorni) return 0;
    let tot = 0;
    for (const g of struttura.giorni) {
      if (g.is_lavorativo) tot += oreGiorno(g.giorno);
    }
    return tot;
  });

  // Per ogni lavoratore: turni pesati + ore calcolate per-turno
  // Mappa user_id → { turni, ore }
  let turniPerUtente = $derived.by(() => {
    if (!struttura?.sovragruppi) return {};
    const oreDefault = struttura.calendario?.ore_giornaliere_default ?? 6.5;
    const gs = giornoSettimana;
    const conteggi = conteggiConfig.filter(c => c.attivo);
    const result = {};
    for (const sg of struttura.sovragruppi)
      for (const gr of sg.gruppi)
        for (const t of gr.turni) {
          const peso = t.peso_turno ?? 1;
          const oreTurno = t.ore_turno;
          const orePrimo = t.ore_primo_giorno;
          const oreUltimo = t.ore_ultimo_giorno;
          const tipoTemp = (t.flag_nome || '').toLowerCase();
          for (let g = 1; g <= numGiorni; g++) {
            const uid = localAss[`${t.id}-${g}`]?.user_id;
            if (uid == null) continue;
            if (!result[uid]) result[uid] = { turni: 0, ore: 0 };
            result[uid].turni += peso;
            // Ore: primo/ultimo giorno override, poi ore_turno, poi fallback
            let ore;
            if (g === 1 && orePrimo != null) ore = orePrimo;
            else if (g === numGiorni && oreUltimo != null) ore = oreUltimo;
            else if (oreTurno != null) ore = oreTurno;
            else ore = oreGiorno(g) || oreDefault;
            result[uid].ore += ore;
            // Conteggi configurabili
            const dow = gs[g]; // 0=Dom, 6=Sab
            for (const c of conteggi) {
              const matchTipo = tipoTemp === (c.flag_nome || c.tipo_temporale || '').toLowerCase();
              const matchGiorno = c.giorno_settimana == null || dow === c.giorno_settimana;
              const match = c.negato ? (!matchTipo && matchGiorno) : (matchTipo && matchGiorno);
              if (match) {
                result[uid][c.id] = (result[uid][c.id] ?? 0) + 1;
              }
            }
          }
        }
    return result;
  });

  // Formatta ore decimali in hh:mm
  function fmtOre(oreDecimali) {
    const h = Math.floor(oreDecimali);
    const m = Math.round((oreDecimali - h) * 60);
    return `${h}:${String(m).padStart(2, '0')}`;
  }

  // Tutti gli utenti attivi — per griglie desiderata e context menu
  let utentiBasic = $derived(utenti);

  // Mappa sg_id → style (dallo snapshot del calendario) per le viste WD/Originali
  let desSgStyleMap = $derived.by(() => {
    const m = {};
    const sgs = struttura?.sovragruppi ?? [];
    for (const sg of sgs) m[sg.id] = sg.style ?? {};
    return m;
  });

  // Stile inline per blocco SG (solo backgroundColor + color dallo snapshot).
  function desSgBlockStyle(sgId) {
    const s = desSgStyleMap[sgId] ?? {};
    const parts = [];
    if (s.backgroundColor) parts.push(`background-color:${s.backgroundColor}`);
    if (s.color)           parts.push(`color:${s.color}`);
    return parts.join(';');
  }

  // Flag "ripeti nome" dallo stile SG (replica comportamento griglia turni)
  function desSgRepeat(sgId) {
    return !!(desSgStyleMap[sgId]?.['--repeatName']);
  }

  // Raggruppa utenti consecutivi per sovragruppo (per WD/Originali) — stessa
  // logica di DesiderataInserimento: chiave unica `${sg}_${pos}` per evitare
  // duplicate keys in alfabetico_globale.
  let desUserGroups = $derived.by(() => {
    const out = [];
    let cur = null;
    const sgMap = {};
    for (const sg of (struttura?.sovragruppi ?? [])) sgMap[sg.id] = sg;
    for (const u of utentiBasic) {
      const sgKey = u.sovragruppo_id ?? 'null';
      if (cur && cur.sgKey === sgKey) {
        cur.count++; cur.users.push(u);
      } else {
        const sg = sgMap[u.sovragruppo_id] ?? null;
        cur = {
          key: `${sgKey}_${out.length}`,
          sgKey,
          count: 1, users: [u],
          sg_sigla: sg?.sigla ?? null,
          sg_nome:  sg?.nome ?? null,
          sovragruppo_id: u.sovragruppo_id,
        };
        out.push(cur);
      }
    }
    return out;
  });

  // Mappa (user_id → giorno → entry) per lookup O(1)
  function _buildMap(arr) {
    const m = {};
    for (const d of arr) {
      if (!m[d.user_id]) m[d.user_id] = {};
      m[d.user_id][d.giorno] = d;
    }
    return m;
  }
  let wdMap  = $derived(_buildMap(wdFull));
  let desMap = $derived(_buildMap(desFull));

  // Applica l'ordinamento dei desiderata (stesso criterio della pagina basic).
  // modalita:
  //   - 'alfabetico_globale'   → per sigla
  //   - 'alfabetico_intragruppo' → per ordine effettivo SG, poi sigla
  //   - 'manuale'              → per ordine effettivo SG, poi users.ordine_desiderata, poi sigla
  function _sortByModalitaDes(lista, modalita, sgMap) {
    const sigla = u => (u.sigla || '').toUpperCase();
    const sgOrd = u => {
      if (!u.sovragruppo_id) return 999999;
      const sg = sgMap[u.sovragruppo_id];
      if (!sg) return 999999;
      return sg.ordine_desiderata ?? sg.ordine ?? 0;
    };
    const copy = [...lista];
    if (modalita === 'alfabetico_globale') {
      copy.sort((a, b) => sigla(a).localeCompare(sigla(b)));
    } else if (modalita === 'manuale') {
      copy.sort((a, b) => {
        const d = sgOrd(a) - sgOrd(b); if (d) return d;
        const od = (a.ordine_desiderata ?? 0) - (b.ordine_desiderata ?? 0); if (od) return od;
        return sigla(a).localeCompare(sigla(b));
      });
    } else { // alfabetico_intragruppo (default)
      copy.sort((a, b) => {
        const d = sgOrd(a) - sgOrd(b); if (d) return d;
        return sigla(a).localeCompare(sigla(b));
      });
    }
    return copy;
  }

  function _resortUtenti() {
    const sgMap = {};
    for (const sg of sovragruppiOrd) sgMap[sg.id] = sg;
    utenti = _sortByModalitaDes(utenti, modalitaDesOrd, sgMap);
  }

  async function cambiaModalitaDesOrd(nuova) {
    const r = await adminApi.setModalitaOrdinamentoDesiderata(nuova);
    if (!r.ok) { showToast(r.errore ?? 'Errore salvataggio modalità.', true); return; }
    modalitaDesOrd = nuova;
    if (nuova !== 'manuale') riordinoDesOn = false;
    _resortUtenti();
  }

  async function spostaUtenteDesOrd(uid, delta) {
    const idx = utenti.findIndex(u => u.id === uid);
    const target = idx + delta;
    if (idx < 0 || target < 0 || target >= utenti.length) return;
    const nuovi = [...utenti];
    const [x] = nuovi.splice(idx, 1);
    nuovi.splice(target, 0, x);
    nuovi.forEach((u, i) => { u.ordine_desiderata = i; });
    utenti = nuovi;
    const r = await adminApi.setOrdineUtentiDesiderata(nuovi.map(u => u.id));
    if (!r.ok) showToast(r.errore ?? 'Errore salvataggio ordine utenti.', true);
  }

  async function spostaSovragruppoDesOrd(sgId, delta) {
    const idx = sovragruppiOrd.findIndex(s => s.id === sgId);
    const target = idx + delta;
    if (idx < 0 || target < 0 || target >= sovragruppiOrd.length) return;
    const nuovi = [...sovragruppiOrd];
    const [x] = nuovi.splice(idx, 1);
    nuovi.splice(target, 0, x);
    nuovi.forEach((s, i) => { s.ordine_desiderata = i; });
    sovragruppiOrd = nuovi;
    const r = await adminApi.setOrdineSovragruppiDesiderata(nuovi.map(s => s.id));
    if (!r.ok) { showToast(r.errore ?? 'Errore salvataggio ordine SG.', true); return; }
    _resortUtenti();
  }

  // ── Avvio ────────────────────────────────────────────────────
  onMount(async () => {
    trasposto = localStorage.getItem('grigliaTrasposta') === '1';
    const [rc, ru, rt, rOrd] = await Promise.all([
      managerApi.getCalendari(),
      fetch('/api/admin/users', {
        headers: { Authorization: `Bearer ${getToken()}` }
      }).then(r => r.json()),
      managerApi.getTipi(),
      adminApi.getOrdinamentoDesiderata().catch(() => ({ ok: false })),
    ]);
    calendari       = rc.calendari ?? [];
    modalitaDesOrd  = rOrd?.ok ? rOrd.modalita : 'alfabetico_intragruppo';
    sovragruppiOrd  = rOrd?.ok ? (rOrd.sovragruppi ?? []) : [];
    const sgMap = {};
    for (const sg of sovragruppiOrd) sgMap[sg.id] = sg;
    const utentiAttivi = (ru.utenti ?? []).filter(u => u.is_active && !u.escluso_turni);
    utenti          = _sortByModalitaDes(utentiAttivi, modalitaDesOrd, sgMap);
    tipi            = rt.tipi ?? [];
    // Carica conteggi config
    try {
      const rcc = await managerApi.getConteggiConfig();
      conteggiConfig = rcc.conteggi ?? [];
    } catch { conteggiConfig = []; }
    if (calendari.length) await caricaCalendario(calendari[0].id);
    document.addEventListener('keydown', onGlobalKeyDown, true);
    document.addEventListener('pointerdown', onDocumentPointerDown);
    document.addEventListener('paste', onGlobalPaste);
  });

  let wsConnected = $state(false);

  async function caricaCalendario(id) {
    // Disconnetti dal calendario precedente
    if (calId) {
      leaveCalendario(calId);
      removeAllListeners();
    }

    calId   = id;
    loading = true;
    const [rs, rh, rwd, rd, rwdh] = await Promise.all([
      managerApi.getStruttura(id),
      managerApi.getHistory(id),
      managerApi.getWorkingDes(id),
      managerApi.getDesiderata(id),
      managerApi.getWdHistory(id),
    ]);
    loading = false;
    if (rs.ok)  {
      struttura = rs;
      initLocalAss(rs.assegnazioni ?? []);
      regoleConflitto = rs.regole_conflitto ?? [];
      solverRegoleDirty = false;
      if (rs.flag_turno?.length) solverFlagTurno = rs.flag_turno;
      configSnapshot = rs.config_snapshot ?? {};
      snapVincoliGlobali = [...(configSnapshot.vincoli_globali ?? [])];
      snapVincoliSolver = [...(configSnapshot.vincoli_solver ?? [])];
      snapVincoliDirty = false;
      const calStyle = rs.calendario?.style ?? {};
      if (calStyle['--colTurnoWidth']) colTurnoWidth = calStyle['--colTurnoWidth'];
    }
    if (rh.ok)   history = rh.history;
    if (rwd.ok)  wdFull  = rwd.working_desiderata ?? [];
    if (rd.ok)   desFull = rd.desiderata ?? [];
    if (rwdh.ok) wdHistory = rwdh.wd_history;

    // Celle bloccate
    caricaCelleBloccate();

    // Carica info effettivo — serve per principale e effettivo
    // Trova l'id del calendario principale per caricare l'effettivo associato
    let _progId = null;
    if (rs.ok) {
      const cal = rs.calendario;
      if (cal?.stato === 'CHIUSO' && cal?.tipo === 'programmato') {
        _progId = id;
      } else if (cal?.tipo === 'effettivo' && cal?.parent_id) {
        _progId = cal.parent_id;
      }
    }
    if (_progId) {
      const re = await managerApi.getEffettivo(_progId);
      effettivoInfo = (re.ok && re.effettivo) ? re.effettivo : null;
    } else {
      effettivoInfo = null;
    }

    // WebSocket: connetti e joina la room del calendario
    _setupWebSocket(id);
  }

  function _setupWebSocket(id) {
    const meId = $userStore?.id;
    onStatusChange((connected) => { wsConnected = connected; });
    connectSocket();
    joinCalendario(id);
    wsConnected = isConnected();

    onAssegnazioneChanged((data) => {
      if (data.manager_id === meId) return;
      const key = `${data.turno_id}-${data.giorno}`;
      localAss[key] = { user_id: data.user_id, conflitti: parseConflitti(data.conflitti) };
      localAss = localAss;
      if (data.history) history = data.history;
    });

    onUndoRedo((data) => {
      if (data.manager_id === meId) return;
      if (data.history) history = data.history;
      // Ricarica completa per undo/redo (potrebbe coinvolgere molte celle)
      caricaCalendarioSilent(id);
    });

    onSolverCompleted((data) => {
      if (data.manager_id === meId) return;
      caricaCalendarioSilent(id);
    });

    onDesiderataChanged((data) => {
      if (data.actor_id === meId) return;
      const arr = data.source === 'working_desiderata' ? wdFull : desFull;
      const idx = arr.findIndex(d => d.user_id === data.user_id && d.giorno === data.giorno);
      let next = [...arr];
      if (data.entry) {
        const rec = {
          user_id: data.user_id,
          giorno: data.giorno,
          tipo_richiesta_id: data.entry.tipo_richiesta_id,
          req_sigla: data.entry.req_sigla,
          req_tipo:  data.entry.req_tipo,
          note: null,
        };
        if (idx >= 0) next[idx] = { ...next[idx], ...rec };
        else next.push(rec);
      } else if (idx >= 0) {
        next.splice(idx, 1);
      }
      if (data.source === 'working_desiderata') wdFull = next;
      else desFull = next;
    });

    onPrivacyChanged((data) => {
      if (data.actor_id === meId) return;
      const idx = utenti.findIndex(u => u.id === data.user_id);
      if (idx >= 0) {
        utenti[idx] = { ...utenti[idx], offusca: data.offusca };
        utenti = [...utenti];
      }
    });
  }

  // Ricorda l'id del calendario principale per poterci tornare da effettivo
  let _principaleCalId = $state(null);

  async function switchCalTab(tab) {
    if (tab === calTab) return;
    // Salva l'id del calendario principale prima di switchare
    if (calTab === 'principale' && calId) _principaleCalId = calId;

    calTab = tab;
    if (tab === 'effettivo' && effettivoInfo?.id) {
      await caricaCalendario(effettivoInfo.id);
    } else if (tab === 'principale') {
      const targetId = _principaleCalId || struttura?.calendario?.parent_id;
      if (targetId) await caricaCalendario(targetId);
    }
  }

  async function caricaCalendarioSilent(id) {
    const [rs, rh] = await Promise.all([
      managerApi.getStruttura(id),
      managerApi.getHistory(id),
    ]);
    if (rs.ok) {
      struttura = rs;
      initLocalAss(rs.assegnazioni ?? []);
    }
    if (rh.ok) history = rh.history;
  }

  onDestroy(() => {
    if (calId) leaveCalendario(calId);
    disconnectSocket();
    if (typeof document !== 'undefined') {
      document.removeEventListener('keydown', onGlobalKeyDown, true);
      document.removeEventListener('pointerdown', onDocumentPointerDown);
      document.removeEventListener('paste', onGlobalPaste);
    }
  });

  /** Parsing conflitti: stringa JSON o array, con fallback a []. */
  function parseConflitti(raw) {
    try {
      return typeof raw === 'string' ? JSON.parse(raw) : (raw ?? []);
    } catch { return []; }
  }

  function initLocalAss(assegnazioni) {
    const m = {};
    for (const a of assegnazioni) {
      m[`${a.turno_id}-${a.giorno}`] = {
        user_id: a.user_id,
        originale_user_id: a.originale_user_id ?? null,
        conflitti: parseConflitti(a.conflitti),
      };
    }
    localAss = m;
    syncStatus = {};
  }

  /**
   * Applica un array di operazioni history alle assegnazioni locali.
   * Ogni op: { tabella, record_id, dati }.
   * Se dati è null (undo inserimento), cerca turno_id/giorno nei prev.
   */
  function applyAssOps(ops, prev) {
    let updated = { ...localAss };
    const prevArr = Array.isArray(prev) ? prev : (prev ? [prev] : []);
    for (const op of ops) {
      if (op.tabella !== 'assegnazioni_turni') continue;
      if (op.dati) {
        const key = `${op.dati.turno_id}-${op.dati.giorno}`;
        updated[key] = { user_id: op.dati.user_id, conflitti: parseConflitti(op.dati.conflitti) };
      } else {
        const other = prevArr.find(p => p.record_id === op.record_id);
        if (other?.dati) {
          const key = `${other.dati.turno_id}-${other.dati.giorno}`;
          updated[key] = { user_id: null, conflitti: [] };
        }
      }
    }
    localAss = updated;
  }

  // ── Modifica cella (ottimistica) ──────────────────────────────
  async function onCellChange(turnoId, giorno, rawVal) {
    if (isReadOnly) return;
    const key    = `${turnoId}-${giorno}`;
    const userId = rawVal === '' ? null : parseInt(rawVal);

    // Snapshot per eventuale rollback
    const prev = localAss[key] ?? null;

    // Aggiornamento locale immediato
    localAss   = { ...localAss,   [key]: { user_id: userId, conflitti: [] } };
    syncStatus = { ...syncStatus, [key]: 'saving' };

    await sincronizza(turnoId, giorno, userId, key, prev);
  }

  async function sincronizza(turnoId, giorno, userId, key, prev, forza = false) {
    let r;
    try {
      const payload = { turno_id: turnoId, giorno, user_id: userId };
      if (forza) payload.forza_inserimento = true;
      r = await managerApi.salvaAssegnazione(calId, payload);
    } catch (e) {
      localAss   = { ...localAss,   [key]: prev ?? { user_id: null, conflitti: [] } };
      syncStatus = { ...syncStatus, [key]: 'err' };
      showToast(`Errore di rete: ${e.message}`, true);
      setTimeout(() => { syncStatus = { ...syncStatus, [key]: '' }; }, 4000);
      return;
    }

    if (r.ok) {
      // Conferma con conflitti calcolati dal server
      const conflitti = r.conflitti ?? [];
      let updated = { ...localAss, [key]: { user_id: userId, conflitti } };
      // Propaga ricalcolo conflitti alle celle vicine impattate
      for (const v of (r.vicini ?? [])) {
        const vk = `${v.turno_id}-${v.giorno}`;
        if (updated[vk]) updated[vk] = { ...updated[vk], conflitti: v.conflitti };
      }
      localAss   = updated;
      syncStatus = { ...syncStatus, [key]: 'ok' };
      const rh = await managerApi.getHistory(calId);
      if (rh.ok) history = rh.history;
      setTimeout(() => { syncStatus = { ...syncStatus, [key]: '' }; }, 1200);
    } else if (r.codice === 'bloccato' && !forza) {
      // Regola bloccante: chiedi conferma per forzare
      const regole = (r.regole ?? []).join(', ');
      if (confirm(`Inserimento bloccato:\n${regole}\n\nForzare l'inserimento?`)) {
        await sincronizza(turnoId, giorno, userId, key, prev, true);
      } else {
        localAss   = { ...localAss,   [key]: prev ?? { user_id: null, conflitti: [] } };
        syncStatus = { ...syncStatus, [key]: '' };
      }
    } else {
      // Errore: rollback
      localAss   = { ...localAss,   [key]: prev ?? { user_id: null, conflitti: [] } };
      syncStatus = { ...syncStatus, [key]: 'err' };
      showToast(r.errore ?? 'Errore.', true);
      setTimeout(() => { syncStatus = { ...syncStatus, [key]: '' }; }, 3000);
    }
  }

  // ── Undo / Redo ───────────────────────────────────────────────
  async function doUndo() {
    if (isReadOnly) return;
    const r = await managerApi.undo(calId);
    if (r.ok) { await applyUndoRedo(r); showToast('Undo'); }
    else showToast(r.errore, true);
  }

  async function doRedo() {
    if (isReadOnly) return;
    const r = await managerApi.redo(calId);
    if (r.ok) { await applyUndoRedo(r); showToast('Redo'); }
    else showToast(r.errore, true);
  }

  async function applyUndoRedo(r) {
    if (r.history) history = r.history;

    const d = r.dati_applicati;
    const BATCH_TABLES = ['solver', 'optimizer', 'azzera', 'posti_fissi', 'incolla', 'swap'];

    if (BATCH_TABLES.includes(r.tabella) && Array.isArray(d)) {
      applyAssOps(d, r.dati_precedenti_step);
    } else if (r.tabella === 'assegnazioni_turni') {
      // Singola cella: wrappa in array per riusare applyAssOps
      const op = { tabella: 'assegnazioni_turni', record_id: d?.id, dati: d };
      const prev = r.dati_precedenti_step
        ? { record_id: d?.id, dati: r.dati_precedenti_step }
        : null;
      applyAssOps([op], prev ? [prev] : []);
    } else if (r.tabella === 'working_desiderata') {
      managerApi.getWorkingDes(calId).then(rwd => { if (rwd.ok) wdFull = rwd.working_desiderata ?? []; });
    }
  }

  // ── Helpers UI ────────────────────────────────────────────────
  function showToast(msg, err = false) {
    toast = msg; toastErr = err;
    setTimeout(() => toast = '', 3000);
  }

  function tipoGiorno(g) {
    return struttura?.giorni.find(x => x.giorno === g)?.tipo ?? 'normale';
  }

  function thClass(g) {
    const t = tipoGiorno(g);
    return t === 'superfestivo' ? 'gc-super' : t === 'festivo' ? 'gc-fest' : '';
  }

  /**
   * Restituisce lo stile inline della cella basato sulla categoria più alta
   * tra i conflitti attivati. Ogni conflitto porta il proprio stile.
   */
  const CATEGORIA_ORDINE = { facoltativa: 0, consigliata: 1, critica: 2 };

  function _parseStile(stile) {
    try {
      return typeof stile === 'string' ? JSON.parse(stile) : (stile || {});
    } catch { return {}; }
  }

  function _stileToCss(stile) {
    const st = _parseStile(stile);
    let css = '';
    if (st.backgroundColor) css += `background:${st.backgroundColor};`;
    if (st.color) css += `color:${st.color};`;
    if (st.fontWeight) css += `font-weight:${st.fontWeight};`;
    if (st.fontStyle) css += `font-style:${st.fontStyle};`;
    return css;
  }

  function cellConflittoStyle(key) {
    const conflitti = localAss[key]?.conflitti ?? [];
    if (!conflitti.length) return '';

    let bestStile = null;
    let bestOrd = -1;

    for (const c of conflitti) {
      const ord = CATEGORIA_ORDINE[c.categoria] ?? 0;
      if (ord > bestOrd) { bestOrd = ord; bestStile = c.stile; }
    }

    return bestStile ? _stileToCss(bestStile) : '';
  }

  function cellClass(key, g) {
    const t = tipoGiorno(g);
    return t === 'superfestivo' ? 'gc-super' : t === 'festivo' ? 'gc-fest' : '';
  }

  function isEffettivoMod(key) {
    if (!isEffettivo) return false;
    const a = localAss[key];
    if (!a) return false;
    const uid = a.user_id;
    const orig = a.originale_user_id;
    if (uid == null && orig == null) return false;
    return uid !== orig;
  }

  /** Mappa turno_id → { apri_festivi, apri_superfestivi, aperture_straordinarie } */
  let _turnoApertureMap = $derived.by(() => {
    if (!struttura?.sovragruppi) return {};
    const map = {};
    for (const sg of struttura.sovragruppi)
      for (const g of sg.gruppi)
        for (const t of g.turni)
          map[t.id] = {
            apri_festivi: t.apri_festivi || 0,
            apri_superfestivi: t.apri_superfestivi || 0,
            aperture_straordinarie: new Set(t.aperture_straordinarie || []),
          };
    return map;
  });

  function isCellaChiusa(turnoId, giorno) {
    const info = _turnoApertureMap[turnoId];
    if (!info) return false;
    if (info.aperture_straordinarie.has(giorno)) return false;
    const tipo = tipoGiorno(giorno);
    if (tipo === 'festivo' && !info.apri_festivi) return true;
    if (tipo === 'superfestivo' && !info.apri_superfestivi) return true;
    return false;
  }

  // ── Accesso manager — turni inaccessibili ──────────────────
  let _turnoAccessMap = $derived.by(() => {
    if (!struttura?.sovragruppi) return {};
    const map = {};
    for (const sg of struttura.sovragruppi)
      for (const g of sg.gruppi)
        for (const t of g.turni)
          map[t.id] = t.accessibile !== false;
    return map;
  });

  let _utentiAccessibili = $derived(struttura?.utenti_accessibili ?? null);

  let accessoInfo = $derived(struttura?.accesso_info ?? null);

  function isTurnoInaccessibile(turnoId) {
    return _turnoAccessMap[turnoId] === false;
  }

  let _utentiAccSet = $derived(_utentiAccessibili ? new Set(_utentiAccessibili) : null);

  function isUtenteAccessibile(uid) {
    if (!_utentiAccSet) return true;
    return _utentiAccSet.has(uid);
  }

  function nomeGiorno(g) {
    if (!struttura?.calendario) return '';
    const { anno, mese } = struttura.calendario;
    return NOMI_GG[new Date(anno, mese - 1, g).getDay()];
  }

  function selectVal(key) {
    const uid = localAss[key]?.user_id;
    return uid != null ? String(uid) : '';
  }

  async function salvaWorkingDes(userId, giorno, tipoId) {
    const r = await managerApi.setWorkingDes(calId, {
      user_id:          userId,
      giorno,
      tipo_richiesta_id: tipoId || null,
      note:             null,
    });
    if (r.ok) {
      if (r.wd_history) wdHistory = r.wd_history;
      const rwd = await managerApi.getWorkingDes(calId);
      if (rwd.ok) wdFull = rwd.working_desiderata ?? [];
      // Aggiorna conflitti celle impattate dal cambio WD
      if (r.vicini?.length) {
        let updated = { ...localAss };
        for (const v of r.vicini) {
          const vk = `${v.turno_id}-${v.giorno}`;
          if (updated[vk]) updated[vk] = { ...updated[vk], conflitti: v.conflitti };
        }
        localAss = updated;
      }
    } else {
      showToast(r.errore ?? 'Errore nel salvataggio.', true);
    }
  }

  // ── WD Undo / Redo ──────────────────────────────────────────
  async function doWdUndo() {
    if (isReadOnly) return;
    const r = await managerApi.wdUndo(calId);
    if (r.ok) {
      if (r.wd_history) wdHistory = r.wd_history;
      const rwd = await managerApi.getWorkingDes(calId);
      if (rwd.ok) wdFull = rwd.working_desiderata ?? [];
      showToast('Undo WD');
    } else {
      showToast(r.errore, true);
    }
  }

  async function doWdRedo() {
    if (isReadOnly) return;
    const r = await managerApi.wdRedo(calId);
    if (r.ok) {
      if (r.wd_history) wdHistory = r.wd_history;
      const rwd = await managerApi.getWorkingDes(calId);
      if (rwd.ok) wdFull = rwd.working_desiderata ?? [];
      showToast('Redo WD');
    } else {
      showToast(r.errore, true);
    }
  }

  async function ricaricaDesiderataOriginali() {
    if (!confirm('Attenzione: tutte le modifiche ai working desiderata saranno azzerate e verranno ripristinati i desiderata originali.\n\nContinuare?')) return;
    const r = await managerApi.ricaricaWd(calId);
    if (r.ok) {
      if (r.wd_history) wdHistory = r.wd_history;
      const rwd = await managerApi.getWorkingDes(calId);
      if (rwd.ok) wdFull = rwd.working_desiderata ?? [];
      showToast(r.messaggio ?? 'Desiderata originali ricaricati.');
    } else {
      showToast(r.errore ?? 'Errore.', true);
    }
  }

  // ── Context menu assegnazione lavoratore ─────────────────────
  let assMenu = $state(null); // { x, y, turnoId, giorno, turnoSigla }
  let assColHidden = $state({}); // { 'wd': true, 'des': false, ... } — colonne nascoste

  // Mappa derivata: per ogni giorno, per ogni utente → { wd, des, disponibile }
  // Usa wdMap e desMap già esistenti
  function getDisponibilita(giorno) {
    const congelati = !!struttura?.calendario?.desiderata_congelati;
    return utentiBasic.filter(u => isUtenteAccessibile(u.id)).map(u => {
      const wd = wdMap[u.id]?.[giorno] ?? null;
      const des = desMap[u.id]?.[giorno] ?? null;
      // Dopo congelamento: solo WD fa fede (se rimosso = disponibile)
      // Prima: solo desiderata originali
      const ref = congelati ? wd : des;
      const disponibile = !ref || ref.req_tipo !== 'assenza';
      return {
        user_id: u.id, sigla: u.sigla,
        disponibile,
        wd_sigla: wd?.req_sigla ?? null,
        wd_tipo: wd?.req_tipo ?? null,
        wd_note: wd?.note ?? null,
        des_sigla: des?.req_sigla ?? null,
        des_tipo: des?.req_tipo ?? null,
        des_note: des?.note ?? null,
      };
    }).sort((a, b) => {
      if (a.disponibile !== b.disponibile) return a.disponibile ? -1 : 1;
      return a.sigla.localeCompare(b.sigla);
    });
  }

  function isDisponibile(userId, giorno) {
    const congelati = !!struttura?.calendario?.desiderata_congelati;
    const ref = congelati ? (wdMap[userId]?.[giorno] ?? null) : (desMap[userId]?.[giorno] ?? null);
    return !ref || ref.req_tipo !== 'assenza';
  }

  let forzaInserimento = $state(false);

  function onCellContextMenu(e, turnoId, giorno, turnoSigla) {
    e.preventDefault();
    forzaInserimento = false;
    assMenu = { x: e.clientX, y: e.clientY, turnoId, giorno, turnoSigla };
  }

  function closeAssMenu() { assMenu = null; }

  function assMenuChangeDay(delta) {
    if (!assMenu) return;
    const newG = assMenu.giorno + delta;
    if (newG < 1 || newG > numGiorni) return;
    assMenu = { ...assMenu, giorno: newG };
  }

  function assegnaUtente(userId, disponibile) {
    if (!assMenu) return;
    if (userId && !disponibile && !forzaInserimento) return;
    onCellChange(assMenu.turnoId, assMenu.giorno, userId ? String(userId) : '');
    assMenu = null;
  }

  // Drag del context menu assegnazione
  let assDragging = $state(false);
  function onAssDragStart(e) {
    assDragging = true;
    const startX = e.clientX, startY = e.clientY;
    const origX = assMenu.x, origY = assMenu.y;
    function onMove(ev) {
      assMenu = { ...assMenu, x: origX + ev.clientX - startX, y: origY + ev.clientY - startY };
    }
    function onUp() {
      assDragging = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  // ── Multi-selezione celle ──────────────────────────────────
  let selectedCells = $state(new Set());   // Set<"turnoId-giorno">
  let selAnchor = $state(null);            // { turnoId, giorno }
  let selEnd = $state(null);              // angolo opposto per Shift+Freccia

  // ── Clipboard copia/incolla ────────────────────────────────
  // type: 'griglia' → cells: [{dTurnoIdx, dGiorno, userId}]
  // type: 'wd'      → cells: [{dUserIdx, dGiorno, tipoId}]
  let clipboard = $state(null);

  // ── Cella con cursore tastiera (stile Excel) ───────────────
  let focusedCell = $state(null);    // { turnoId, giorno } — griglia
  let focusedWdCell = $state(null);  // { userId, giorno }  — WD

  // Opzioni dropdown WD (dipendono solo da tipi, non dal giorno)
  let wdCellOptions = $derived([
    { value: '', label: '—' },
    ...tipi.filter(t => t.tipo === 'lavorativo').map(t => ({ value: String(t.id), label: t.sigla })),
    ...tipi.filter(t => t.tipo === 'assenza').map(t => ({ value: String(t.id), label: t.sigla })),
  ]);

  let orderedTurnoIds = $derived(
    (struttura?.sovragruppi ?? []).flatMap(sg =>
      sg.gruppi.flatMap(g => g.turni.map(t => t.id))
    )
  );

  // ── Drag & drop celle (long press) ──────────────────────────
  let dragSource = $state(null);  // { turnoId, giorno, key }
  let dragTarget = $state(null);  // { turnoId, giorno, key }
  let dragTimer = null;

  function onCellPointerDown(e, turnoId, giorno, bloccata = false) {
    if (e.button !== 0) return;

    // ── Multi-select: Ctrl+Click o Shift+Click ──
    if (e.ctrlKey || e.metaKey) {
      if (bloccata) return;
      e.preventDefault(); e.stopPropagation();
      if (document.activeElement?.tagName === 'SELECT') document.activeElement.blur();
      toggleCellSelection(turnoId, giorno);
      return;
    }
    if (e.shiftKey) {
      if (bloccata) return;
      e.preventDefault(); e.stopPropagation();
      if (document.activeElement?.tagName === 'SELECT') document.activeElement.blur();
      selectRectangle(turnoId, giorno);
      return;
    }

    // ── Click normale: imposta focused cell, resetta selezione ──
    if (selectedCells.size > 0) clearSelection();
    if (!bloccata) {
      focusedCell = { turnoId, giorno };
      selAnchor = { turnoId, giorno };
      focusedWdCell = null;
    }

    if (bloccata) return;

    // ── Drag logic esistente ──
    const key = `${turnoId}-${giorno}`;
    const userId = localAss[key]?.user_id;
    if (!userId) return;

    // Se il click è sul pulsante ▾ del CellEditor non avviare drag
    if (e.target.closest('.ce-btn')) return;

    dragTimer = setTimeout(() => {
      dragSource = { turnoId, giorno, key };
      dragTarget = null;
      document.body.classList.add('cell-dragging');
    }, 350);

    // Listener globale per pointerup (caso in cui rilascio fuori dalla griglia)
    function globalUp() {
      onCellPointerUp();
      window.removeEventListener('pointerup', globalUp);
    }
    window.addEventListener('pointerup', globalUp);
  }

  function onCellPointerUp() {
    if (dragTimer) { clearTimeout(dragTimer); dragTimer = null; }
    if (dragSource && dragTarget && dragSource.key !== dragTarget.key) {
      swapOrMove(dragSource, dragTarget);
    }
    document.body.classList.remove('cell-dragging');
    dragSource = null;
    dragTarget = null;
  }

  function onCellPointerEnter(turnoId, giorno) {
    if (!dragSource) return;
    const key = `${turnoId}-${giorno}`;
    dragTarget = { turnoId, giorno, key };
  }

  function onCellPointerCancel() {
    if (dragTimer) { clearTimeout(dragTimer); dragTimer = null; }
    document.body.classList.remove('cell-dragging');
    dragSource = null;
    dragTarget = null;
  }

  // ── Multi-selezione: helpers ────────────────────────────────
  function clearSelection() {
    if (selectedCells.size === 0) return;
    selectedCells = new Set();
    selAnchor = null;
    selEnd = null;
  }

  function toggleCellSelection(turnoId, giorno) {
    const key = `${turnoId}-${giorno}`;
    const next = new Set(selectedCells);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    selectedCells = next;
    selAnchor = { turnoId, giorno };
  }

  function selectRectangle(turnoId, giorno) {
    if (!selAnchor) { toggleCellSelection(turnoId, giorno); return; }
    const idxA = orderedTurnoIds.indexOf(selAnchor.turnoId);
    const idxB = orderedTurnoIds.indexOf(turnoId);
    const minT = Math.min(idxA, idxB), maxT = Math.max(idxA, idxB);
    const minG = Math.min(selAnchor.giorno, giorno), maxG = Math.max(selAnchor.giorno, giorno);
    const next = new Set();
    for (let ti = minT; ti <= maxT; ti++) {
      const tId = orderedTurnoIds[ti];
      for (let g = minG; g <= maxG; g++) {
        if (isCellaChiusa(tId, g) || isTurnoInaccessibile(tId) || isCellaBloccata(tId, g)) continue;
        next.add(`${tId}-${g}`);
      }
    }
    selectedCells = next;
  }

  // ── Opzioni dropdown griglia (per cella) ────────────────────
  function gridCellOptions(g, curVal) {
    const opts = [{ value: '', label: '—' }];
    for (const u of utenti) {
      if (!isUtenteAccessibile(u.id) && String(u.id) !== curVal) continue;
      const disp = isDisponibile(u.id, g);
      opts.push({ value: String(u.id), label: u.sigla, disabled: !disp && String(u.id) !== curVal });
    }
    return opts;
  }

  // ── Navigazione tastiera — griglia ──────────────────────────
  function moveGridFocus(dir) {
    if (!focusedCell) return;
    const tIdx = orderedTurnoIds.indexOf(focusedCell.turnoId);
    let nextTIdx = tIdx, nextG = focusedCell.giorno;

    if (dir === 'down' || dir === 'tab')      nextTIdx = Math.min(tIdx + 1, orderedTurnoIds.length - 1);
    else if (dir === 'up' || dir === 'tab-back') nextTIdx = Math.max(tIdx - 1, 0);
    else if (dir === 'right')                 nextG = Math.min(nextG + 1, numGiorni);
    else if (dir === 'left')                  nextG = Math.max(nextG - 1, 1);

    const nextTurnoId = orderedTurnoIds[nextTIdx];
    if (!nextTurnoId || isTurnoInaccessibile(nextTurnoId)) return;
    if (isCellaChiusa(nextTurnoId, nextG) || isCellaBloccata(nextTurnoId, nextG)) return;

    focusedCell = { turnoId: nextTurnoId, giorno: nextG };
    selAnchor = { turnoId: nextTurnoId, giorno: nextG };
    selEnd = null;
    clearSelection();
    selectedWdCells = new Set();
    focusedWdCell = null;
  }

  function onCellConfirm(turnoId, giorno) {
    const tIdx = orderedTurnoIds.indexOf(turnoId);
    const nextTIdx = Math.min(tIdx + 1, orderedTurnoIds.length - 1);
    if (nextTIdx === tIdx) return;
    const nextTurnoId = orderedTurnoIds[nextTIdx];
    if (!nextTurnoId || isTurnoInaccessibile(nextTurnoId)) return;
    if (isCellaChiusa(nextTurnoId, giorno) || isCellaBloccata(nextTurnoId, giorno)) return;
    focusedCell = { turnoId: nextTurnoId, giorno };
    selAnchor = { turnoId: nextTurnoId, giorno };
    clearSelection();
  }

  // ── Navigazione tastiera — WD ────────────────────────────────
  function moveWdFocus(dir) {
    if (!focusedWdCell) return;
    const d = _remapDesDir(dir);
    const userIds = utentiBasic.map(u => u.id);
    const uIdx = userIds.indexOf(focusedWdCell.userId);
    let nextUIdx = uIdx, nextG = focusedWdCell.giorno;

    if (d === 'down' || d === 'tab')         nextUIdx = Math.min(uIdx + 1, userIds.length - 1);
    else if (d === 'up' || d === 'tab-back')  nextUIdx = Math.max(uIdx - 1, 0);
    else if (d === 'right')                   nextG = Math.min(nextG + 1, numGiorni);
    else if (d === 'left')                    nextG = Math.max(nextG - 1, 1);

    const nextUserId = userIds[nextUIdx];
    if (!nextUserId || !isUtenteAccessibile(nextUserId)) return;
    focusedWdCell = { userId: nextUserId, giorno: nextG };
    wdSelAnchor = { userId: nextUserId, giorno: nextG };
    wdSelEnd = null;
    clearWdSelection();
    selectedCells = new Set();
    focusedCell = null;
  }

  function onWdCellConfirm(userId, giorno) {
    const userIds = utentiBasic.map(u => u.id);
    const uIdx = userIds.indexOf(userId);
    const nextUIdx = Math.min(uIdx + 1, userIds.length - 1);
    if (nextUIdx === uIdx) return;
    const nextUserId = userIds[nextUIdx];
    if (!nextUserId || !isUtenteAccessibile(nextUserId)) return;
    focusedWdCell = { userId: nextUserId, giorno };
    wdSelAnchor = { userId: nextUserId, giorno };
    clearWdSelection();
  }

  // ── Paste da Excel (clipboard di sistema, TSV) ───────────────
  function onGlobalPaste(e) {
    // Solo se una cella è focused e il focus non è in un input/textarea
    if (document.activeElement?.tagName === 'INPUT' || document.activeElement?.tagName === 'TEXTAREA') return;

    if (focusedCell && vista === 'griglia') {
      if (trasposto) { showToast('Incolla da Excel non disponibile in vista trasposta.', true); return; }
      e.preventDefault();
      const celle = _parseExcelPasteGrid(e.clipboardData.getData('text/plain'));
      if (celle.length > 0) _eseguiPasteGriglia(celle);
    } else if (focusedWdCell && vista === 'working') {
      e.preventDefault();
      const celle = _parseExcelPasteWd(e.clipboardData.getData('text/plain'));
      if (celle.length > 0) _eseguiPasteWd(celle);
    }
  }

  function _parseExcelPasteGrid(tsv) {
    const rows = tsv.split('\n').map(r => r.replace(/\r$/, '')).filter(r => r !== '');
    const tIdx = orderedTurnoIds.indexOf(focusedCell.turnoId);
    const celle = [];
    for (let ri = 0; ri < rows.length; ri++) {
      for (let ci = 0; ci < rows[ri].split('\t').length; ci++) {
        const text = rows[ri].split('\t')[ci].trim();
        const nTIdx = tIdx + ri, nG = focusedCell.giorno + ci;
        if (nTIdx >= orderedTurnoIds.length || nG < 1 || nG > numGiorni) continue;
        const turnoId = orderedTurnoIds[nTIdx];
        if (isTurnoInaccessibile(turnoId) || isCellaChiusa(turnoId, nG) || isCellaBloccata(turnoId, nG)) continue;
        const u = text === '' ? null : utenti.find(u => u.sigla.toLowerCase() === text.toLowerCase());
        celle.push({ turno_id: turnoId, giorno: nG, user_id: u?.id ?? null });
      }
    }
    return celle;
  }

  function _parseExcelPasteWd(tsv) {
    const rows = tsv.split('\n').map(r => r.replace(/\r$/, '')).filter(r => r !== '');
    const userIds = utentiBasic.map(u => u.id);
    const uIdx = userIds.indexOf(focusedWdCell.userId);
    const celle = [];
    for (let ri = 0; ri < rows.length; ri++) {
      for (let ci = 0; ci < rows[ri].split('\t').length; ci++) {
        const text = rows[ri].split('\t')[ci].trim();
        const nUIdx = uIdx + ri, nG = focusedWdCell.giorno + ci;
        if (nUIdx >= userIds.length || nG < 1 || nG > numGiorni) continue;
        if (!isUtenteAccessibile(userIds[nUIdx])) continue;
        const t = text === '' ? null : tipi.find(t => t.sigla.toLowerCase() === text.toLowerCase());
        if (text !== '' && !t) continue; // sigla non trovata → skip
        celle.push({ user_id: userIds[nUIdx], giorno: nG, tipo_richiesta_id: t?.id ?? null });
      }
    }
    return celle;
  }

  // ── Selezione estesa con Shift+Freccia ──────────────────────
  function extendGridSelection(dir) {
    if (!selAnchor) return;
    const curEnd = selEnd ?? selAnchor;
    let endTIdx = orderedTurnoIds.indexOf(curEnd.turnoId);
    let endG = curEnd.giorno;

    if (dir === 'down')  endTIdx = Math.min(endTIdx + 1, orderedTurnoIds.length - 1);
    if (dir === 'up')    endTIdx = Math.max(endTIdx - 1, 0);
    if (dir === 'right') endG = Math.min(endG + 1, numGiorni);
    if (dir === 'left')  endG = Math.max(endG - 1, 1);

    const endTurnoId = orderedTurnoIds[endTIdx];
    if (!endTurnoId) return;
    selEnd = { turnoId: endTurnoId, giorno: endG };
    selectRectangle(selEnd.turnoId, selEnd.giorno); // usa selAnchor come anchor fisso
  }

  function extendWdSelection(dir) {
    if (!wdSelAnchor) return;
    const d = _remapDesDir(dir);
    const userIds = utentiBasic.map(u => u.id);
    const curEnd = wdSelEnd ?? wdSelAnchor;
    let endUIdx = userIds.indexOf(curEnd.userId);
    let endG = curEnd.giorno;

    if (d === 'down')  endUIdx = Math.min(endUIdx + 1, userIds.length - 1);
    if (d === 'up')    endUIdx = Math.max(endUIdx - 1, 0);
    if (d === 'right') endG = Math.min(endG + 1, numGiorni);
    if (d === 'left')  endG = Math.max(endG - 1, 1);

    const endUserId = userIds[endUIdx];
    if (!endUserId) return;
    wdSelEnd = { userId: endUserId, giorno: endG };
    selectWdRectangle(wdSelEnd.userId, wdSelEnd.giorno);
  }

  // ── Taglia celle ─────────────────────────────────────────────
  async function cutSelected() {
    if (isReadOnly) return;
    if (selectedCells.size === 0 && !focusedCell) return;
    if (selectedCells.size === 0 && focusedCell) {
      toggleCellSelection(focusedCell.turnoId, focusedCell.giorno);
    }
    copySelected(); // copia in clipboard (mostra toast "copiate")
    await bulkClearSelected(); // svuota con history step
    showToast('Tagliato');
  }

  async function cutSelectedWd() {
    if (selectedWdCells.size === 0 && !focusedWdCell) return;
    if (selectedWdCells.size === 0 && focusedWdCell) {
      toggleWdSelection(focusedWdCell.userId, focusedWdCell.giorno);
    }
    copySelectedWd();
    await bulkClearWd();
    showToast('Tagliato');
  }

  // ── Copia celle griglia ─────────────────────────────────────
  function copySelected() {
    let keys;
    if (selectedCells.size > 0) {
      keys = Array.from($state.snapshot(selectedCells));
    } else if (focusedCell) {
      keys = [`${focusedCell.turnoId}-${focusedCell.giorno}`];
    } else {
      return;
    }

    // Calcola offset relativo rispetto alla cella in alto a sinistra
    const parsed = keys.map(k => {
      const [turnoId, giorno] = k.split('-').map(Number);
      return { turnoId, giorno, turnoIdx: orderedTurnoIds.indexOf(turnoId) };
    });
    const minTurnoIdx = Math.min(...parsed.map(p => p.turnoIdx));
    const minGiorno = Math.min(...parsed.map(p => p.giorno));

    const cells = parsed.map(p => ({
      dTurnoIdx: p.turnoIdx - minTurnoIdx,
      dGiorno:   p.giorno - minGiorno,
      userId:    localAss[`${p.turnoId}-${p.giorno}`]?.user_id ?? null,
    }));

    clipboard = { type: 'griglia', cells };
    showToast(`${keys.length} cell${keys.length === 1 ? 'a' : 'e'} copiat${keys.length === 1 ? 'a' : 'e'}`);
  }

  // ── Incolla celle griglia ────────────────────────────────────
  async function pasteSelected() {
    if (!clipboard || clipboard.type !== 'griglia') return;
    if (isReadOnly) return;

    // Ancora di incolla: top-left della selezione corrente (o selAnchor se nessuna selezione)
    let anchorTurnoIdx, anchorGiorno;
    if (selectedCells.size > 0) {
      const keys = Array.from($state.snapshot(selectedCells));
      const parsed = keys.map(k => {
        const [tId, g] = k.split('-').map(Number);
        return { turnoIdx: orderedTurnoIds.indexOf(tId), giorno: g };
      });
      anchorTurnoIdx = Math.min(...parsed.map(p => p.turnoIdx));
      anchorGiorno   = Math.min(...parsed.map(p => p.giorno));
    } else if (selAnchor) {
      anchorTurnoIdx = orderedTurnoIds.indexOf(selAnchor.turnoId);
      anchorGiorno   = selAnchor.giorno;
    } else if (focusedCell) {
      anchorTurnoIdx = orderedTurnoIds.indexOf(focusedCell.turnoId);
      anchorGiorno   = focusedCell.giorno;
    } else {
      return;
    }

    const maxGiorno = numGiorni || 31;
    const cells = $state.snapshot(clipboard.cells);

    // Broadcast (1 cella copiata): riempi tutte le celle selezionate con lo stesso userId
    if (cells.length === 1 && selectedCells.size > 1) {
      const userId = cells[0].userId;
      const selKeys = Array.from($state.snapshot(selectedCells));
      const celle = selKeys.map(k => {
        const [turnoId, giorno] = k.split('-').map(Number);
        return { turno_id: turnoId, giorno, user_id: userId };
      }).filter(c => !isCellaChiusa(c.turno_id, c.giorno) && !isTurnoInaccessibile(c.turno_id));
      if (celle.length > 0) await _eseguiPasteGriglia(celle);
      return;
    }

    // Paste relativo: ogni cella della clipboard → posizione relativa dall'ancora
    const celle = [];
    for (const cell of cells) {
      const tIdx = anchorTurnoIdx + cell.dTurnoIdx;
      const giorno = anchorGiorno + cell.dGiorno;
      if (tIdx < 0 || tIdx >= orderedTurnoIds.length) continue;
      if (giorno < 1 || giorno > maxGiorno) continue;
      const turnoId = orderedTurnoIds[tIdx];
      if (isCellaChiusa(turnoId, giorno) || isTurnoInaccessibile(turnoId)) continue;
      celle.push({ turno_id: turnoId, giorno, user_id: cell.userId });
    }
    if (celle.length > 0) await _eseguiPasteGriglia(celle);
  }

  async function _eseguiPasteGriglia(celle) {
    const r = await managerApi.salvaBatch(calId, celle);
    if (r.ok) {
      if (r.bloccate?.length > 0) {
        const n = r.bloccate.length;
        const forza = confirm(`${n} cell${n === 1 ? 'a' : 'e'} blocat${n === 1 ? 'a' : 'e'} da regole.\nForzare l'inserimento?`);
        if (forza) {
          const bloccateKeys = new Set(r.bloccate.map(b => `${b.turno_id}-${b.giorno}`));
          const celleForzate = celle.filter(c => bloccateKeys.has(`${c.turno_id}-${c.giorno}`));
          await managerApi.salvaBatch(calId, celleForzate, true);
        }
      }
      if (r.history) history = r.history;
      await caricaCalendarioSilent(calId);
    } else {
      showToast(r.errore ?? 'Errore incolla.', true);
    }
  }

  // ── Copia celle WD ───────────────────────────────────────────
  function copySelectedWd() {
    let keys;
    if (selectedWdCells.size > 0) {
      keys = Array.from($state.snapshot(selectedWdCells));
    } else if (focusedWdCell) {
      keys = [`${focusedWdCell.userId}-${focusedWdCell.giorno}`];
    } else {
      return;
    }

    const userIds = utentiBasic.map(u => u.id);
    const parsed = keys.map(k => {
      const [userId, giorno] = k.split('-').map(Number);
      return { userId, giorno, userIdx: userIds.indexOf(userId) };
    });
    const minUserIdx = Math.min(...parsed.map(p => p.userIdx));
    const minGiorno  = Math.min(...parsed.map(p => p.giorno));

    const cells = parsed.map(p => ({
      dUserIdx: p.userIdx - minUserIdx,
      dGiorno:  p.giorno - minGiorno,
      tipoId:   wdMap[p.userId]?.[p.giorno]?.tipo_richiesta_id ?? null,
    }));

    clipboard = { type: 'wd', cells };
    showToast(`${keys.length} cell${keys.length === 1 ? 'a' : 'e'} WD copiat${keys.length === 1 ? 'a' : 'e'}`);
  }

  // ── Incolla celle WD ─────────────────────────────────────────
  async function pasteSelectedWd() {
    if (!clipboard || clipboard.type !== 'wd') return;

    const userIds = utentiBasic.map(u => u.id);
    let anchorUserIdx, anchorGiorno;

    if (selectedWdCells.size > 0) {
      const keys = Array.from($state.snapshot(selectedWdCells));
      const parsed = keys.map(k => {
        const [uid, g] = k.split('-').map(Number);
        return { userIdx: userIds.indexOf(uid), giorno: g };
      });
      anchorUserIdx = Math.min(...parsed.map(p => p.userIdx));
      anchorGiorno  = Math.min(...parsed.map(p => p.giorno));
    } else if (wdSelAnchor) {
      anchorUserIdx = userIds.indexOf(wdSelAnchor.userId);
      anchorGiorno  = wdSelAnchor.giorno;
    } else if (focusedWdCell) {
      anchorUserIdx = userIds.indexOf(focusedWdCell.userId);
      anchorGiorno  = focusedWdCell.giorno;
    } else {
      return;
    }

    const maxGiorno = numGiorni || 31;
    const cells = $state.snapshot(clipboard.cells);

    // Broadcast (1 cella copiata): riempi tutte le celle selezionate con lo stesso tipoId
    if (cells.length === 1 && selectedWdCells.size > 1) {
      const tipoId = cells[0].tipoId;
      const selKeys = Array.from($state.snapshot(selectedWdCells));
      const celle = selKeys.map(k => {
        const [userId, giorno] = k.split('-').map(Number);
        return { user_id: userId, giorno, tipo_richiesta_id: tipoId };
      });
      if (celle.length > 0) await _eseguiPasteWd(celle);
      return;
    }

    // Paste relativo
    const celle = [];
    for (const cell of cells) {
      const uIdx = anchorUserIdx + cell.dUserIdx;
      const giorno = anchorGiorno + cell.dGiorno;
      if (uIdx < 0 || uIdx >= userIds.length) continue;
      if (giorno < 1 || giorno > maxGiorno) continue;
      celle.push({ user_id: userIds[uIdx], giorno, tipo_richiesta_id: cell.tipoId });
    }
    if (celle.length > 0) await _eseguiPasteWd(celle);
  }

  async function _eseguiPasteWd(celle) {
    const r = await managerApi.salvaBatchWd(calId, celle);
    if (r.ok) {
      if (r.wd_history) wdHistory = r.wd_history;
      const rwd = await managerApi.getWorkingDes(calId);
      if (rwd.ok) wdFull = rwd.working_desiderata ?? [];
    } else {
      showToast(r.errore ?? 'Errore incolla WD.', true);
    }
  }

  async function bulkClearSelected() {
    if (selectedCells.size === 0) return;
    // $state.snapshot per uscire dal proxy Svelte 5 e iterare in modo affidabile
    const keys = Array.from($state.snapshot(selectedCells));
    clearSelection();

    // Update ottimistico + raccolta celle da svuotare
    let updatedAss = $state.snapshot(localAss);
    let updatedSync = $state.snapshot(syncStatus);
    const celle = [];
    for (const key of keys) {
      const [turnoId, giorno] = key.split('-').map(Number);
      const prev = updatedAss[key] ?? null;
      if (prev?.user_id == null) continue; // gia' vuota
      updatedAss[key] = { user_id: null, conflitti: [] };
      updatedSync[key] = 'saving';
      celle.push({ turno_id: turnoId, giorno, key });
    }
    if (celle.length === 0) return;
    localAss = updatedAss;
    syncStatus = updatedSync;

    try {
      const payload = celle.map(c => ({ turno_id: c.turno_id, giorno: c.giorno }));
      const r = await managerApi.svuotaBatch(calId, payload);
      if (r.ok) {
        if (r.svuotate < celle.length) {
          showToast(`Svuotate ${r.svuotate}/${celle.length} celle (alcune non accessibili).`, true);
        }
        // Sync OK: aggiorna history e ricarica conflitti
        if (r.history) history = r.history;
        // Ricarica struttura per aggiornare conflitti vicini
        const rs = await managerApi.getStruttura(calId);
        if (rs.ok) {
          struttura = rs;
          initLocalAss(rs.assegnazioni ?? []);
        }
      } else {
        showToast(r.errore ?? 'Errore svuotamento batch.', true);
        // Rollback: ricarica tutto
        await caricaCalendarioSilent(calId);
      }
    } catch (e) {
      showToast(`Errore di rete: ${e.message}`, true);
      await caricaCalendarioSilent(calId);
    }
    // Pulisci sync dots
    let cleanSync = $state.snapshot(syncStatus);
    for (const c of celle) cleanSync[c.key] = '';
    syncStatus = cleanSync;
  }

  function onGlobalKeyDown(e) {
    // Le frecce/tastiera quando una cella è focused sono gestite da CellEditor; il global handler non le tocca
    if (e.key === 'Escape') { clearSelection(); clearWdSelection(); focusedCell = null; focusedWdCell = null; }
    else if (e.key === 'Delete' || e.key === 'Backspace') {
      if (selectedCells.size > 0) { e.preventDefault(); e.stopPropagation(); bulkClearSelected(); }
      else if (selectedWdCells.size > 0) { e.preventDefault(); e.stopPropagation(); bulkClearWd(); }
    }
    // Ctrl+C — copia selezione corrente (o cella focused)
    else if ((e.ctrlKey || e.metaKey) && e.key === 'c') {
      if (selectedCells.size > 0 || focusedCell) { e.preventDefault(); copySelected(); }
      else if (selectedWdCells.size > 0 || focusedWdCell) { e.preventDefault(); copySelectedWd(); }
    }
    // Ctrl+X — taglia selezione corrente (o cella focused)
    else if ((e.ctrlKey || e.metaKey) && e.key === 'x') {
      if (!isReadOnly && (selectedCells.size > 0 || focusedCell)) { e.preventDefault(); e.stopPropagation(); cutSelected(); }
      else if (selectedWdCells.size > 0 || focusedWdCell) { e.preventDefault(); e.stopPropagation(); cutSelectedWd(); }
    }
    // Ctrl+V — incolla clipboard
    else if ((e.ctrlKey || e.metaKey) && e.key === 'v') {
      if (clipboard?.type === 'griglia' && (selectedCells.size > 0 || selAnchor || focusedCell)) {
        e.preventDefault(); pasteSelected();
      } else if (clipboard?.type === 'wd' && (selectedWdCells.size > 0 || wdSelAnchor || focusedWdCell)) {
        e.preventDefault(); pasteSelectedWd();
      }
    }
    // Ctrl+Z / Ctrl+Y — undo/redo per vista corrente
    else if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
      e.preventDefault();
      if (vista === 'working') doWdUndo();
      else doUndo();
    }
    else if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
      e.preventDefault();
      if (vista === 'working') doWdRedo();
      else doRedo();
    }
  }

  function onDocumentPointerDown(e) {
    if (selectedCells.size > 0) {
      if (!(e.ctrlKey || e.metaKey || e.shiftKey) && !e.target.closest('td.cella')) clearSelection();
    }
    if (selectedWdCells.size > 0) {
      if (!(e.ctrlKey || e.metaKey || e.shiftKey) && !e.target.closest('td.des-cell')) clearWdSelection();
    }
    // Reset focused cell se si clicca fuori dalle celle editabili
    if (!e.target.closest('td.cella') && !e.target.closest('.ce-list')) focusedCell = null;
    if (!e.target.closest('td.des-cell') && !e.target.closest('.ce-list')) focusedWdCell = null;
  }

  // ── Multi-selezione working desiderata ──────────────────────
  let selectedWdCells = $state(new Set());   // Set<"userId-giorno">
  let wdSelAnchor = $state(null);            // { userId, giorno }
  let wdSelEnd = $state(null);              // angolo opposto per Shift+Freccia

  function clearWdSelection() {
    if (selectedWdCells.size === 0) return;
    selectedWdCells = new Set();
    wdSelAnchor = null;
    wdSelEnd = null;
  }

  function toggleWdSelection(userId, giorno) {
    const key = `${userId}-${giorno}`;
    const next = new Set(selectedWdCells);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    selectedWdCells = next;
    wdSelAnchor = { userId, giorno };
  }

  function selectWdRectangle(userId, giorno) {
    if (!wdSelAnchor) { toggleWdSelection(userId, giorno); return; }
    const userIds = utentiBasic.map(u => u.id);
    const idxA = userIds.indexOf(wdSelAnchor.userId);
    const idxB = userIds.indexOf(userId);
    const minU = Math.min(idxA, idxB), maxU = Math.max(idxA, idxB);
    const minG = Math.min(wdSelAnchor.giorno, giorno), maxG = Math.max(wdSelAnchor.giorno, giorno);
    const next = new Set();
    for (let ui = minU; ui <= maxU; ui++) {
      for (let g = minG; g <= maxG; g++) {
        next.add(`${userIds[ui]}-${g}`);
      }
    }
    selectedWdCells = next;
  }

  function onWdCellPointerDown(e, userId, giorno) {
    if (e.button !== 0) return;
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault(); e.stopPropagation();
      if (document.activeElement?.tagName === 'SELECT') document.activeElement.blur();
      toggleWdSelection(userId, giorno);
      return;
    }
    if (e.shiftKey) {
      e.preventDefault(); e.stopPropagation();
      if (document.activeElement?.tagName === 'SELECT') document.activeElement.blur();
      selectWdRectangle(userId, giorno);
      return;
    }
    if (selectedWdCells.size > 0) clearWdSelection();
    // Click normale: imposta focused WD cell
    if (!e.target.closest('.ce-btn')) {
      focusedWdCell = { userId, giorno };
      wdSelAnchor = { userId, giorno };
      focusedCell = null;
    }
  }

  async function bulkClearWd() {
    if (selectedWdCells.size === 0) return;
    const keys = Array.from($state.snapshot(selectedWdCells));
    clearWdSelection();

    const celle = [];
    for (const key of keys) {
      const [userId, giorno] = key.split('-').map(Number);
      const entry = wdMap[userId]?.[giorno];
      if (!entry?.tipo_richiesta_id) continue; // già vuota
      celle.push({ user_id: userId, giorno });
    }
    if (celle.length === 0) return;

    try {
      const r = await managerApi.svuotaBatchWd(calId, celle);
      if (r.ok) {
        if (r.wd_history) wdHistory = r.wd_history;
        const rwd = await managerApi.getWorkingDes(calId);
        if (rwd.ok) wdFull = rwd.working_desiderata ?? [];
      } else {
        showToast(r.errore ?? 'Errore svuotamento batch WD.', true);
      }
    } catch (e) {
      showToast(`Errore di rete: ${e.message}`, true);
    }
  }

  async function swapOrMove(src, tgt) {
    const srcUser = localAss[src.key]?.user_id ?? null;
    if (!srcUser) return;

    // Aggiornamento ottimistico
    const tgtUser = localAss[tgt.key]?.user_id ?? null;
    const prevSrc = localAss[src.key];
    const prevTgt = localAss[tgt.key];
    localAss = {
      ...localAss,
      [tgt.key]: { user_id: srcUser, conflitti: [] },
      [src.key]: { user_id: tgtUser, conflitti: tgtUser ? [] : [] },
    };
    syncStatus = { ...syncStatus, [src.key]: 'saving', [tgt.key]: 'saving' };

    try {
      const r = await managerApi.scambiaAssegnazioni(calId, {
        src_turno_id: src.turnoId, src_giorno: src.giorno,
        tgt_turno_id: tgt.turnoId, tgt_giorno: tgt.giorno,
      });
      if (r.ok) {
        let updated = {
          ...localAss,
          [src.key]: { user_id: r.src.user_id, conflitti: r.src.conflitti },
          [tgt.key]: { user_id: r.tgt.user_id, conflitti: r.tgt.conflitti },
        };
        for (const v of (r.vicini ?? [])) {
          const vk = `${v.turno_id}-${v.giorno}`;
          if (updated[vk]) updated[vk] = { ...updated[vk], conflitti: v.conflitti };
        }
        localAss = updated;
        syncStatus = { ...syncStatus, [src.key]: 'ok', [tgt.key]: 'ok' };
        const rh = await managerApi.getHistory(calId);
        if (rh.ok) history = rh.history;
        setTimeout(() => { syncStatus = { ...syncStatus, [src.key]: '', [tgt.key]: '' }; }, 1200);
      } else {
        // Rollback
        localAss = { ...localAss, [src.key]: prevSrc ?? { user_id: null, conflitti: [] }, [tgt.key]: prevTgt ?? { user_id: null, conflitti: [] } };
        syncStatus = { ...syncStatus, [src.key]: 'err', [tgt.key]: 'err' };
        showToast(r.errore, true);
        setTimeout(() => { syncStatus = { ...syncStatus, [src.key]: '', [tgt.key]: '' }; }, 4000);
      }
    } catch (e) {
      localAss = { ...localAss, [src.key]: prevSrc ?? { user_id: null, conflitti: [] }, [tgt.key]: prevTgt ?? { user_id: null, conflitti: [] } };
      syncStatus = { ...syncStatus, [src.key]: 'err', [tgt.key]: 'err' };
      showToast(`Errore: ${e.message}`, true);
      setTimeout(() => { syncStatus = { ...syncStatus, [src.key]: '', [tgt.key]: '' }; }, 4000);
    }
  }

  // ── Formattazione gruppi ────────────────────────────────────
  // Larghezza prima colonna (ridimensionabile)
  let colTurnoWidth = $state(155);
  let resizing = $state(false);

  function onResizeStart(e) {
    e.preventDefault();
    resizing = true;
    const startX = e.clientX;
    const startW = colTurnoWidth;
    function onMove(ev) {
      colTurnoWidth = Math.max(80, Math.min(400, startW + ev.clientX - startX));
    }
    function onUp() {
      resizing = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      // Salva nel DB
      salvaStyleCalendario();
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  // Auto-width celle in base alla sigla più lunga
  let cellWidth = $derived(Math.max(44, Math.max(...utenti.map(u => u.sigla?.length ?? 2), 3) * 9 + 12));

  // Context menu per formattazione gruppo/sovragruppo
  // tipo: 'gruppo' | 'sovragruppo'
  let ctxMenu = $state(null); // { x, y, item, tipo }
  let ctxStyleSnapshot = $state(null); // snapshot stili all'apertura
  let styleUndoCount = $state(0);      // contatore undo disponibili

  function _snapshotManagerStyles(tipo, item) {
    if (tipo === 'sovragruppo') {
      return {
        itemStyle: JSON.parse(JSON.stringify(item.style ?? {})),
        childStyles: (item.gruppi ?? []).map(g => JSON.parse(JSON.stringify(g.style ?? {})))
      };
    }
    return { itemStyle: JSON.parse(JSON.stringify(item.style ?? {})) };
  }

  function onGruppoContextMenu(e, gruppo) {
    e.preventDefault();
    ctxStyleSnapshot = _snapshotManagerStyles('gruppo', gruppo);
    ctxMenu = { x: e.clientX, y: e.clientY, item: gruppo, tipo: 'gruppo' };
  }

  function onSgContextMenu(e, sg) {
    e.preventDefault();
    ctxStyleSnapshot = _snapshotManagerStyles('sovragruppo', sg);
    ctxMenu = { x: e.clientX, y: e.clientY, item: sg, tipo: 'sovragruppo' };
  }

  function closeCtxMenu() {
    // Rollback: ripristina stili dallo snapshot
    if (ctxStyleSnapshot && ctxMenu) {
      const item = ctxMenu.item;
      item.style = ctxStyleSnapshot.itemStyle;
      if (ctxMenu.tipo === 'sovragruppo' && ctxStyleSnapshot.childStyles) {
        (item.gruppi ?? []).forEach((g, i) => {
          if (ctxStyleSnapshot.childStyles[i]) g.style = ctxStyleSnapshot.childStyles[i];
        });
      }
      struttura = { ...struttura };
    }
    ctxMenu = null;
    ctxStyleSnapshot = null;
  }

  // Editing inline nome gruppo
  let editingGruppo = $state(null); // { sgIdx, gIdx }
  let editingNome = $state('');

  function startEditGruppoNome(sgIdx, gIdx, nome) {
    editingGruppo = { sgIdx, gIdx };
    editingNome = nome;
  }

  function applyGruppoNome() {
    if (!editingGruppo) return;
    // Qui aggiorniamo solo localmente — il nome nel separatore è di sola lettura
    // dallo snapshot, l'utente vede il risultato ma il nome reale non cambia
    editingGruppo = null;
  }

  // Helper: converte oggetto style JS → stringa CSS inline
  // Filtra proprietà custom (--) e valori non stringa (oggetti annidati)
  function toStyleStr(obj) {
    if (!obj || typeof obj !== 'object') return '';
    return Object.entries(obj)
      .filter(([k, v]) => !k.startsWith('--') && typeof v === 'string')
      .map(([k, v]) => `${k.replace(/[A-Z]/g, c => '-' + c.toLowerCase())}:${v} !important`)
      .join(';');
  }

  // Default separatori
  const DEFAULT_SEP_STYLE = { backgroundColor: '#e9ecef', color: '#6c757d', fontStyle: 'italic' };
  const DEFAULT_SG_STYLE = { backgroundColor: '#d6d8db', color: '#1a1a1a', fontWeight: 'bold' };

  // Stile effettivo per il separatore gruppo: default → calendario.style → gruppo.style
  function effectiveStyle(gruppo) {
    const calStyle = struttura?.calendario?.style ?? {};
    const gStyle = gruppo?.style ?? {};
    return { ...DEFAULT_SEP_STYLE, ...calStyle, ...gStyle };
  }

  // Default colonna turni
  const DEFAULT_COL_STYLE = { backgroundColor: '#ffffff', color: '#212529' };

  // Stile effettivo per la colonna turni (prima colonna) di un gruppo
  function effectiveColStyle(gruppo) {
    const colStyle = gruppo?.style?.['--columnStyle'] ?? {};
    return { ...DEFAULT_COL_STYLE, ...colStyle };
  }

  // Colore bordo: --borderColor se impostato, altrimenti backgroundColor,
  // altrimenti il colore bordo-esterno dall'appearance del calendario.
  function gruppoBorderColor(gruppo) {
    const s = effectiveStyle(gruppo);
    return s['--borderColor'] ?? s.backgroundColor ?? (appVals.bordo_esterno_colore ?? '#dee2e6');
  }
  function sgBorderColor(sg) {
    const s = effectiveSgStyle(sg);
    return s['--borderColor'] ?? s.backgroundColor ?? (appVals.bordo_esterno_colore ?? '#dee2e6');
  }
  // Spessore bordo: --borderWidth se impostato, altrimenti spessore dall'appearance.
  function gruppoBorderWidth(gruppo) {
    return (effectiveStyle(gruppo)['--borderWidth'] ?? (appVals.bordo_esterno_spessore ?? 4)) + 'px';
  }
  function sgBorderWidth(sg) {
    return (effectiveSgStyle(sg)['--borderWidth'] ?? (appVals.bordo_esterno_spessore ?? 5)) + 'px';
  }
  // CSS variables per bordi di un gruppo (include SG parent)
  function borderVars(gruppo, sg) {
    return `--g-border:${gruppoBorderColor(gruppo)};--g-width:${gruppoBorderWidth(gruppo)};--sg-border:${sgBorderColor(sg)};--sg-width:${sgBorderWidth(sg)}`;
  }
  function sgBorderVars(sg) {
    return `--sg-border:${sgBorderColor(sg)};--sg-width:${sgBorderWidth(sg)}`;
  }

  // Stile effettivo per un sovragruppo
  function effectiveSgStyle(sg) {
    const sgStyle = sg?.style ?? {};
    return { ...DEFAULT_SG_STYLE, ...sgStyle };
  }

  async function salvaStyleCalendario() {
    await managerApi.setStyleCalendario(calId, { '--colTurnoWidth': colTurnoWidth });
  }

  // Setter locali — solo preview, non salvano nel DB
  function setGruppoStyle(gruppo, prop, value) {
    gruppo.style = { ...(gruppo.style ?? {}), [prop]: value };
    struttura = { ...struttura };
  }

  function toggleRepeatName(item) {
    const current = item.style?.['--repeatName'] ?? false;
    const isSg = ctxMenu?.tipo === 'sovragruppo';
    if (isSg) {
      setSgStyle(item, '--repeatName', !current);
    } else {
      setGruppoStyle(item, '--repeatName', !current);
    }
  }

  // Handler unificato per StyleContextMenu onset(prop, value, tab)
  function onCtxSetProp(prop, value, tab) {
    if (!ctxMenu) return;
    const item = ctxMenu.item;
    const isSg = ctxMenu.tipo === 'sovragruppo';
    if (tab === 'colonna') {
      isSg ? setSgColStyle(item, prop, value) : setGruppoColStyle(item, prop, value);
    } else {
      isSg ? setSgStyle(item, prop, value) : setGruppoStyle(item, prop, value);
    }
  }

  function onCtxBorderSet(prop, value) {
    if (!ctxMenu) return;
    const item = ctxMenu.item;
    const isSg = ctxMenu.tipo === 'sovragruppo';
    if (prop === '--repeatName') {
      toggleRepeatName(item);
    } else {
      isSg ? setSgStyle(item, prop, value) : setGruppoStyle(item, prop, value);
    }
  }

  function setGruppoColStyle(gruppo, prop, value) {
    const colStyle = { ...(gruppo.style?.['--columnStyle'] ?? {}), [prop]: value };
    gruppo.style = { ...(gruppo.style ?? {}), '--columnStyle': colStyle };
    struttura = { ...struttura };
  }

  function setSgColStyle(sg, prop, value) {
    for (const g of (sg.gruppi ?? [])) {
      const colStyle = { ...(g.style?.['--columnStyle'] ?? {}), [prop]: value };
      g.style = { ...(g.style ?? {}), '--columnStyle': colStyle };
    }
    struttura = { ...struttura };
  }

  function setSgStyle(sg, prop, value) {
    sg.style = { ...(sg.style ?? {}), [prop]: value };
    struttura = { ...struttura };
  }

  // Applica: salva nel DB + push history
  async function applicaCtxStyle() {
    if (!ctxMenu || !ctxStyleSnapshot) return;
    const item = ctxMenu.item;
    const tipo = ctxMenu.tipo;

    // Costruisci array batch di modifiche
    // JSON round-trip per de-proxificare gli oggetti Svelte 5
    const clone = obj => JSON.parse(JSON.stringify(obj));
    const batchItems = [];

    if (tipo === 'sovragruppo') {
      batchItems.push({
        tipo: 'sovragruppo', campo: 'sg_style',
        sigla: item.sigla,
        style: clone(item.style ?? {}), style_before: clone(ctxStyleSnapshot.itemStyle),
      });
      for (let i = 0; i < (item.gruppi ?? []).length; i++) {
        const g = item.gruppi[i];
        batchItems.push({
          tipo: 'gruppo', campo: 'style',
          sigla: g.sigla, ordine: g.ordine,
          style: clone(g.style ?? {}), style_before: clone(ctxStyleSnapshot.childStyles?.[i] ?? {}),
        });
      }
    } else {
      batchItems.push({
        tipo: 'gruppo', campo: 'style',
        sigla: item.sigla, ordine: item.ordine,
        style: clone(item.style ?? {}), style_before: clone(ctxStyleSnapshot.itemStyle),
      });
    }

    const r = await managerApi.setFormatoBatch(calId, batchItems);
    if (r.ok) styleUndoCount = r.undo_count;
    else showToast(r.errore ?? 'Errore salvataggio formato.', true);

    ctxMenu = null;
    ctxStyleSnapshot = null;
  }

  async function applicaATutti(gruppo) {
    // Snapshot before di tutti i gruppi per history
    // Per il gruppo corrente (con preview attiva), usa lo snapshot originale
    const clone = obj => JSON.parse(JSON.stringify(obj));
    const style_before = [];
    for (const sg of struttura.sovragruppi) {
      for (const g of sg.gruppi) {
        const isCurrentItem = (g === gruppo && ctxStyleSnapshot);
        style_before.push({
          gruppo_sigla: g.sigla,
          gruppo_ordine: g.ordine,
          style_before: isCurrentItem
            ? clone(ctxStyleSnapshot.itemStyle)
            : clone(g.style ?? {}),
        });
        g.style = clone(gruppo.style ?? {});
      }
    }
    struttura = { ...struttura };
    const r = await managerApi.setFormatoGruppo(calId, {
      gruppo_sigla: gruppo.sigla,
      gruppo_ordine: gruppo.ordine,
      style: clone(gruppo.style ?? {}),
      applica_tutti: true,
      style_before,
    });
    if (r.ok) styleUndoCount = r.undo_count;
    showToast('Formato applicato a tutti i gruppi.');
    ctxMenu = null;
    ctxStyleSnapshot = null;
  }

  async function undoCalendarStyle() {
    if (isReadOnly) return;
    const r = await managerApi.undoStyle(calId);
    if (r.ok) {
      styleUndoCount = r.undo_count;
      // Applica style_before degli item ripristinati allo stato locale
      for (const histItem of (r.items ?? [])) {
        const styleBefore = histItem.style_before ?? {};
        if (histItem.campo === 'sg_style') {
          for (const sg of struttura.sovragruppi) {
            if (sg.sigla === histItem.sigla) sg.style = { ...styleBefore };
          }
        } else if (histItem.campo === 'style') {
          for (const sg of struttura.sovragruppi) {
            for (const g of sg.gruppi) {
              if (g.sigla === histItem.sigla && (histItem.ordine == null || g.ordine === histItem.ordine)) {
                g.style = { ...styleBefore };
              }
            }
          }
        }
      }
      struttura = { ...struttura };
    } else {
      showToast(r.errore ?? 'Nessuna operazione da annullare.', true);
    }
  }
</script>

<style>
  .gc-super { background: var(--gc-superfestivi-bg, #f8d7da); }
  .gc-fest  { background: var(--gc-festivi-bg, #fff3cd); }
  .gc-chiusa {
    background: repeating-linear-gradient(
      -45deg,
      #e9ecef,
      #e9ecef 3px,
      #f8f9fa 3px,
      #f8f9fa 6px
    ) !important;
    pointer-events: none;
  }
  .gc-no-accesso {
    background: #e9ecef !important;
    pointer-events: none;
  }
  .gc-turno-disabled {
    opacity: 0.5;
    text-decoration: line-through;
  }
  .gc-no-accesso .cell-noacc-sigla {
    display: block;
    text-align: center;
    font-size: .75rem;
    font-weight: 600;
    color: #6c757d;
    padding-top: 2px;
  }
  .gc-locked {
    background: #fef3c7 !important;
    position: relative;
  }
  .gc-readonly {
    pointer-events: none;
    opacity: 0.85;
  }
  .gc-effettivo-mod {
    border: 3px solid #f97316 !important;
  }
  .scm-tab-disabled {
    opacity: 0.4 !important;
    text-decoration: line-through;
  }
  .cell-locked-marker {
    position: absolute;
    top: 1px;
    right: 2px;
    font-size: .55rem;
    color: #b45309;
    opacity: 0.7;
  }
  .cell-locked-sigla {
    display: block;
    text-align: center;
    font-size: .75rem;
    font-weight: 600;
    color: #92400e;
    padding-top: 2px;
  }
  .cell-chiusa-marker {
    display: block;
    width: 100%;
    height: 100%;
  }

  /* ── Notti mese precedente ──────────────────────────────── */
  .col-notte-prec {
    background: #f0f0f0 !important;
    border-right: 2px solid #adb5bd !important;
  }
  .cella-notte-prec {
    background: #f8f9fa;
    text-align: center;
    font-size: .75rem;
    font-weight: 600;
    color: #495057;
    pointer-events: none;
    min-width: var(--cell-w, 44px);
    max-width: var(--cell-w, 44px);
  }
  .cella-notte-prec-empty {
    /* Turno non notturno: cella vuota grigia */
    background: #f0f0f0;
  }
  .cella-notte-prec-missing {
    /* Turno notturno ma nessun calendario precedente: evidenziato rosso */
    background: #f8d7da;
  }
  .notte-prec-row td.cella-notte-prec {
    border-right: 2px solid #adb5bd;
  }
  .notte-prec-row td.cella-notte-prec:last-child {
    border-right: none;
  }

  /* ══════════════════════════════════════════════════════════════
     STILE GRIGLIA DESIDERATA — unificato con Inserimento Desiderata
     (vedi DesiderataInserimento.svelte)
     ══════════════════════════════════════════════════════════════ */
  .desiderata-grid       { border-collapse: separate; border-spacing: 0; }
  .desiderata-grid th,
  .desiderata-grid td    { padding: 2px 4px; vertical-align: middle; }

  /* Celle label (sigla utente, numero giorno) */
  .des-cell-label        { background: #f8f9fa; white-space: nowrap; font-weight: 600; }
  td.des-cell-label      { position: sticky; left: 0; z-index: 10; }
  th.des-cell-label      { position: sticky; top: 0; z-index: 20; }

  /* Header giorno */
  .des-g                 { text-align: center; background: #f8f9fa; }
  .des-dow               { font-size: .58rem; color: #666; }

  /* Riga sovragruppo (orientamento normale) */
  .des-sg-row .sg-label-cell { background: #e9ecef; font-weight: 700; position: sticky; left: 0; z-index: 10; }
  .des-sg-spacer         { background: #e9ecef; padding: 0 !important; height: 4px; }
  .sg-label              { font-weight: bold; }
  /* Riga SG con "ripeti nome" (stile uguale a griglia turni) */
  tr.des-sg-row td.des-sg-repeat {
    background: #e9ecef; font-weight: 700;
    position: sticky; left: 0; z-index: 10;
    padding: 2px 8px !important;
  }
  tr.des-sg-row td.des-sg-repeat .sep-repeat { display: flex; justify-content: space-around; }
  .des-sg-row .btn-link  { color: inherit; line-height: 1; font-size: .75rem; }

  /* Header SG orizzontale (orientamento trasposto) */
  th.sg-header           { background: #e9ecef; font-weight: 600; text-align: center; border-bottom: 2px solid #6c757d; }

  /* Utente corrente evidenziato in rosa */
  .user-me               { background: #f8d7da !important; }
  .cell-me               { background: rgba(248, 215, 218, .45); }
  .user-sigla.user-me    { background: #f8d7da !important; }
  th.des-g.user-me       { background: #f8d7da !important; color: #212529 !important; }

  /* Celle: lavorativo (verde tenue) e assenza (rosso con bordo) */
  .des-working           { background-color: #d1e7dd; }
  .des-notworking        { outline: 2px solid #dc3545; outline-offset: -2px; background-color: #f8d7da; }

  /* Tipologia giorno — stessi CSS vars di /manager griglia turni */
  .gc-fest               { background-color: var(--gc-festivi-bg, #fff3cd); }
  .gc-super              { background-color: var(--gc-superfestivi-bg, #f8d7da); }
  td.des-cell.gc-fest    { background-color: color-mix(in srgb, var(--gc-festivi-bg, #fff3cd) 60%, transparent); }
  td.des-cell.gc-super   { background-color: color-mix(in srgb, var(--gc-superfestivi-bg, #f8d7da) 60%, transparent); }
  td.des-cell.cell-me.gc-fest  { background-color: color-mix(in srgb, var(--gc-festivi-bg, #fff3cd) 55%, #f8d7da 45%); }
  td.des-cell.cell-me.gc-super { background-color: color-mix(in srgb, var(--gc-superfestivi-bg, #f8d7da) 55%, #f8d7da 45%); }
  /* Label giorno (trasposta): festivi/superfestivi anche sulla label sinistra */
  td.des-cell-label.gc-fest  { background-color: var(--gc-festivi-bg, #fff3cd) !important; }
  td.des-cell-label.gc-super { background-color: var(--gc-superfestivi-bg, #f8d7da) !important; }

  /* Cella base */
  .des-cell              { position: relative; text-align: center; min-width: 42px; }

  /* WD-specific add-ons (non presenti in /basic) */
  td.des-cell.des-no-accesso, td.des-cell-label.des-no-accesso {
    background: #e9ecef !important;
    color: #6c757d;
  }
  td.des-cell.des-wd-frozen-off {
    background: #fef3c7 !important;
    pointer-events: none;
  }
  td.des-cell.wd-selected {
    outline: 2px solid #0d6efd !important;
    outline-offset: -2px;
    background: rgba(13, 110, 253, .12) !important;
  }
  td.des-cell.wd-selected select.des-sel {
    background: rgba(13, 110, 253, .12) !important;
  }

  select.des-sel {
    width: 100%; height: 100%; border: none; background: white;
    font-size: 0.68rem; font-weight: 600;
    text-align: center; text-align-last: center;
    cursor: pointer; padding: 0; appearance: none; -webkit-appearance: none; outline: none;
  }
  select.des-sel[data-tipo="lavorativo"] { background: #d1e7dd; }
  select.des-sel[data-tipo="assenza"]    { background: #f8d7da; }
  select.des-sel:hover { filter: brightness(0.92); }
  select.des-sel:focus { outline: 2px solid #0d6efd; background: #e8f0fe; filter: none; }

  /* Wrap scrollabile delle viste desiderata */
  .des-wrap              { max-height: calc(100vh - 130px); overflow: auto; }

  td.cella {
    padding: 0; height: 30px;
    min-width: var(--cell-w, 72px); max-width: var(--cell-w, 72px);
    border: var(--gc-cella-bordo, 1px solid #dee2e6);
  }

  /* ── Bordi strutturali ──────────────────────────────────────── */

  /* Separatori gruppo */
  td.sep-gruppo, th.sep-gruppo {
    border: var(--g-width, 4px) solid var(--g-border, #dee2e6) !important;
  }
  /* Vista normale: laterali del separatore gruppo seguono il colore SG */
  td.sep-gruppo {
    border-left: var(--sg-width, 5px) solid var(--sg-border, #dee2e6) !important;
    border-right: var(--sg-width, 5px) solid var(--sg-border, #dee2e6) !important;
  }
  /* Separatore SG normale: barra colorata senza bordo perimetrale */
  td.sep-sg {
    border: none !important;
  }
  /* Separatore SG trasposta: bordo spesso */
  th.sep-sg {
    border: var(--sg-width, 5px) solid var(--sg-border, #dee2e6) !important;
  }

  /* Nomi turno (prima colonna): bordi laterali spessi colore gruppo, top/bottom solo su perimetro */
  tbody td.col-turno {
    border-left: var(--g-width, 4px) solid var(--g-border, #dee2e6) !important;
    border-right: var(--g-width, 4px) solid var(--g-border, #dee2e6) !important;
  }
  tr.first-in-gruppo > td.col-turno { border-top: var(--g-width, 4px) solid var(--g-border, #dee2e6) !important; }
  tr.last-in-gruppo > td.col-turno  { border-bottom: var(--g-width, 4px) solid var(--g-border, #dee2e6) !important; }

  /* Perimetro blocco celle giorno per gruppo */
  tr.first-in-gruppo > td.cella { border-top: var(--g-width, 4px) solid var(--g-border, #dee2e6); }
  tr.last-in-gruppo > td.cella  { border-bottom: var(--g-width, 4px) solid var(--g-border, #dee2e6); }
  tr.turno-row > td.cella:first-of-type { border-left: var(--g-width, 4px) solid var(--g-border, #dee2e6); }
  tr.turno-row > td.cella:last-child    { border-right: var(--g-width, 4px) solid var(--g-border, #dee2e6); }

  /* Perimetro SG vista normale: laterali + top (bottom è la riga di chiusura) */
  tr.sg-row > td.col-turno           { border-left: var(--sg-width, 5px) solid var(--sg-border, #dee2e6) !important; }
  tr.sg-row > td.cella:last-child    { border-right: var(--sg-width, 5px) solid var(--sg-border, #dee2e6) !important; }
  tr.first-in-sg > td.col-turno     { border-top: var(--sg-width, 5px) solid var(--sg-border, #dee2e6) !important; }
  tr.first-in-sg > td.cella         { border-top: var(--sg-width, 5px) solid var(--sg-border, #dee2e6) !important; }

  /* Chiusura SG (riga colorata dopo ogni SG) */
  td.sep-sg-close {
    padding: 0 !important;
    border: none !important;
  }

  /* ── Vista trasposta: bordi perimetro per gruppo ── */
  td.first-col-gruppo, th.first-col-gruppo { border-left: var(--g-width, 4px) solid var(--g-border, #dee2e6) !important; }
  td.last-col-gruppo, th.last-col-gruppo   { border-right: var(--g-width, 4px) solid var(--g-border, #dee2e6) !important; }
  tr.first-day-row > td.cella { border-top: var(--g-width, 4px) solid var(--g-border, #dee2e6); }
  tr.last-day-row > td.cella  { border-bottom: var(--g-width, 4px) solid var(--g-border, #dee2e6); }
  /* Perimetro SG trasposta */
  td.first-col-sg, th.first-col-sg { border-left: var(--sg-width, 5px) solid var(--sg-border, #dee2e6) !important; }
  td.last-col-sg, th.last-col-sg   { border-right: var(--sg-width, 5px) solid var(--sg-border, #dee2e6) !important; }

  /* Il select occupa tutta la cella, senza freccia visibile */
  select.cell-sel {
    width: 100%;
    height: 100%;
    border: none;
    background: white;
    font-size: 0.72rem;
    font-weight: 600;
    text-align: center;
    text-align-last: center;
    cursor: pointer;
    padding: 0 2px;
    appearance: none;
    -webkit-appearance: none;
    outline: none;
  }

  /* Focus e hover */
  select.cell-sel:hover  { filter: brightness(0.92); }
  select.cell-sel:focus  {
    outline: 2px solid #0d6efd;
    border-radius: 2px;
    background: #e8f0fe !important;
    filter: none;
  }

  /* Pallino stato sincronizzazione */
  .sync-dot {
    position: absolute;
    top: 2px; right: 2px;
    width: 6px; height: 6px;
    border-radius: 50%;
    pointer-events: none;
  }
  .sync-dot.saving { background: #ffc107; animation: pulse .8s infinite; }
  .sync-dot.ok     { background: #198754; }
  .sync-dot.err    { background: #dc3545; }

  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }

  td.col-turno, th.col-turno {
    position: sticky; left: 0; z-index: 10;
    min-width: var(--col-turno-w, 155px); max-width: var(--col-turno-w, 155px);
    font-size: 0.75rem;
  }
  td.col-turno {
    background: #fff;
    border-right: 2px solid #dee2e6 !important;
  }
  th.col-turno {
    background: #0d6efd; color: #fff; z-index: 20;
    position: relative;
    border-right: 2px solid #dee2e6 !important;
  }

  .resize-handle {
    position: absolute; right: 0; top: 0; bottom: 0;
    width: 5px; cursor: col-resize;
    background: transparent;
  }
  .resize-handle:hover { background: rgba(255,255,255,0.4); }

  th.col-g {
    min-width: var(--cell-w, 72px); max-width: var(--cell-w, 72px);
    text-align: center; font-size: 0.68rem; padding: 2px 0;
  }

  /* ── Griglia trasposta ────────────────────────────────────── */
  .t-grid { font-size: .75rem; }

  .t-col-giorno {
    position: sticky; left: 0; z-index: 10;
    min-width: 72px; max-width: 72px;
    padding: 2px 8px;
    background: #fff; color: #212529;
    border-right: 2px solid #dee2e6 !important;
    white-space: nowrap; font-size: .75rem;
  }
  thead .t-col-giorno { z-index: 20; background: #0d6efd; color: #fff; }
  tbody .t-col-giorno.gc-fest  { background: var(--gc-festivi-bg, #fff3cd); color: #212529; }
  tbody .t-col-giorno.gc-super { background: var(--gc-superfestivi-bg, #f8d7da); color: #212529; }


  .t-day-name {
    font-size: .6rem; opacity: .8; font-weight: normal; margin-left: 4px;
  }

  .t-th-sg {
    text-align: center; font-size: .72rem; padding: 3px 6px;
    cursor: context-menu; user-select: none;
  }
  .t-th-gruppo {
    text-align: center; font-size: .68rem; padding: 1px 4px;
    cursor: context-menu; user-select: none;
  }
  .t-th-turno {
    text-align: center; font-size: .68rem; font-weight: 600;
    padding: 2px 4px;
    min-width: var(--cell-w, 72px); max-width: var(--cell-w, 72px);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }

  /* Context menu shared styles (used by assignment menu) */
  .ctx-drag-bar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 4px 10px; cursor: move; background: var(--ctx-bar, #f8f9fa);
    border-bottom: 1px solid var(--ctx-sep, #eee); border-radius: 4px 4px 0 0;
    user-select: none;
  }
  .ctx-drag-bar.ctx-drag-bottom {
    border-bottom: none; border-top: 1px solid var(--ctx-sep, #eee);
    border-radius: 0 0 4px 4px; justify-content: center;
    padding: 2px 10px;
  }
  .ctx-close {
    border: none; background: none; font-size: 1.1rem; color: var(--ctx-muted, #999);
    cursor: pointer; padding: 0 4px; line-height: 1;
  }
  .ctx-close:hover { color: var(--ctx-fg, #333); }

  /* Separatore gruppo */
  td.sep-gruppo {
    cursor: context-menu;
    user-select: none;
  }
  .sep-repeat {
    display: flex; justify-content: space-around;
  }

  /* ── Context menu assegnazione ──────────────────── */
  .ass-menu {
    position: fixed; z-index: 1000;
    background: var(--ctx-bg, #fff); border: 1px solid var(--ctx-border, #ccc);
    border-radius: 6px; box-shadow: 0 4px 16px var(--ctx-shadow, rgba(0,0,0,.18));
    min-width: 340px; max-width: 520px;
    font-size: .8rem; color: var(--ctx-fg, #212529);
  }
  .ass-table-wrap {
    max-height: 320px; overflow-y: auto;
    padding: 0 4px;
  }
  .ass-table {
    width: 100%; border-collapse: collapse;
  }
  .ass-table th {
    position: sticky; top: 0;
    background: var(--ctx-bar, #f8f9fa); font-size: .7rem;
    text-align: left; padding: 4px 6px;
    border: 1px solid var(--ctx-tbl-border, #dee2e6);
  }
  .ass-table td {
    padding: 3px 6px; font-size: .75rem;
    border: 1px solid var(--ctx-tbl-border, #dee2e6);
  }
  .ass-row {
    cursor: pointer;
  }
  .ass-row:hover {
    background: var(--ctx-hover, #e8f0fe);
  }
  .ass-unavail {
    opacity: .5;
    text-decoration: line-through;
  }
  .ass-unavail:hover {
    opacity: .8;
  }
  .ass-current {
    background: var(--ctx-current, #d1e7dd);
    font-weight: 600;
  }
  .ass-sigla {
    font-weight: 600;
  }
  .ass-note {
    max-width: 150px;
    word-break: break-word;
    white-space: pre-wrap;
  }
  .ass-empty-row {
    text-align: center; font-style: italic; color: var(--ctx-muted);
    padding: 5px 10px; font-size: .75rem; cursor: pointer;
    border-bottom: 1px solid var(--ctx-sep, #eee);
  }
  .ass-empty-row:hover { background: var(--ctx-hover); }
  .ass-empty-row.ass-current { background: var(--ctx-current, #d1e7dd); font-weight: 600; }
  .ass-blocked {
    cursor: not-allowed;
    pointer-events: none;
    opacity: .35;
  }
  .ass-turni {
    text-align: center; white-space: nowrap; font-size: .7rem;
    line-height: 1.2;
  }
  .turni-count { font-weight: 700; }
  .turni-ore { display: block; font-size: .6rem; opacity: .7; }
  .turni-ok .turni-count { color: #198754; }
  .turni-over .turni-count { color: #dc3545; }

  .cell-dragging-source {
    outline: 2px dashed #0d6efd !important;
    outline-offset: -2px;
    opacity: .6;
  }
  .cell-dragging-source select { pointer-events: none; }
  .cell-drag-over {
    outline: 2px solid #198754 !important;
    outline-offset: -2px;
    background: rgba(25, 135, 84, .12) !important;
  }
  td.cella.gc-selected {
    outline: 2px solid #0d6efd !important;
    outline-offset: -2px;
    background: rgba(13, 110, 253, .12) !important;
  }
  td.cella.gc-selected select.cell-sel {
    background: rgba(13, 110, 253, .12) !important;
  }
  /* Cella con cursore tastiera (stile Excel) */
  td.cella.gc-focused,
  td.des-cell.gc-focused {
    outline: 2px solid #198754 !important;
    outline-offset: -2px;
    z-index: 3;
  }
  td.cella.gc-focused.gc-selected,
  td.des-cell.gc-focused.wd-selected {
    outline-color: #0d6efd !important;
  }
  :global(body.cell-dragging) .cella select { pointer-events: none; }
  :global(body.cell-dragging) .cella { cursor: grabbing; }
  .ass-nav-btn {
    background: none; border: 1px solid var(--ctx-btn-border, #ccc); border-radius: 3px;
    padding: 0 4px; cursor: pointer; font-size: .75rem; line-height: 1.4;
    color: var(--ctx-fg, #212529);
  }
  .ass-nav-btn:disabled { opacity: .3; cursor: default; }
  .ass-nav-btn:not(:disabled):hover { background: var(--ctx-hover, #e8f0fe); }
  .ass-th-toggle {
    position: relative;
  }
  .ass-th-toggle .ass-eye-btn {
    position: absolute; right: 1px; top: 1px;
    background: none; border: none; cursor: pointer;
    font-size: .55rem; color: var(--ctx-muted, #999); padding: 0 2px; line-height: 1;
    opacity: 0; transition: opacity .15s;
  }
  .ass-th-toggle:hover .ass-eye-btn { opacity: 1; }
  .ass-eye-btn:hover { color: var(--ctx-fg, #212529); }
  .ass-restore-btn {
    background: var(--ctx-bar, #f8f9fa); border: 1px solid var(--ctx-btn-border, #ccc);
    border-radius: 3px; padding: 0 5px; font-size: .6rem; cursor: pointer;
    color: var(--ctx-fg, #212529); line-height: 1.6;
  }
  .ass-restore-btn:hover { background: var(--ctx-hover, #e8f0fe); }
  .ass-menu select, .ass-menu input[type="checkbox"] {
    background: var(--ctx-bg, #fff); color: var(--ctx-fg, #212529);
    border-color: var(--ctx-btn-border, #ccc);
  }
  /* Solver modal */
  .modal-backdrop-custom {
    position: fixed; inset: 0; z-index: 1050;
    background: rgba(0,0,0,.35);
  }
  .solver-modal {
    position: fixed; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    z-index: 1051;
    background: #fff; border-radius: 8px;
    padding: 1.2rem; min-width: 420px; max-width: 700px; width: 90vw;
    max-height: 85vh; overflow-y: auto;
    box-shadow: 0 8px 32px rgba(0,0,0,.25);
  }
  .solver-result { border: 1px solid #dee2e6; background: #f8f9fa; }

  /* Posti Fissi modal */
  .pf-modal {
    position: fixed; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    z-index: 1051;
    background: #fff; border-radius: 8px;
    padding: 1.2rem; min-width: 520px; max-width: 800px; width: 92vw;
    max-height: 85vh; overflow-y: auto;
    box-shadow: 0 8px 32px rgba(0,0,0,.25);
  }
  .pf-utenti-grid {
    display: flex; flex-wrap: wrap; gap: 4px;
    max-height: 150px; overflow-y: auto;
    padding: 4px; border: 1px solid #dee2e6; border-radius: 4px;
  }
  .pf-utente-chip {
    display: inline-block; padding: 1px 7px;
    border: 1px solid #dee2e6; border-radius: 12px;
    font-size: .72rem; cursor: pointer;
    background: #fff; color: #666;
    transition: background .15s, border-color .15s;
    user-select: none;
  }
  .pf-utente-chip:hover { border-color: #86b7fe; }
  .pf-utente-sel {
    background: #0d6efd; color: #fff; border-color: #0d6efd;
  }
  .pf-utente-sel:hover { background: #0b5ed7; border-color: #0b5ed7; }

  /* Azzera modal rows */
  .az-row {
    padding: 3px 6px; cursor: pointer; border-radius: 3px;
    user-select: none; display: flex; align-items: center; gap: 6px;
  }
  .az-row:hover { background: #e8f0fe; }
  .az-check { font-size: .9rem; width: 16px; text-align: center; flex-shrink: 0; }

  /* Aperture modal */
  .aperture-modal {
    position: fixed; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    z-index: 1051;
    background: #fff; border-radius: 8px;
    padding: 1.2rem; min-width: 500px; max-width: 900px; width: 92vw;
    max-height: 85vh;
    box-shadow: 0 8px 32px rgba(0,0,0,.25);
    display: flex; flex-direction: column;
  }
  .aperture-scroll {
    overflow-y: auto; flex: 1; max-height: calc(85vh - 120px);
  }
  .ap-day-btn {
    display: inline-flex; align-items: center; justify-content: center;
    width: 26px; height: 22px; padding: 0;
    border: 1px solid #dee2e6; border-radius: 3px;
    font-size: .7rem; cursor: pointer;
    background: #fff; color: #666; margin: 1px;
    transition: background .15s, color .15s;
  }
  .ap-day-btn.ap-fest  { background: #fef3cd; color: #856404; border-color: #e0c870; }
  .ap-day-btn.ap-super { background: #fad7d7; color: #842029; border-color: #e0a0a0; }
  .ap-day-btn.ap-active { background: #198754 !important; color: #fff !important; border-color: #157347 !important; }
  .ap-day-btn:hover { opacity: .8; }
</style>

<!-- ── TAB PRINCIPALE / EFFETTIVO ──────────────────── -->
{#if calStato === 'CHIUSO' || effettivoInfo || isEffettivo}
  <div class="bg-light border-bottom px-3 py-1 d-flex align-items-center gap-2"
       style="position:sticky;top:0;z-index:31">
    <ul class="nav nav-tabs nav-tabs-sm mb-0" style="border-bottom:none">
      <li class="nav-item">
        <button class="nav-link py-1 px-3 {calTab === 'principale' ? 'active' : ''}"
                onclick={() => switchCalTab('principale')}>
          <i class="bi bi-calendar-check me-1"></i>Principale
          {#if calTab === 'principale' && calStato === 'APERTO'}
            <span class="ms-1 text-muted" style="font-size:.7rem">(riaperto)</span>
          {:else if calTab === 'principale' && calStato === 'CHIUSO'}
            <span class="ms-1 text-muted" style="font-size:.7rem">(chiuso{struttura?.calendario?.versione ? ` v${struttura.calendario.versione}` : ''})</span>
          {:else if effettivoInfo?.parent_versione}
            <span class="ms-1 text-muted" style="font-size:.7rem">(chiuso v{effettivoInfo.parent_versione})</span>
          {/if}
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link py-1 px-3 {calTab === 'effettivo' ? 'active' : ''} {!effettivoInfo ? 'scm-tab-disabled' : ''}"
                disabled={!effettivoInfo}
                onclick={() => switchCalTab('effettivo')}>
          <i class="bi bi-pencil-square me-1"></i>Effettivo
          {#if effettivoInfo}
            <span class="ms-1" style="font-size:.7rem">(v{effettivoInfo.parent_versione ?? struttura?.calendario?.versione ?? ''})</span>
            {#if effettivoInfo.stato === 'CHIUSO'}
              <span class="badge bg-secondary ms-1" style="font-size:.6rem">chiuso</span>
            {/if}
          {/if}
        </button>
      </li>
    </ul>
  </div>
{/if}
{#if isReadOnly}
  <div class="alert alert-info m-0 py-1 px-3 rounded-0 small">
    <i class="bi bi-lock me-1"></i>
    {#if isEffettivo}
      Effettivo in sola lettura (chiuso)
    {:else if calStato === 'CHIUSO' && calTipo === 'programmato'}
      Calendario in sola lettura (CHIUSO){#if struttura?.calendario?.chiuso_il} — ultimato il {_fmtArchDate(struttura.calendario.chiuso_il)}{/if}
    {:else}
      Calendario in sola lettura ({calStato})
    {/if}
  </div>
{/if}
{#if isEffettivo && !isReadOnly}
  <div class="alert alert-info m-0 py-1 px-3 rounded-0 small">
    <i class="bi bi-pencil-square me-1"></i>
    Calendario effettivo basato sul calendario principale v{effettivoInfo?.parent_versione ?? struttura?.calendario?.versione ?? ''}{#if effettivoInfo?.parent_chiuso_il} del {_fmtArchDate(effettivoInfo.parent_chiuso_il)}{/if}
  </div>
{/if}

<!-- ── TOOLBAR ─────────────────────────────────────────────────── -->
<div class="bg-white border-bottom px-3 py-2 d-flex align-items-center gap-2 flex-wrap"
     style="position:sticky;top:0;z-index:30">
  <div class="btn-group btn-group-sm" role="group">
    <button class="btn {vista==='griglia'   ? 'btn-primary' : 'btn-outline-primary'}"
            onclick={() => vista='griglia'}>
      <i class="bi bi-table me-1"></i>Griglia Turni
    </button>
    <button class="btn {vista==='working'   ? 'btn-primary' : 'btn-outline-primary'}"
            onclick={() => vista='working'}>
      <i class="bi bi-pencil-square me-1"></i>Working Desiderata
    </button>
    <button class="btn {vista==='originali' ? 'btn-primary' : 'btn-outline-primary'}"
            onclick={() => vista='originali'}>
      <i class="bi bi-eye me-1"></i>Desiderata Originali
    </button>
    {#if $userStore && !$userStore.escluso_turni}
      <button class="btn {vista==='inserisci' ? 'btn-primary' : 'btn-outline-primary'}"
              onclick={() => vista='inserisci'}>
        <i class="bi bi-person-plus me-1"></i>Inserisci Desiderata
      </button>
    {/if}
  </div>

  <select class="form-select form-select-sm w-auto"
          onchange={e => { calTab = 'principale'; _principaleCalId = null; caricaCalendario(+e.target.value); }}>
    {#each calendari as c}
      <option value={c.id}>{NOMI_MESI[c.mese]} {c.anno} — {c.stato}</option>
    {/each}
  </select>

  <div class="ms-auto d-flex gap-2 align-items-center">
    {#if vista === 'griglia'}
      {#if Object.values(syncStatus).some(s => s === 'saving')}
        <span class="spinner-border spinner-border-sm text-warning" title="Salvataggio in corso"></span>
      {/if}
      <button class="btn btn-outline-secondary btn-sm" disabled={isReadOnly || !history.can_undo}
              onclick={doUndo} title="Annulla (Ctrl+Z)">
        <i class="bi bi-arrow-counterclockwise"></i>
      </button>
      <button class="btn btn-outline-secondary btn-sm" disabled={isReadOnly || !history.can_redo}
              onclick={doRedo} title="Ripeti (Ctrl+Y)">
        <i class="bi bi-arrow-clockwise"></i>
      </button>
      <button class="btn btn-sm {trasposto ? 'btn-primary' : 'btn-outline-secondary'}"
              onclick={toggleTrasposto} title="Trasponi griglia (giorni ↔ turni)">
        <i class="bi bi-arrow-repeat"></i>
      </button>
      {#if calId}
        <span class="badge {wsConnected ? 'bg-success' : 'bg-danger'} d-flex align-items-center"
              title={wsConnected ? 'Connesso (sync real-time attivo)' : 'Disconnesso (sync real-time non attivo)'}
              style="font-size:.6rem">
          <i class="bi bi-wifi me-1"></i>{wsConnected ? 'Live' : 'Off'}
        </span>
        {#if accessoInfo && accessoInfo.turni_accessibili < accessoInfo.turni_totali}
          <span class="badge bg-secondary d-flex align-items-center" title="Turni accessibili / totali">
            <i class="bi bi-briefcase me-1"></i>Turni: {accessoInfo.turni_accessibili}/{accessoInfo.turni_totali}
          </span>
        {/if}
        {#if _utentiAccessibili}
          <span class="badge bg-secondary d-flex align-items-center" title="Utenti gestibili / totali">
            <i class="bi bi-people me-1"></i>Utenti: {_utentiAccessibili.length}/{utenti.length}
          </span>
        {/if}
        <button class="btn btn-outline-secondary btn-sm" onclick={apertureApri}
                disabled={isReadOnly || isEffettivo}
                title="Gestisci aperture turni (festivi/superfestivi/straordinarie)">
          <i class="bi bi-calendar2-check me-1"></i>Aperture
        </button>
        <button class="btn btn-outline-danger btn-sm" onclick={azzeraApri}
                disabled={isReadOnly || isEffettivo}
                title="Azzera assegnazioni">
          <i class="bi bi-trash me-1"></i>Azzera
        </button>
        <button class="btn btn-outline-info btn-sm" onclick={pfApri}
                disabled={isReadOnly || isEffettivo}
                title="Posti fissi (assegnazioni ricorrenti)">
          <i class="bi bi-pin-angle me-1"></i>Fissi
        </button>
        <button class="btn btn-outline-warning btn-sm" onclick={solverApri}
                disabled={isReadOnly || isEffettivo}
                title="Solver automatico">
          <i class="bi bi-cpu me-1"></i>Solver
        </button>
        <button class="btn btn-outline-primary btn-sm" onclick={optApri}
                disabled={isReadOnly || isEffettivo}
                title="Ottimizza bilanciamento">
          <i class="bi bi-sliders2 me-1"></i>Ottimizza
        </button>
        <!-- Export Excel + aspetto griglia -->
        <div class="d-inline-flex align-items-center gap-1">
          <button class="btn btn-outline-success btn-sm"
                  onclick={async () => { const r = await exportApi.turni(calId, exportHeaderBg, exportHeaderFg); if (!r.ok) showToast(r.errore, true); }}
                  title="Esporta turni Excel"><i class="bi bi-file-earmark-excel"></i></button>
          <button class="btn btn-outline-info btn-sm"
                  onclick={async () => { const r = await exportApi.ore(calId); if (!r.ok) showToast(r.errore, true); }}
                  title="Esporta ore Excel"><i class="bi bi-file-earmark-bar-graph"></i></button>
          <button class="btn btn-outline-secondary btn-sm px-1"
                  onclick={apriAppModal}
                  title="Aspetto griglia e colori Excel">
            <i class="bi bi-palette"></i>
          </button>
        </div>
      {/if}
    {/if}
  </div>
</div>

<!-- ── TOAST ──────────────────────────────────────────────────── -->
{#if toast}
  <div class="position-fixed bottom-0 end-0 p-3" style="z-index:1100">
    <div class="toast show text-white {toastErr ? 'bg-danger' : 'bg-success'}">
      <div class="toast-body">{toast}</div>
    </div>
  </div>
{/if}

<!-- ── MODALE SOLVER ─────────────────────────────────────────── -->
{#if solverOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-backdrop-custom" onclick={() => { solverOpen = false; }}></div>
  <div class="solver-modal">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h6 class="mb-0"><i class="bi bi-cpu me-1"></i>Solver</h6>
      <button class="btn-close btn-close-sm" onclick={() => { solverOpen = false; }}></button>
    </div>

    <!-- Tab navigation -->
    <ul class="nav nav-tabs nav-fill mb-3" style="font-size:.8rem">
      <li class="nav-item">
        <button class="nav-link {solverTab === 'opzioni' ? 'active' : ''}" onclick={() => solverTab = 'opzioni'}>
          <i class="bi bi-sliders me-1"></i>Opzioni
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link {solverTab === 'regole' ? 'active' : ''}" onclick={() => solverTab = 'regole'}>
          <i class="bi bi-shield-check me-1"></i>Regole
          {#if solverRegoleDirty}<span class="badge bg-warning text-dark ms-1">*</span>{/if}
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link {solverTab === 'vincoli' ? 'active' : ''}" onclick={() => solverTab = 'vincoli'}>
          <i class="bi bi-sliders2 me-1"></i>Vincoli
          {#if snapVincoliDirty}<span class="badge bg-warning text-dark ms-1">*</span>{/if}
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link {solverTab === 'utenti' ? 'active' : ''}" onclick={() => solverTab = 'utenti'}>
          <i class="bi bi-people me-1"></i>Utenti
          {#if solverUtenti.length > 0}<span class="badge bg-secondary ms-1">{solverUtenti.length}</span>{/if}
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link {solverTab === 'turni' ? 'active' : ''}" onclick={() => solverTab = 'turni'}>
          <i class="bi bi-list-check me-1"></i>Turni
          {#if !solverTurniTutti}<span class="badge bg-info ms-1">{solverTurniSel.length}</span>{/if}
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link {solverTab === 'accesso' ? 'active' : ''}" onclick={() => solverTab = 'accesso'}>
          <i class="bi bi-key me-1"></i>Accesso
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link {solverTab === 'escl_giorno' ? 'active' : ''}" onclick={() => solverTab = 'escl_giorno'}>
          <i class="bi bi-calendar-x me-1"></i>Escludi giorno
          {#if esclusioni.length > 0}<span class="badge bg-secondary ms-1">{esclusioni.length}</span>{/if}
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link {solverTab === 'escl_turno' ? 'active' : ''}" onclick={() => solverTab = 'escl_turno'}>
          <i class="bi bi-person-dash me-1"></i>Escludi turno
        </button>
      </li>
    </ul>

    <!-- TAB: Opzioni -->
    {#if solverTab === 'opzioni'}
      <div class="mb-3">
        <div class="form-check mb-1">
          <input class="form-check-input" type="checkbox" id="sv-vuote"
                 checked={solverOpts.solo_vuote}
                 onchange={() => solverOpts.solo_vuote = !solverOpts.solo_vuote} />
          <label class="form-check-label small" for="sv-vuote">Solo celle vuote</label>
        </div>
        <div class="form-check mb-1">
          <input class="form-check-input" type="checkbox" id="sv-indisp"
                 checked={solverOpts.solo_indispensabili}
                 onchange={() => solverOpts.solo_indispensabili = !solverOpts.solo_indispensabili} />
          <label class="form-check-label small" for="sv-indisp">Solo turni indispensabili</label>
        </div>
        {#if struttura?.calendario?.desiderata_congelati}
          <div class="mb-2 mt-2">
            <label class="form-label small fw-bold mb-1" for="sv-fonte-des">Fonte desiderata</label>
            <select class="form-select form-select-sm" id="sv-fonte-des"
                    value={solverOpts.fonte_desiderata}
                    onchange={e => solverOpts.fonte_desiderata = e.currentTarget.value}>
              <option value="working">Working Desiderata</option>
              <option value="originali">Desiderata Originali</option>
            </select>
          </div>
        {/if}

        <div class="small text-muted mt-2 mb-2">
          <i class="bi bi-info-circle me-1"></i>I desiderata assenza sono sempre esclusioni hard.
        </div>

        <hr class="my-2"/>
        <div class="mb-2">
          <label class="form-label small fw-bold mb-1">Ordine risoluzione (priorità custom)</label>
          <div class="text-muted mb-1" style="font-size:.7rem">
            I criteri vengono applicati nell'ordine indicato, dopo indispensabile/automatico e prima del peso priorità.
          </div>

          {#each solverCriteri as cr, idx}
          <div class="d-flex align-items-center gap-1 mb-1">
            <span class="badge" class:bg-primary={cr.tipo === 'flag'} class:bg-success={cr.tipo === 'tipo_giorno'} style="font-size:.7rem">
              {cr.tipo === 'flag' ? `Flag: ${cr.flag_nome}` : `Giorni: ${cr.valori.join(', ')}`}
            </span>
            <button class="btn btn-sm btn-outline-secondary py-0 px-1" style="font-size:.65rem"
                    disabled={idx === 0}
                    onclick={() => { const c = [...solverCriteri]; [c[idx-1], c[idx]] = [c[idx], c[idx-1]]; solverCriteri = c; }}>&#9650;</button>
            <button class="btn btn-sm btn-outline-secondary py-0 px-1" style="font-size:.65rem"
                    disabled={idx === solverCriteri.length - 1}
                    onclick={() => { const c = [...solverCriteri]; [c[idx], c[idx+1]] = [c[idx+1], c[idx]]; solverCriteri = c; }}>&#9660;</button>
            <button class="btn btn-sm btn-outline-danger py-0 px-1" style="font-size:.65rem"
                    onclick={() => { solverCriteri = solverCriteri.filter((_,i) => i !== idx); }}>&#10005;</button>
          </div>
          {/each}

          <div class="d-flex gap-1 mt-1">
            <select class="form-select form-select-sm" style="max-width:150px" id="sv-crit-flag">
              <option value="">+ Flag...</option>
              {#if struttura?.sovragruppi}
                {#each [...new Set(struttura.sovragruppi.flatMap(sg => sg.gruppi.flatMap(g => g.turni.filter(t => t.flag_nome).map(t => t.flag_nome))))] as fn}
                  {#if !solverCriteri.some(c => c.tipo === 'flag' && c.flag_nome === fn)}
                    <option value={fn}>{fn}</option>
                  {/if}
                {/each}
              {/if}
            </select>
            <button class="btn btn-sm btn-outline-primary py-0 px-2" style="font-size:.75rem"
                    onclick={(e) => {
                      const sel = e.target.closest('.d-flex').querySelector('#sv-crit-flag');
                      if (sel.value) { solverCriteri = [...solverCriteri, {tipo:'flag', flag_nome: sel.value}]; sel.value = ''; }
                    }}>Aggiungi</button>
          </div>
          <div class="d-flex gap-1 mt-1">
            {#if !solverCriteri.some(c => c.tipo === 'tipo_giorno')}
              <button class="btn btn-sm btn-outline-success py-0 px-2" style="font-size:.75rem"
                      onclick={() => { solverCriteri = [...solverCriteri, {tipo:'tipo_giorno', valori:['superfestivo','festivo']}]; }}>
                + Festivi/Superfestivi prima
              </button>
            {/if}
          </div>
        </div>

        <hr class="my-2"/>
        <div class="form-check mb-2">
          <input class="form-check-input" type="checkbox" id="sv-multistart"
                 checked={solverMultiStart > 0}
                 onchange={() => solverMultiStart = solverMultiStart > 0 ? 0 : 1} />
          <label class="form-check-label small fw-bold" for="sv-multistart">Generazione multipla (Multi-start)</label>
        </div>
        {#if solverMultiStart > 0}
        <div class="ps-3 border-start mb-2" style="border-color:#0d6efd!important">
          <div class="row g-2 mb-1">
            <div class="col-6">
              <label class="form-label small mb-0">Esecuzioni</label>
              <input type="number" class="form-control form-control-sm"
                     bind:value={solverNRuns} min="2" max="50" step="1" />
            </div>
            <div class="col-6">
              <label class="form-label small mb-0">Top-K</label>
              <input type="number" class="form-control form-control-sm"
                     bind:value={solverTopK} min="2" max="10" step="1" />
            </div>
          </div>
          <div class="text-muted" style="font-size:.7rem">Esegue N volte con randomizzazione e scrive la soluzione migliore.</div>
        </div>
        {/if}
      </div>
    {/if}

    <!-- TAB: Regole conflitto (editor snapshot per-calendario) -->
    {#if solverTab === 'regole'}
      <div class="small text-muted mb-2">
        Modifica le regole conflitto <strong>di questo calendario</strong>.
        Le modifiche non influenzano la configurazione globale.
      </div>

      <!-- Form nuova regola -->
      {#if solverShowAddRegola && solverNuovaRegola}
        <div class="card card-body p-2 mb-2 bg-light" style="font-size:.78rem">
          <div class="row g-1 mb-1">
            <div class="col-4">
              <label class="form-label mb-0 small">Nome</label>
              <input class="form-control form-control-sm" bind:value={solverNuovaRegola.nome} />
            </div>
            <div class="col-3">
              <label class="form-label mb-0 small">Tipo</label>
              <select class="form-select form-select-sm" bind:value={solverNuovaRegola.tipo_regola}>
                <option value="tipo_vs_tipo">tipo_vs_tipo</option>
                <option value="desiderata_mismatch">des. mismatch</option>
                <option value="desiderata_assenza_mismatch">Assenza</option>
              </select>
            </div>
            {#if solverNuovaRegola.tipo_regola === 'tipo_vs_tipo'}
              <div class="col-2">
                <label class="form-label mb-0 small">Flag A</label>
                <select class="form-select form-select-sm" bind:value={solverNuovaRegola.flag_a_id}>
                  <option value={null}>{'\u2014'}</option>
                  {#each solverFlagOrdinati as f}
                    <option value={f.id}>{f.parent_nome ? f.parent_nome + '\u2192' : ''}{f.nome}</option>
                  {/each}
                </select>
              </div>
              <div class="col-2">
                <label class="form-label mb-0 small">Flag B</label>
                <select class="form-select form-select-sm" bind:value={solverNuovaRegola.flag_b_id}>
                  <option value={null}>{'\u2014'}</option>
                  {#each solverFlagOrdinati as f}
                    <option value={f.id}>{f.parent_nome ? f.parent_nome + '\u2192' : ''}{f.nome}</option>
                  {/each}
                </select>
              </div>
              <div class="col-1">
                <label class="form-label mb-0 small">Offset</label>
                <input class="form-control form-control-sm" type="number" min="-1" max="1"
                       bind:value={solverNuovaRegola.offset_giorni} />
              </div>
            {/if}
          </div>
          <div class="row g-1 mb-1">
            <div class="col-3">
              <label class="form-label mb-0 small">Categoria</label>
              <select class="form-select form-select-sm" bind:value={solverNuovaRegola.categoria}>
                <option value="facoltativa">facoltativa</option>
                <option value="consigliata">consigliata</option>
                <option value="critica">critica</option>
              </select>
            </div>
            <div class="col-2">
              <label class="form-label mb-0 small">Peso</label>
              <input class="form-control form-control-sm" type="number" step="0.1"
                     bind:value={solverNuovaRegola.peso_numerico} />
            </div>
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-primary btn-sm" onclick={solverConfermaAggiungi}>
              <i class="bi bi-plus-lg me-1"></i>Aggiungi
            </button>
            <button class="btn btn-secondary btn-sm"
                    onclick={() => { solverShowAddRegola = false; solverNuovaRegola = null; }}>
              Annulla
            </button>
          </div>
        </div>
      {:else}
        <button class="btn btn-outline-primary btn-sm mb-2" style="font-size:.72rem"
                onclick={solverAggiungiRegola}>
          <i class="bi bi-plus-lg me-1"></i>Nuova regola
        </button>
      {/if}

      {#if regoleConflitto.length === 0}
        <div class="text-muted small fst-italic">Nessuna regola conflitto nello snapshot.</div>
      {:else}
        <div style="max-height:300px;overflow-y:auto">
          <table class="table table-sm mb-0" style="font-size:.78rem">
            <thead class="table-light"><tr>
              <th>Nome</th><th>Tipo</th><th>Flag A</th><th>Flag B</th>
              <th>Offset</th><th>Categoria</th>
              <th>Peso</th><th>Attiva</th><th></th>
            </tr></thead>
            <tbody>
              {#each regoleConflitto as r, idx (r.id)}
                {#if solverEditRegola?.id === r.id}
                  <!-- Riga in editing -->
                  <tr class="table-warning">
                    <td><input class="form-control form-control-sm" style="width:120px"
                               bind:value={solverEditRegola.nome} /></td>
                    <td>
                      <select class="form-select form-select-sm" style="width:100px"
                              bind:value={solverEditRegola.tipo_regola}>
                        <option value="tipo_vs_tipo">T vs T</option>
                        <option value="desiderata_mismatch">Des.</option>
                        <option value="desiderata_assenza_mismatch">Ass.</option>
                      </select>
                    </td>
                    <td>
                      {#if solverEditRegola.tipo_regola === 'tipo_vs_tipo'}
                        <select class="form-select form-select-sm" style="width:100px"
                                bind:value={solverEditRegola.flag_a_id}>
                          <option value={null}>{'\u2014'}</option>
                          {#each solverFlagOrdinati as f}
                            <option value={f.id}>{f.parent_nome ? f.parent_nome + '\u2192' : ''}{f.nome}</option>
                          {/each}
                        </select>
                      {:else}{'\u2014'}{/if}
                    </td>
                    <td>
                      {#if solverEditRegola.tipo_regola === 'tipo_vs_tipo'}
                        <select class="form-select form-select-sm" style="width:100px"
                                bind:value={solverEditRegola.flag_b_id}>
                          <option value={null}>{'\u2014'}</option>
                          {#each solverFlagOrdinati as f}
                            <option value={f.id}>{f.parent_nome ? f.parent_nome + '\u2192' : ''}{f.nome}</option>
                          {/each}
                        </select>
                      {:else}{'\u2014'}{/if}
                    </td>
                    <td>
                      {#if solverEditRegola.tipo_regola === 'tipo_vs_tipo'}
                        <input class="form-control form-control-sm" type="number" min="-1" max="1"
                               style="width:50px" bind:value={solverEditRegola.offset_giorni} />
                      {:else}{'\u2014'}{/if}
                    </td>
                    <td>
                      <select class="form-select form-select-sm" style="width:95px"
                              bind:value={solverEditRegola.categoria}>
                        <option value="facoltativa">facoltativa</option>
                        <option value="consigliata">consigliata</option>
                        <option value="critica">critica</option>
                      </select>
                    </td>
                    <td>
                      <input class="form-control form-control-sm" type="number" step="0.1"
                             style="width:50px" bind:value={solverEditRegola.peso_numerico} />
                    </td>
                    <td>
                      <input class="form-check-input" type="checkbox"
                             checked={!!solverEditRegola.is_active}
                             onchange={e => { solverEditRegola.is_active = e.target.checked ? 1 : 0; }} />
                    </td>
                    <td style="white-space:nowrap">
                      <button class="btn btn-success btn-sm py-0" onclick={solverApplicaEditRegola}>
                        <i class="bi bi-check-lg"></i>
                      </button>
                      <button class="btn btn-secondary btn-sm py-0"
                              onclick={() => { solverEditRegola = null; }}>
                        <i class="bi bi-x"></i>
                      </button>
                    </td>
                  </tr>
                {:else}
                  <!-- Riga display -->
                  <tr class="{r.is_active ? '' : 'text-muted'}" style="cursor:pointer"
                      onclick={() => solverStartEditRegola(r)}>
                    <td class="fw-semibold">{r.nome || `#${r.id}`}</td>
                    <td class="small">{r.tipo_regola === 'tipo_vs_tipo' ? 'T vs T' : r.tipo_regola === 'desiderata_mismatch' ? 'Des.' : 'NW'}</td>
                    <td><span class="badge bg-secondary">{solverFlagLabel(r.flag_a_id)}</span></td>
                    <td><span class="badge bg-secondary">{solverFlagLabel(r.flag_b_id)}</span></td>
                    <td class="small">{r.tipo_regola === 'tipo_vs_tipo' ? ((r.offset_giorni > 0 ? '+' : '') + r.offset_giorni) : '\u2014'}</td>
                    <td>
                      <span class="badge" style={solverRegolaStyle(r)}>
                        {r.categoria ?? 'consigliata'}
                      </span>
                    </td>
                    <td class="small">{r.peso_numerico}</td>
                    <td onclick={e => e.stopPropagation()}>
                      <input class="form-check-input" type="checkbox" checked={!!r.is_active}
                             onchange={e => {
                               regoleConflitto[idx] = { ...r, is_active: e.target.checked ? 1 : 0 };
                               regoleConflitto = [...regoleConflitto];
                               solverRegoleDirty = true;
                             }} />
                    </td>
                    <td style="white-space:nowrap" onclick={e => e.stopPropagation()}>
                      <button class="btn btn-outline-danger btn-sm py-0"
                              onclick={() => solverEliminaRegola(r.id)}
                              title="Elimina regola dallo snapshot">
                        <i class="bi bi-trash"></i>
                      </button>
                    </td>
                  </tr>
                {/if}
              {/each}
            </tbody>
          </table>
        </div>
      {/if}

      <!-- Azioni salva/ripristina -->
      <div class="mt-2 d-flex gap-2 flex-wrap">
        {#if solverRegoleDirty}
          <button class="btn btn-success btn-sm" style="font-size:.72rem"
                  onclick={solverSalvaRegoleSnapshot}>
            <i class="bi bi-check-lg me-1"></i>Salva regole snapshot
          </button>
          <button class="btn btn-outline-secondary btn-sm" style="font-size:.72rem"
                  onclick={solverResetRegole}>
            <i class="bi bi-arrow-counterclockwise me-1"></i>Ripristina
          </button>
        {/if}
        <button class="btn btn-outline-secondary btn-sm" style="font-size:.72rem"
                onclick={() => { regoleConflitto.forEach((r, i) => { regoleConflitto[i] = { ...r, is_active: 1 }; }); regoleConflitto = [...regoleConflitto]; solverRegoleDirty = true; }}>
          Attiva tutte
        </button>
        <button class="btn btn-outline-secondary btn-sm" style="font-size:.72rem"
                onclick={() => { regoleConflitto.forEach((r, i) => { regoleConflitto[i] = { ...r, is_active: 0 }; }); regoleConflitto = [...regoleConflitto]; solverRegoleDirty = true; }}>
          Disattiva tutte
        </button>
      </div>
    {/if}

    <!-- TAB: Vincoli (config snapshot per-calendario) -->
    {#if solverTab === 'vincoli'}
      <div class="small text-muted mb-2">
        Modifica i vincoli solver <strong>di questo calendario</strong>.
        Le modifiche non influenzano la configurazione globale.
      </div>

      <!-- Vincoli globali key-value -->
      <h6 class="mb-2" style="font-size:.82rem">Vincoli globali</h6>
      {#if snapVincoliGlobali.length === 0}
        <div class="text-muted small fst-italic mb-2">Nessun vincolo globale nello snapshot.</div>
      {:else}
        <table class="table table-sm mb-2" style="font-size:.78rem">
          <thead class="table-light"><tr>
            <th>Vincolo</th><th style="width:70px">Valore</th>
            <th>Descrizione</th><th style="width:45px">Attivo</th>
          </tr></thead>
          <tbody>
          {#each snapVincoliGlobali as v, i}
            <tr class={v.is_active ? '' : 'text-muted'}>
              <td class="font-monospace small">{v.chiave}</td>
              <td>
                <input class="form-control form-control-sm" type="number"
                       bind:value={v.valore}
                       onchange={() => { snapVincoliDirty = true; }} />
              </td>
              <td class="small text-muted">{v.descrizione || ''}</td>
              <td>
                <input class="form-check-input" type="checkbox" checked={!!v.is_active}
                       onchange={() => {
                         snapVincoliGlobali[i] = { ...v, is_active: v.is_active ? 0 : 1 };
                         snapVincoliGlobali = [...snapVincoliGlobali];
                         snapVincoliDirty = true;
                       }} />
              </td>
            </tr>
          {/each}
          </tbody>
        </table>
      {/if}

      <!-- Limiti mensili max per caratteristica temporale -->
      <h6 class="mt-2 mb-2" style="font-size:.82rem">
        Limiti mensili max per caratteristica temporale
        <button class="btn btn-sm btn-outline-primary ms-2 py-0" style="font-size:.7rem"
                onclick={() => snapAddVincoloSolver('flag')}>
          <i class="bi bi-plus me-1"></i>Aggiungi
        </button>
      </h6>
      {#if snapVincoliSolver.filter(v => v.tipo === 'flag').length}
        <table class="table table-sm mb-2" style="font-size:.78rem">
          <thead class="table-light"><tr>
            <th>Flag</th><th style="width:70px">Max N</th>
            <th style="width:45px">Attivo</th><th style="width:35px"></th>
          </tr></thead>
          <tbody>
          {#each snapVincoliSolver as vs, i}
            {#if vs.tipo === 'flag'}
              <tr class={vs.is_active ? '' : 'text-muted'}>
                <td>
                  <select class="form-select form-select-sm" bind:value={vs.ref_id}
                          onchange={() => { snapVincoliDirty = true; }}>
                    <option value={null}>{'\u2014 seleziona flag \u2014'}</option>
                    {#each solverFlagTurno.filter(f => f.mostra_in_struttura) as f}
                      <option value={f.id}>{f.nome}{f.parent_nome ? ` (${f.parent_nome})` : ''}</option>
                    {/each}
                  </select>
                </td>
                <td>
                  <input class="form-control form-control-sm" type="number" bind:value={vs.max_n}
                         onchange={() => { snapVincoliDirty = true; }} />
                </td>
                <td>
                  <input class="form-check-input" type="checkbox" checked={!!vs.is_active}
                         onchange={() => {
                           snapVincoliSolver[i] = { ...vs, is_active: vs.is_active ? 0 : 1 };
                           snapVincoliSolver = [...snapVincoliSolver];
                           snapVincoliDirty = true;
                         }} />
                </td>
                <td>
                  <button class="btn btn-sm btn-outline-danger py-0"
                          onclick={() => snapRemoveVincoloSolver(i)}>
                    <i class="bi bi-x-lg"></i>
                  </button>
                </td>
              </tr>
            {/if}
          {/each}
          </tbody>
        </table>
      {:else}
        <div class="text-muted small mb-2">Nessun limite flag configurato.</div>
      {/if}

      <!-- Limiti mensili max per caratteristica qualitativa -->
      <h6 class="mt-2 mb-2" style="font-size:.82rem">
        Limiti mensili max per caratteristica qualitativa
        <button class="btn btn-sm btn-outline-primary ms-2 py-0" style="font-size:.7rem"
                onclick={() => snapAddVincoloSolver('qualitativo')}>
          <i class="bi bi-plus me-1"></i>Aggiungi
        </button>
      </h6>
      {#if snapVincoliSolver.filter(v => v.tipo === 'qualitativo').length}
        <table class="table table-sm mb-2" style="font-size:.78rem">
          <thead class="table-light"><tr>
            <th>Tipo</th><th style="width:70px">Max N</th>
            <th style="width:45px">Attivo</th><th style="width:35px"></th>
          </tr></thead>
          <tbody>
          {#each snapVincoliSolver as vs, i}
            {#if vs.tipo === 'qualitativo'}
              <tr class={vs.is_active ? '' : 'text-muted'}>
                <td>
                  <select class="form-select form-select-sm" bind:value={vs.ref_id}
                          onchange={() => { snapVincoliDirty = true; }}>
                    <option value={null}>{'\u2014 seleziona tipo \u2014'}</option>
                    {#each solverTipiQual as tq}
                      <option value={tq.id}>{tq.nome}</option>
                    {/each}
                  </select>
                </td>
                <td>
                  <input class="form-control form-control-sm" type="number" bind:value={vs.max_n}
                         onchange={() => { snapVincoliDirty = true; }} />
                </td>
                <td>
                  <input class="form-check-input" type="checkbox" checked={!!vs.is_active}
                         onchange={() => {
                           snapVincoliSolver[i] = { ...vs, is_active: vs.is_active ? 0 : 1 };
                           snapVincoliSolver = [...snapVincoliSolver];
                           snapVincoliDirty = true;
                         }} />
                </td>
                <td>
                  <button class="btn btn-sm btn-outline-danger py-0"
                          onclick={() => snapRemoveVincoloSolver(i)}>
                    <i class="bi bi-x-lg"></i>
                  </button>
                </td>
              </tr>
            {/if}
          {/each}
          </tbody>
        </table>
      {:else}
        <div class="text-muted small mb-2">Nessun limite tipo qualitativo configurato.</div>
      {/if}

      <!-- Azioni salva/ripristina -->
      <div class="mt-2 d-flex gap-2 flex-wrap">
        {#if snapVincoliDirty}
          <button class="btn btn-success btn-sm" style="font-size:.72rem"
                  onclick={snapSalvaVincoli}>
            <i class="bi bi-check-lg me-1"></i>Salva vincoli snapshot
          </button>
          <button class="btn btn-outline-secondary btn-sm" style="font-size:.72rem"
                  onclick={snapResetVincoli}>
            <i class="bi bi-arrow-counterclockwise me-1"></i>Ripristina
          </button>
        {/if}
      </div>
    {/if}

    <!-- TAB: Utenti -->
    {#if solverTab === 'utenti'}
      <div class="small text-muted mb-2">
        Vincoli, limiti ed esclusioni per utente <strong>di questo calendario</strong>.
        Clicca su un utente per espandere. Le modifiche sono salvate nello snapshot con il pulsante nella tab Vincoli.
      </div>
      {#if solverUtenti.length === 0}
        <div class="text-muted small fst-italic">Nessun utente basic trovato.</div>
      {:else}
        <div style="max-height:400px;overflow-y:auto">
          <table class="table table-sm table-hover mb-0" style="font-size:.78rem">
            <thead class="table-light"><tr>
              <th>Utente</th><th>Vincoli override</th><th>Limiti flag/tipo</th><th>Esclusioni flag</th>
            </tr></thead>
            <tbody>
              {#each solverUtenti as u}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
                <tr class="{solverEditUid === u.id ? 'table-warning' : ''}" style="cursor:pointer"
                    onclick={() => solverEspandiUtente(u.id)}>
                  <td class="fw-semibold">{u.sigla || u.username}</td>
                  <td>
                    {#if u.vincoli?.length}
                      {#each u.vincoli as v}<span class="badge bg-info text-dark me-1 mb-1">{v.chiave}={v.valore}</span>{/each}
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
                    {#if u.esclusioni?.length}
                      {#each u.esclusioni as e}<span class="badge bg-danger me-1 mb-1" title={e.note||''}>{e.flag_nome}</span>{/each}
                    {:else}<span class="text-muted fst-italic">—</span>{/if}
                  </td>
                </tr>
                {#if solverEditUid === u.id}
                  <!-- svelte-ignore a11y_click_events_have_key_events -->
                  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
                  <tr><td colspan="4" class="bg-light p-2" onclick={(e) => e.stopPropagation()}>
                    <!-- Vincoli override -->
                    <div class="d-flex align-items-center gap-2 mb-1">
                      <strong style="font-size:.75rem">Vincoli override</strong>
                      <button class="btn btn-sm btn-outline-primary py-0 px-1" style="font-size:.7rem"
                              onclick={() => { solverEditVincoli = [...solverEditVincoli, {chiave:'',valore:'',note:''}]; }}>
                        <i class="bi bi-plus"></i>
                      </button>
                    </div>
                    {#if solverEditVincoli.length}
                      <table class="table table-sm mb-2" style="font-size:.78rem">
                        <thead><tr><th>Chiave</th><th>Valore</th><th>Note</th><th></th></tr></thead>
                        <tbody>
                        {#each solverEditVincoli as vu, i}
                          <tr>
                            <td>
                              <select class="form-select form-select-sm" style="font-size:.78rem" bind:value={vu.chiave} onchange={solverSalvaVincoli}>
                                <option value="">—</option>
                                {#each solverVincoliGlob as vg}<option value={vg.chiave}>{vg.chiave}</option>{/each}
                              </select>
                            </td>
                            <td><input class="form-control form-control-sm" type="number" bind:value={vu.valore} onchange={solverSalvaVincoli} /></td>
                            <td><input class="form-control form-control-sm" bind:value={vu.note} onchange={solverSalvaVincoli} /></td>
                            <td><button class="btn btn-sm btn-outline-danger py-0"
                                        onclick={() => { solverEditVincoli = solverEditVincoli.filter((_,j) => j!==i); solverSalvaVincoli(); }}>
                              <i class="bi bi-x-lg"></i></button></td>
                          </tr>
                        {/each}
                        </tbody>
                      </table>
                    {:else}<div class="text-muted small mb-2">Nessun override.</div>{/if}

                    <!-- Limiti flag/tipo -->
                    <div class="d-flex align-items-center gap-2 mb-1">
                      <strong style="font-size:.75rem">Limiti flag/tipo</strong>
                      <button class="btn btn-sm btn-outline-primary py-0 px-1" style="font-size:.7rem"
                              onclick={() => { solverEditVSolver = [...solverEditVSolver, {tipo:'flag',ref_id:null,max_n:0,note:''}]; }}>
                        <i class="bi bi-plus"></i> Flag
                      </button>
                      <button class="btn btn-sm btn-outline-primary py-0 px-1" style="font-size:.7rem"
                              onclick={() => { solverEditVSolver = [...solverEditVSolver, {tipo:'qualitativo',ref_id:null,max_n:0,note:''}]; }}>
                        <i class="bi bi-plus"></i> Tipo
                      </button>
                    </div>
                    {#if solverEditVSolver.length}
                      <table class="table table-sm mb-2" style="font-size:.78rem">
                        <thead><tr><th>Tipo</th><th>Rif.</th><th style="width:60px">Max</th><th>Note</th><th></th></tr></thead>
                        <tbody>
                        {#each solverEditVSolver as vsu, i}
                          <tr>
                            <td class="small">{vsu.tipo === 'flag' ? 'Flag' : 'Qual.'}</td>
                            <td>
                              {#if vsu.tipo === 'flag'}
                                <select class="form-select form-select-sm" style="font-size:.78rem" bind:value={vsu.ref_id} onchange={solverSalvaVSolver}>
                                  <option value={null}>—</option>
                                  {#each solverFlagTurno.filter(f => f.mostra_in_struttura) as f}<option value={f.id}>{f.nome}</option>{/each}
                                </select>
                              {:else}
                                <select class="form-select form-select-sm" style="font-size:.78rem" bind:value={vsu.ref_id} onchange={solverSalvaVSolver}>
                                  <option value={null}>—</option>
                                  {#each solverTipiQual as tq}<option value={tq.id}>{tq.nome}</option>{/each}
                                </select>
                              {/if}
                            </td>
                            <td><input class="form-control form-control-sm" type="number" bind:value={vsu.max_n} onchange={solverSalvaVSolver} /></td>
                            <td><input class="form-control form-control-sm" bind:value={vsu.note} onchange={solverSalvaVSolver} placeholder="Note" /></td>
                            <td><button class="btn btn-sm btn-outline-danger py-0"
                                        onclick={() => { solverEditVSolver = solverEditVSolver.filter((_,j) => j!==i); solverSalvaVSolver(); }}>
                              <i class="bi bi-x-lg"></i></button></td>
                          </tr>
                        {/each}
                        </tbody>
                      </table>
                    {:else}<div class="text-muted small mb-2">Nessun limite.</div>{/if}

                    <!-- Esclusioni flag -->
                    <div class="d-flex align-items-center gap-2 mb-1">
                      <strong style="font-size:.75rem">Esclusioni turno (flag)</strong>
                      <button class="btn btn-sm btn-outline-primary py-0 px-1" style="font-size:.7rem"
                              onclick={() => { solverEditEscl = [...solverEditEscl, {flag_id:null,flag_nome:'',note:''}]; }}>
                        <i class="bi bi-plus"></i>
                      </button>
                    </div>
                    {#if solverEditEscl.length}
                      <table class="table table-sm mb-0" style="font-size:.78rem">
                        <thead><tr><th>Flag escluso</th><th>Note</th><th></th></tr></thead>
                        <tbody>
                        {#each solverEditEscl as eu, i}
                          <tr>
                            <td>
                              <select class="form-select form-select-sm" style="font-size:.78rem" bind:value={eu.flag_id} onchange={solverSalvaEscl}>
                                <option value={null}>— flag —</option>
                                {#each solverFlagTurno.filter(f => f.mostra_in_struttura) as f}
                                  <option value={f.id}>{f.nome}{f.parent_nome ? ` (${f.parent_nome})` : ''}</option>
                                {/each}
                              </select>
                            </td>
                            <td><input class="form-control form-control-sm" bind:value={eu.note} onchange={solverSalvaEscl} placeholder="Note" /></td>
                            <td><button class="btn btn-sm btn-outline-danger py-0"
                                        onclick={() => { solverEditEscl = solverEditEscl.filter((_,j) => j!==i); solverSalvaEscl(); }}>
                              <i class="bi bi-x-lg"></i></button></td>
                          </tr>
                        {/each}
                        </tbody>
                      </table>
                    {:else}<div class="text-muted small">Nessuna esclusione.</div>{/if}
                  </td></tr>
                {/if}
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    {/if}

    <!-- TAB: Turni (selezione turni su cui operare) -->
    {#if solverTab === 'turni'}
      <div class="mb-2">
        <div class="form-check mb-2">
          <input class="form-check-input" type="checkbox" id="sv-turni-tutti"
                 checked={solverTurniTutti}
                 onchange={() => {
                   solverTurniTutti = !solverTurniTutti;
                   if (solverTurniTutti) solverTurniSel = _turniAllLocalIds();
                 }} />
          <label class="form-check-label small fw-bold" for="sv-turni-tutti">Tutti i turni</label>
        </div>
        {#if !solverTurniTutti}
          <p class="text-muted small mb-2">Seleziona i turni su cui il solver deve operare.</p>
          <div class="border rounded p-2 mb-2" style="max-height:300px; overflow-y:auto; font-size:.8rem">
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="az-row fw-bold" onclick={() => { solverTurniSel = _turniToggleTutti(solverTurniSel); }}>
              <span class="az-check">{solverTurniSel.length === _turniAllLocalIds().length ? '☑' : solverTurniSel.length > 0 ? '☒' : '☐'}</span>
              Tutti
            </div>
            <hr class="my-1">
            {#each (struttura?.sovragruppi ?? []) as sg}
              {@const sgTurniAcc = sg.gruppi.flatMap(g => g.turni.filter(t => t.accessibile !== false))}
              {#if sgTurniAcc.length > 0}
                {@const sgIds = sgTurniAcc.map(t => t.local_id)}
                {@const sgAll = sgIds.every(id => solverTurniSel.includes(id))}
                {@const sgSome = !sgAll && sgIds.some(id => solverTurniSel.includes(id))}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div class="az-row ms-1 fw-semibold" onclick={(e) => { e.stopPropagation(); solverTurniSel = _turniToggleSG(solverTurniSel, sg); }}>
                  <span class="az-check">{sgAll ? '☑' : sgSome ? '☒' : '☐'}</span>
                  {sg.sigla} — {sg.nome}
                </div>
                {#each sg.gruppi as g}
                  {@const gTurniAcc = g.turni.filter(t => t.accessibile !== false)}
                  {#if gTurniAcc.length > 0}
                    {@const gIds = gTurniAcc.map(t => t.local_id)}
                    {@const gAll = gIds.every(id => solverTurniSel.includes(id))}
                    {@const gSome = !gAll && gIds.some(id => solverTurniSel.includes(id))}
                    <!-- svelte-ignore a11y_click_events_have_key_events -->
                    <!-- svelte-ignore a11y_no_static_element_interactions -->
                    <div class="az-row ms-3" onclick={(e) => { e.stopPropagation(); solverTurniSel = _turniToggleGruppo(solverTurniSel, g); }}>
                      <span class="az-check">{gAll ? '☑' : gSome ? '☒' : '☐'}</span>
                      {g.sigla} — {g.nome}
                    </div>
                    {#each gTurniAcc as t}
                      <!-- svelte-ignore a11y_click_events_have_key_events -->
                      <!-- svelte-ignore a11y_no_static_element_interactions -->
                      <div class="az-row ms-5" onclick={(e) => { e.stopPropagation(); solverTurniSel = _turniToggleTurno(solverTurniSel, t.local_id); }}>
                        <span class="az-check">{solverTurniSel.includes(t.local_id) ? '☑' : '☐'}</span>
                        {t.sigla}
                      </div>
                    {/each}
                  {/if}
                {/each}
              {/if}
            {/each}
          </div>
          <span class="text-muted small">{solverTurniSel.length} turni selezionati</span>
        {/if}
      </div>
    {/if}

    <!-- TAB: Accesso -->
    {#if solverTab === 'accesso'}
      {#if solverOrfani?.has_orfani}
        <div class="alert alert-warning py-2 px-3 mb-2" style="font-size:.78rem">
          <i class="bi bi-exclamation-triangle-fill me-1"></i>
          <strong>Riferimenti orfani nella gestione accessi.</strong>
          {#if solverOrfani.turni.length > 0}
            {solverOrfani.turni.length} turni eliminati dalla struttura.
          {/if}
          {#if solverOrfani.utenti.length > 0}
            {solverOrfani.utenti.length} utenti non più attivi.
          {/if}
          {#if solverOrfani.managers.length > 0}
            {solverOrfani.managers.length} manager non più attivi.
          {/if}
          <span class="d-block mt-1">Ricontrollare la gestione accessi nel pannello Admin.</span>
        </div>
      {/if}
      {@const allTurni = (struttura?.sovragruppi || []).flatMap(sg => sg.gruppi.flatMap(g => g.turni.map(t => ({...t, sg_sigla: sg.sigla, gruppo_sigla: g.sigla}))))}
      {@const turniAcc = allTurni.filter(t => t.accessibile)}
      {@const turniNo = allTurni.filter(t => !t.accessibile)}
      {@const accSet = _utentiAccessibili ? new Set(_utentiAccessibili) : null}
      {@const utentiAcc = accSet ? utenti.filter(u => accSet.has(u.id)) : utenti}
      {@const utentiNo = accSet ? utenti.filter(u => !accSet.has(u.id)) : []}
      <div class="row g-3" style="font-size:.78rem">
        <div class="col-md-6">
          <h6 class="mb-1"><i class="bi bi-check-circle text-success me-1"></i>Turni accessibili ({turniAcc.length}/{allTurni.length})</h6>
          {#if turniAcc.length === allTurni.length}
            <div class="text-muted small fst-italic">Tutti i turni sono accessibili.</div>
          {:else}
            <div style="max-height:180px;overflow-y:auto">
              <table class="table table-sm mb-0">
                <tbody>
                  {#each turniAcc as t}
                    <tr><td><span class="badge bg-success me-1">{t.sg_sigla}</span>{t.sigla}</td></tr>
                  {/each}
                </tbody>
              </table>
            </div>
            {#if turniNo.length > 0}
              <h6 class="mt-2 mb-1"><i class="bi bi-x-circle text-danger me-1"></i>Non accessibili ({turniNo.length})</h6>
              <div style="max-height:120px;overflow-y:auto">
                <table class="table table-sm mb-0">
                  <tbody>
                    {#each turniNo as t}
                      <tr class="text-muted"><td><span class="badge bg-secondary me-1">{t.sg_sigla}</span>{t.sigla}</td></tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          {/if}
        </div>
        <div class="col-md-6">
          <h6 class="mb-1"><i class="bi bi-check-circle text-success me-1"></i>Utenti gestibili ({utentiAcc.length}/{utenti.length})</h6>
          {#if !accSet}
            <div class="text-muted small fst-italic">Tutti gli utenti sono gestibili.</div>
          {:else}
            <div style="max-height:180px;overflow-y:auto">
              <table class="table table-sm mb-0">
                <tbody>
                  {#each utentiAcc as u}
                    <tr><td>{u.sigla}</td></tr>
                  {/each}
                </tbody>
              </table>
            </div>
            {#if utentiNo.length > 0}
              <h6 class="mt-2 mb-1"><i class="bi bi-x-circle text-danger me-1"></i>Non gestibili ({utentiNo.length})</h6>
              <div style="max-height:120px;overflow-y:auto">
                <table class="table table-sm mb-0">
                  <tbody>
                    {#each utentiNo as u}
                      <tr class="text-muted"><td>{u.sigla}</td></tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          {/if}
        </div>
      </div>
    {/if}

    <!-- TAB: Escludi giorno -->
    {#if solverTab === 'escl_giorno'}
      <div class="small text-muted mb-2">
        Utenti esclusi dal solver/optimizer per giorni specifici (oltre ai desiderata assenza).
      </div>

      {#if esclusioni.length > 0}
        <div style="max-height:200px;overflow-y:auto" class="mb-3">
          <table class="table table-sm mb-0" style="font-size:.8rem">
            <thead class="table-light"><tr>
              <th>Utente</th><th>Tipo</th><th>Dettaglio</th><th>Motivo</th><th style="width:30px"></th>
            </tr></thead>
            <tbody>
            {#each esclusioni as esc, i}
              <tr>
                <td>{utenti.find(u => u.id === esc.user_id)?.sigla || esc.user_id}</td>
                <td><span class="badge bg-secondary">{esc.tipo}</span></td>
                <td class="small">
                  {#if esc.tipo === 'giorno'}g.{esc.giorno}
                  {:else if esc.tipo === 'intervallo'}g.{esc.giorno_da}-{esc.giorno_a}
                  {:else}{(esc.giorni_settimana || []).map(d => ['L','M','Me','G','V','S','D'][d]).join(', ')}
                  {/if}
                </td>
                <td class="small text-muted">{esc.motivo || ''}</td>
                <td><button class="btn btn-sm btn-outline-danger py-0" onclick={() => esclRimuovi(i)}><i class="bi bi-x-lg"></i></button></td>
              </tr>
            {/each}
            </tbody>
          </table>
        </div>
      {:else}
        <div class="text-muted small fst-italic mb-3">Nessuna esclusione configurata.</div>
      {/if}

      <div class="border rounded p-2 mb-3 bg-light">
        <div class="row g-2 align-items-end">
          <div class="col-auto">
            <label class="form-label small mb-0">Utente</label>
            <select class="form-select form-select-sm" style="width:120px"
                    bind:value={esclNuova.user_id}>
              <option value={null}>— scegli —</option>
              {#each utenti as u}
                <option value={u.id}>{u.sigla}</option>
              {/each}
            </select>
          </div>
          <div class="col-auto">
            <label class="form-label small mb-0">Tipo</label>
            <select class="form-select form-select-sm" style="width:140px"
                    bind:value={esclNuova.tipo}>
              <option value="giorno">Giorno singolo</option>
              <option value="intervallo">Intervallo</option>
              <option value="giorno_settimana">Giorno settimana</option>
            </select>
          </div>

          {#if esclNuova.tipo === 'giorno'}
            <div class="col-auto">
              <label class="form-label small mb-0">Giorno</label>
              <input type="number" class="form-control form-control-sm" style="width:70px"
                     bind:value={esclNuova.giorno} min="1" max="31" />
            </div>
          {:else if esclNuova.tipo === 'intervallo'}
            <div class="col-auto">
              <label class="form-label small mb-0">Da</label>
              <input type="number" class="form-control form-control-sm" style="width:60px"
                     bind:value={esclNuova.giorno_da} min="1" max="31" />
            </div>
            <div class="col-auto">
              <label class="form-label small mb-0">A</label>
              <input type="number" class="form-control form-control-sm" style="width:60px"
                     bind:value={esclNuova.giorno_a} min="1" max="31" />
            </div>
          {:else}
            <div class="col-auto">
              <label class="form-label small mb-0">Giorni</label>
              <div class="d-flex gap-1">
                {#each ['L','M','Me','G','V','S','D'] as label, dow}
                  <button class="btn btn-sm {(esclNuova.giorni_settimana || []).includes(dow) ? 'btn-primary' : 'btn-outline-secondary'} py-0"
                          style="font-size:.7rem;width:28px" onclick={() => esclToggleDow(dow)}>
                    {label}
                  </button>
                {/each}
              </div>
            </div>
          {/if}

          <div class="col-auto">
            <label class="form-label small mb-0">Motivo</label>
            <input class="form-control form-control-sm" style="width:120px"
                   bind:value={esclNuova.motivo} placeholder="Opzionale" />
          </div>
          <div class="col-auto">
            <button class="btn btn-sm btn-outline-primary" onclick={esclAggiungi}
                    disabled={!esclNuova.user_id}>
              <i class="bi bi-plus"></i>
            </button>
          </div>
        </div>
      </div>

      <button class="btn btn-success btn-sm" onclick={esclSalva}>
        <i class="bi bi-check me-1"></i>Salva esclusioni giorno
      </button>
    {/if}

    <!-- TAB: Escludi turno -->
    {#if solverTab === 'escl_turno'}
      <div class="p-2">
        <p class="text-muted small mb-2">
          Esclusioni per-utente valide solo per questo calendario. Non modificano il preset.
        </p>

        <!-- Form aggiungi esclusione -->
        <div class="d-flex gap-1 align-items-end mb-2 flex-wrap">

          <!-- Dropdown multi-checkbox utenti (add) -->
          <div>
            <label class="form-label small mb-0">Utenti</label>
            <div class="position-relative" use:clickOutside={() => (etUserDropOpen = false)}>
              <button class="btn btn-sm btn-outline-secondary d-flex align-items-center gap-1"
                      style="min-width:90px"
                      onclick={() => (etUserDropOpen = !etUserDropOpen)}
                      type="button">
                <span class="flex-grow-1 text-start">
                  {etForm.users.length === 0 ? '—' : etForm.users.length === 1
                    ? (utenti.find(u => u.id === etForm.users[0])?.sigla ?? '?')
                    : `${etForm.users.length} utenti`}
                </span>
                <i class="bi bi-chevron-down small"></i>
              </button>
              {#if etUserDropOpen}
                <div class="dropdown-menu show p-1 shadow-sm" style="min-width:130px;z-index:1060">
                  {#each utenti as u}
                    <label class="dropdown-item d-flex align-items-center gap-2 py-1 small"
                           style="cursor:pointer">
                      <input type="checkbox"
                             checked={etForm.users.includes(u.id)}
                             onchange={() => _etToggleUser(etForm, u.id)} />
                      {u.sigla}
                    </label>
                  {/each}
                </div>
              {/if}
            </div>
          </div>

          <!-- Livello -->
          <div>
            <label class="form-label small mb-0">Livello</label>
            <select class="form-select form-select-sm" style="min-width:110px"
                    bind:value={etForm.tipo}
                    onchange={() => (etForm.target_id = null)}>
              <option value="turno">Turno</option>
              <option value="gruppo">Gruppo</option>
              <option value="sovragruppo">Sovragruppo</option>
            </select>
          </div>

          <!-- Target -->
          <div class="flex-grow-1">
            <label class="form-label small mb-0">Target</label>
            <select class="form-select form-select-sm" bind:value={etForm.target_id}>
              <option value={null}>—</option>
              {#each _etTargets(etForm.tipo) as t}
                <option value={t.id}>{t.label}</option>
              {/each}
            </select>
          </div>

          <button class="btn btn-sm btn-outline-primary"
                  onclick={etAggiungi}
                  disabled={etForm.users.length === 0 || !etForm.target_id}
                  title="Aggiungi esclusione">
            <i class="bi bi-plus-lg"></i>
          </button>
        </div>

        <!-- Lista esclusioni correnti -->
        {#if etData.length === 0}
          <div class="text-muted small fst-italic text-center py-2">
            Nessuna esclusione configurata.
          </div>
        {:else}
          <div class="list-group list-group-flush" style="max-height:240px;overflow-y:auto">
            {#each etData as esc, idx}
              {#if etEditIdx === idx}
                <!-- Riga in edit mode -->
                <div class="list-group-item py-1 px-2">
                  <div class="d-flex gap-1 align-items-center flex-wrap">

                    <!-- Dropdown multi-checkbox utenti (edit) -->
                    <div class="position-relative" use:clickOutside={() => (etEditDropOpen = false)}>
                      <button class="btn btn-sm btn-outline-secondary d-flex align-items-center gap-1"
                              style="min-width:80px"
                              onclick={() => (etEditDropOpen = !etEditDropOpen)}
                              type="button">
                        <span class="flex-grow-1 text-start small">
                          {etEditForm.users.length === 0 ? '—' : etEditForm.users.length === 1
                            ? (utenti.find(u => u.id === etEditForm.users[0])?.sigla ?? '?')
                            : `${etEditForm.users.length} ut.`}
                        </span>
                        <i class="bi bi-chevron-down small"></i>
                      </button>
                      {#if etEditDropOpen}
                        <div class="dropdown-menu show p-1 shadow-sm" style="min-width:130px;z-index:1060">
                          {#each utenti as u}
                            <label class="dropdown-item d-flex align-items-center gap-2 py-1 small"
                                   style="cursor:pointer">
                              <input type="checkbox"
                                     checked={etEditForm.users.includes(u.id)}
                                     onchange={() => _etToggleUser(etEditForm, u.id)} />
                              {u.sigla}
                            </label>
                          {/each}
                        </div>
                      {/if}
                    </div>

                    <select class="form-select form-select-sm" style="min-width:100px"
                            bind:value={etEditForm.tipo}
                            onchange={() => (etEditForm.target_id = null)}>
                      <option value="turno">Turno</option>
                      <option value="gruppo">Gruppo</option>
                      <option value="sovragruppo">Sovragruppo</option>
                    </select>

                    <select class="form-select form-select-sm flex-grow-1"
                            bind:value={etEditForm.target_id}>
                      <option value={null}>—</option>
                      {#each _etTargets(etEditForm.tipo) as t}
                        <option value={t.id}>{t.label}</option>
                      {/each}
                    </select>

                    <button class="btn btn-sm btn-success py-0 px-1"
                            onclick={etSalvaEdit}
                            disabled={etEditForm.users.length === 0 || !etEditForm.target_id}
                            title="Conferma">
                      <i class="bi bi-check-lg"></i>
                    </button>
                    <button class="btn btn-sm btn-secondary py-0 px-1"
                            onclick={etAnnullaEdit}
                            title="Annulla">
                      <i class="bi bi-x-lg"></i>
                    </button>
                  </div>
                </div>
              {:else}
                <!-- Riga visualizzazione -->
                {@const u = utenti.find(x => x.id === esc.user_id)}
                {@const figli = (esc.tipo === 'gruppo' || esc.tipo === 'sovragruppo') ? _etFigli(esc) : []}
                <div class="list-group-item py-1 px-2 small">
                  <div class="d-flex align-items-center gap-2">
                    <span class="badge bg-secondary">{u?.sigla ?? esc.user_id}</span>
                    <span class="badge bg-light text-dark border">{esc.tipo}</span>
                    <span class="text-truncate flex-grow-1">{_etLabel(esc)}</span>
                    <button class="btn btn-sm btn-link text-primary p-0"
                            onclick={() => etAvviaEdit(idx)}
                            title="Modifica">
                      <i class="bi bi-pencil-fill"></i>
                    </button>
                    <button class="btn btn-sm btn-link text-danger p-0"
                            onclick={() => etRimuovi(idx)}
                            title="Rimuovi">
                      <i class="bi bi-x-lg"></i>
                    </button>
                  </div>
                  {#if figli.length > 0}
                    <div class="mt-1 ms-4" style="font-size:.75rem">
                      <span class="text-muted fst-italic">Tranne:</span>
                      <div class="d-flex gap-2 flex-wrap mt-1">
                        {#each figli as figlio}
                          <label class="form-check-label d-flex align-items-center gap-1" style="cursor:pointer">
                            <input type="checkbox" class="form-check-input" style="width:.8em;height:.8em"
                                   checked={(esc.eccezioni ?? []).includes(figlio.id)}
                                   onchange={() => etToggleEccezione(idx, figlio.id)} />
                            {figlio.label}
                          </label>
                        {/each}
                      </div>
                    </div>
                  {/if}
                </div>
              {/if}
            {/each}
          </div>
        {/if}

        <!-- Azioni salva/annulla -->
        {#if etDirty}
          <div class="d-flex gap-2 mt-2 justify-content-end">
            <button class="btn btn-sm btn-outline-secondary" onclick={etAnnulla}>
              Annulla
            </button>
            <button class="btn btn-sm btn-primary" onclick={etSalva} disabled={etLoading}>
              {#if etLoading}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
              Salva
            </button>
          </div>
        {/if}
      </div>
    {/if}

    <!-- Azioni + Risultato (sempre visibili) -->
    <hr class="my-2">
    <div class="d-flex gap-2 mb-2">
      <button class="btn btn-outline-primary btn-sm" onclick={solverAnteprima} disabled={solverLoading}>
        {#if solverLoading}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
        <i class="bi bi-eye me-1"></i>Anteprima
      </button>
      <button class="btn btn-warning btn-sm" onclick={solverEsegui} disabled={solverLoading}>
        {#if solverLoading}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
        <i class="bi bi-play-fill me-1"></i>Esegui
      </button>
    </div>

    {#if solverResult}
      <div class="solver-result p-2 rounded" class:border-success={solverResult.ok} class:border-danger={!solverResult.ok}>
        {#if solverResult.ok}
          <div class="small fw-semibold mb-1">
            {solverResult.dry_run ? 'Anteprima' : 'Eseguito'}
            — {solverResult.celle_riempite}/{solverResult.celle_totali} celle
            {#if solverResult.celle_fallite > 0}
              <span class="text-danger">({solverResult.celle_fallite} non coperte)</span>
            {/if}
            {#if solverResult.indispensabili_scoperti > 0}
              <span class="text-danger fw-bold">⚠ {solverResult.indispensabili_scoperti} indispensabili scoperti!</span>
            {/if}
          </div>
          <div class="small text-muted">
            {solverResult.durata_ms}ms
            {#if solverResult.multi_start}
              — Multi-start: {solverResult.n_runs} run, costo migliore {solverResult.costo_migliore}
            {/if}
          </div>
          {#if solverResult.dry_run && solverResult.proposte?.length}
            <div class="mt-2" style="max-height:200px;overflow-y:auto">
              <table class="table table-sm mb-0" style="font-size:.75rem">
                <thead><tr><th>G.</th><th>Turno</th><th>Utente</th><th>Score</th></tr></thead>
                <tbody>
                {#each solverResult.proposte as p}
                  <tr>
                    <td>{p.giorno}</td>
                    <td>{p.turno_sigla}</td>
                    <td>{p.user_sigla}</td>
                    <td>{p.score}</td>
                  </tr>
                {/each}
                </tbody>
              </table>
            </div>
          {/if}
          {#if solverResult.fallite?.length}
            <div class="mt-2 small text-danger">
              <strong>Non coperte:</strong>
              {#each solverResult.fallite as f}
                <span class="badge bg-danger me-1">{f.turno_sigla} g.{f.giorno}</span>
              {/each}
            </div>
          {/if}
        {:else}
          <div class="small text-danger">{solverResult.errore || 'Errore'}</div>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<!-- ── MODALE OPTIMIZER ────────────────────────────────────────── -->
{#if optOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-backdrop-custom" onclick={() => { optOpen = false; }}></div>
  <div class="solver-modal">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h6 class="mb-0"><i class="bi bi-sliders2 me-1"></i>Ottimizzazione</h6>
      <button class="btn-close btn-close-sm" onclick={() => { optOpen = false; }}></button>
    </div>

    <div class="mb-3">
      <label class="form-label small fw-bold mb-1">Preset</label>
      {#if optPresets.length === 0}
        <div class="text-muted small fst-italic">Nessun preset attivo.</div>
      {:else}
        <select class="form-select form-select-sm"
                bind:value={optPresetId}>
          {#each optPresets as p}
            <option value={p.id}>{p.nome} ({p.tipo})</option>
          {/each}
        </select>
      {/if}
    </div>

    <div class="mb-3">
      <label class="form-label small fw-bold mb-1">Max iterazioni</label>
      <input type="number" class="form-control form-control-sm" style="width:120px"
             bind:value={optMaxIter} min="100" max="10000" step="100" />
    </div>

    <div class="form-check mb-2">
      <input class="form-check-input" type="checkbox" id="opt-sa"
             bind:checked={optUsaSA} />
      <label class="form-check-label small" for="opt-sa">Simulated Annealing</label>
    </div>

    {#if optUsaSA}
    <div class="mb-3 ps-3 border-start" style="border-color:#0d6efd!important">
      <div class="row g-2 mb-1">
        <div class="col-6">
          <label class="form-label small mb-0">Temperatura</label>
          <input type="number" class="form-control form-control-sm"
                 bind:value={optTempIni} min="0.001" max="10" step="0.01" />
        </div>
        <div class="col-6">
          <label class="form-label small mb-0">Raffreddamento</label>
          <input type="number" class="form-control form-control-sm"
                 bind:value={optRaffredd} min="0.9" max="0.999" step="0.001" />
        </div>
      </div>
      <div class="text-muted" style="font-size:.7rem">SA esplora soluzioni peggiori per sfuggire ai minimi locali, poi rifinisce con HC.</div>
    </div>
    {/if}

    <hr class="my-2"/>
    <div class="mb-2">
      <div class="form-check mb-2">
        <input class="form-check-input" type="checkbox" id="opt-turni-tutti"
               checked={optTurniTutti}
               onchange={() => {
                 optTurniTutti = !optTurniTutti;
                 if (optTurniTutti) optTurniSel = _turniAllLocalIds();
               }} />
        <label class="form-check-label small fw-bold" for="opt-turni-tutti">Tutti i turni</label>
      </div>
      {#if !optTurniTutti}
        <p class="text-muted small mb-2">Seleziona i turni da ottimizzare (swap solo tra celle selezionate, costo calcolato su tutti).</p>
        <div class="border rounded p-2 mb-2" style="max-height:250px; overflow-y:auto; font-size:.8rem">
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div class="az-row fw-bold" onclick={() => { optTurniSel = _turniToggleTutti(optTurniSel); }}>
            <span class="az-check">{optTurniSel.length === _turniAllLocalIds().length ? '☑' : optTurniSel.length > 0 ? '☒' : '☐'}</span>
            Tutti
          </div>
          <hr class="my-1">
          {#each (struttura?.sovragruppi ?? []) as sg}
            {@const sgTurniAcc = sg.gruppi.flatMap(g => g.turni.filter(t => t.accessibile !== false))}
            {#if sgTurniAcc.length > 0}
              {@const sgIds = sgTurniAcc.map(t => t.local_id)}
              {@const sgAll = sgIds.every(id => optTurniSel.includes(id))}
              {@const sgSome = !sgAll && sgIds.some(id => optTurniSel.includes(id))}
              <!-- svelte-ignore a11y_click_events_have_key_events -->
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div class="az-row ms-1 fw-semibold" onclick={(e) => { e.stopPropagation(); optTurniSel = _turniToggleSG(optTurniSel, sg); }}>
                <span class="az-check">{sgAll ? '☑' : sgSome ? '☒' : '☐'}</span>
                {sg.sigla} — {sg.nome}
              </div>
              {#each sg.gruppi as g}
                {@const gTurniAcc = g.turni.filter(t => t.accessibile !== false)}
                {#if gTurniAcc.length > 0}
                  {@const gIds = gTurniAcc.map(t => t.local_id)}
                  {@const gAll = gIds.every(id => optTurniSel.includes(id))}
                  {@const gSome = !gAll && gIds.some(id => optTurniSel.includes(id))}
                  <!-- svelte-ignore a11y_click_events_have_key_events -->
                  <!-- svelte-ignore a11y_no_static_element_interactions -->
                  <div class="az-row ms-3" onclick={(e) => { e.stopPropagation(); optTurniSel = _turniToggleGruppo(optTurniSel, g); }}>
                    <span class="az-check">{gAll ? '☑' : gSome ? '☒' : '☐'}</span>
                    {g.sigla} — {g.nome}
                  </div>
                  {#each gTurniAcc as t}
                    <!-- svelte-ignore a11y_click_events_have_key_events -->
                    <!-- svelte-ignore a11y_no_static_element_interactions -->
                    <div class="az-row ms-5" onclick={(e) => { e.stopPropagation(); optTurniSel = _turniToggleTurno(optTurniSel, t.local_id); }}>
                      <span class="az-check">{optTurniSel.includes(t.local_id) ? '☑' : '☐'}</span>
                      {t.sigla}
                    </div>
                  {/each}
                {/if}
              {/each}
            {/if}
          {/each}
        </div>
        <span class="text-muted small">{optTurniSel.length} turni selezionati</span>
      {/if}
    </div>

    <div class="form-check mb-3">
      <input class="form-check-input" type="checkbox" id="opt-preview"
             bind:checked={optPreview} />
      <label class="form-check-label small" for="opt-preview">Solo anteprima (non modifica)</label>
    </div>

    <div class="d-flex gap-2 mb-2">
      <button class="btn btn-primary btn-sm" onclick={optEsegui}
              disabled={optLoading || optPresets.length === 0}>
        {#if optLoading}
          <span class="spinner-border spinner-border-sm me-1"></span>
        {/if}
        {optPreview ? 'Anteprima' : 'Ottimizza'}
      </button>
    </div>

    {#if optResult}
      <div class="mt-2 p-2 border rounded" style="font-size:.8rem">
        {#if optResult.ok}
          <div class="mb-1"><strong>Modalità:</strong> {optResult.modalita === 'sa' ? 'Simulated Annealing + HC' : 'Hill Climbing'}</div>
          <div class="mb-1"><strong>Swap effettuati:</strong> {optResult.swap_count}</div>
          <div class="mb-1"><strong>Costo iniziale:</strong> {optResult.costo_iniziale.toFixed(4)}</div>
          <div class="mb-1"><strong>Costo finale:</strong> {optResult.costo_finale.toFixed(4)}</div>
          <div class="mb-1"><strong>Miglioramento:</strong>
            <span class="{optResult.delta_pct > 0 ? 'text-success' : 'text-muted'}">
              {optResult.delta_pct > 0 ? '-' : ''}{Math.abs(optResult.delta_pct)}%
            </span>
          </div>
          <div class="text-muted">{optResult.durata_ms}ms</div>
          {#if optResult.swap_count === 0}
            <div class="text-muted mt-1">Nessuno swap migliorativo trovato.</div>
          {/if}
        {:else}
          <div class="small text-danger">{optResult.errore || 'Errore'}</div>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<!-- ── MODALE ESCLUSIONI MANUALI ────────────────────────────────── -->

<!-- ── MODALE APERTURE ─────────────────────────────────────────── -->
{#if apertureOpen && struttura}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-backdrop-custom" onclick={() => { apertureOpen = false; }}></div>
  <div class="aperture-modal">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h6 class="mb-0"><i class="bi bi-calendar2-check me-1"></i>Aperture turni</h6>
      <button class="btn-close btn-close-sm" onclick={() => { apertureOpen = false; }}></button>
    </div>
    <p class="small text-muted mb-2">
      Per ogni turno: abilita festivi (domeniche) e superfestivi, oppure seleziona giorni specifici da aprire.
    </p>

    <div class="aperture-scroll">
      <table class="table table-sm table-bordered mb-0" style="font-size:.78rem">
        <thead class="table-light">
          <tr>
            <th style="min-width:120px">Turno</th>
            <th style="width:30px" title="Apri festivi (domeniche)">F</th>
            <th style="width:30px" title="Apri superfestivi">SF</th>
            <th>Aperture straordinarie (clicca giorno)</th>
          </tr>
        </thead>
        <tbody>
          {#each apertureTurni as t, tIdx}
            <tr>
              <td class="fw-semibold">{t.sigla} <span class="text-muted fw-normal">({t.gruppo})</span></td>
              <td class="text-center">
                <input type="checkbox" checked={t.apri_festivi}
                       onchange={() => { apertureTurni[tIdx] = { ...t, apri_festivi: t.apri_festivi ? 0 : 1 }; }} />
              </td>
              <td class="text-center">
                <input type="checkbox" checked={t.apri_superfestivi}
                       onchange={() => { apertureTurni[tIdx] = { ...t, apri_superfestivi: t.apri_superfestivi ? 0 : 1 }; }} />
              </td>
              <td>
                <div class="d-flex flex-wrap gap-0" style="line-height:1">
                  {#each Array(numGiorni) as _, i}
                    {@const g = i + 1}
                    {@const tipo = tipoGiorno(g)}
                    {@const isNonFeriale = tipo === 'festivo' || tipo === 'superfestivo'}
                    {@const isAp = t.aperture_straordinarie.includes(g)}
                    {#if isNonFeriale}
                      <button
                        class="ap-day-btn {isAp ? 'ap-active' : ''} {tipo === 'superfestivo' ? 'ap-super' : 'ap-fest'}"
                        title="Giorno {g} ({tipo}{isAp ? ', apertura straordinaria' : ''})"
                        onclick={() => apertureToggleGiorno(tIdx, g)}>
                        {g}
                      </button>
                    {/if}
                  {/each}
                  {#if !struttura.giorni.some(g => (g.tipo === 'festivo' || g.tipo === 'superfestivo'))}
                    <span class="text-muted">Nessun giorno non-feriale</span>
                  {/if}
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="d-flex justify-content-end gap-2 mt-3">
      <button class="btn btn-secondary btn-sm" onclick={() => { apertureOpen = false; }}>Annulla</button>
      <button class="btn btn-primary btn-sm" onclick={apertureSalva} disabled={apertureSaving}>
        {#if apertureSaving}
          <span class="spinner-border spinner-border-sm me-1"></span>
        {/if}
        Salva
      </button>
    </div>
  </div>
{/if}

<!-- ── MODALE AZZERA ────────────────────────────────────────────── -->
{#if azzeraOpen && struttura}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-backdrop-custom" onclick={() => { azzeraOpen = false; }}></div>
  <div class="pf-modal" style="min-width:400px; max-width:550px">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h6 class="mb-0"><i class="bi bi-trash me-1"></i>Azzera assegnazioni</h6>
      <button class="btn-close btn-close-sm" onclick={() => { azzeraOpen = false; }}></button>
    </div>
    <p class="text-muted small mb-2">Seleziona i turni da azzerare. L'operazione è annullabile (Ctrl+Z).</p>

    <div class="border rounded p-2 mb-3" style="max-height:350px; overflow-y:auto; font-size:.8rem">
      <!-- Seleziona tutti -->
      {#each [struttura.sovragruppi.reduce((s, sg) => s + sg.gruppi.reduce((s2, g) => s2 + g.turni.length, 0), 0)] as _azTotale}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="az-row fw-bold" onclick={_azzeraToggleTutti}>
        <span class="az-check">{azzeraSel.length === _azTotale ? '☑' : azzeraSel.length > 0 ? '☐' : '☐'}</span>
        Tutti
      </div>
      {/each}
      <hr class="my-1">

      {#each struttura.sovragruppi as sg}
        {@const sgTurniAcc = sg.gruppi.flatMap(g => g.turni.filter(t => t.accessibile !== false))}
        {#if sgTurniAcc.length > 0}
          {@const sgIds = sgTurniAcc.map(t => t.id)}
          {@const sgAll = sgIds.every(id => azzeraSel.includes(id))}
          {@const sgSome = !sgAll && sgIds.some(id => azzeraSel.includes(id))}
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div class="az-row ms-1 fw-semibold" onclick={(e) => { e.stopPropagation(); _azzeraToggleSG(sg); }}>
            <span class="az-check">{sgAll ? '☑' : sgSome ? '☒' : '☐'}</span>
            {sg.sigla} — {sg.nome}
          </div>
          {#each sg.gruppi as g}
            {@const gTurniAcc = g.turni.filter(t => t.accessibile !== false)}
            {#if gTurniAcc.length > 0}
              {@const gIds = gTurniAcc.map(t => t.id)}
              {@const gAll = gIds.every(id => azzeraSel.includes(id))}
              {@const gSome = !gAll && gIds.some(id => azzeraSel.includes(id))}
              <!-- svelte-ignore a11y_click_events_have_key_events -->
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div class="az-row ms-3" onclick={(e) => { e.stopPropagation(); _azzeraToggleGruppo(g); }}>
                <span class="az-check">{gAll ? '☑' : gSome ? '☒' : '☐'}</span>
                {g.sigla} — {g.nome}
              </div>
              {#each gTurniAcc as t}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div class="az-row ms-5" onclick={(e) => { e.stopPropagation(); _azzeraToggleTurno(t.id); }}>
                  <span class="az-check">{azzeraSel.includes(t.id) ? '☑' : '☐'}</span>
                  {t.sigla}
                </div>
              {/each}
            {/if}
          {/each}
        {/if}
      {/each}
    </div>

    <div class="d-flex justify-content-between align-items-center">
      <span class="text-muted small">{azzeraSel.length} turni selezionati</span>
      <div class="d-flex gap-2">
        <button class="btn btn-secondary btn-sm" onclick={() => { azzeraOpen = false; }}>Annulla</button>
        <button class="btn btn-danger btn-sm" onclick={azzeraConferma}
                disabled={azzeraLoading || azzeraSel.length === 0}>
          {#if azzeraLoading}
            <span class="spinner-border spinner-border-sm me-1"></span>
          {/if}
          <i class="bi bi-trash me-1"></i>Azzera
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- ── MODALE POSTI FISSI ──────────────────────────────────────── -->
{#if pfOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-backdrop-custom" onclick={() => { pfOpen = false; }}></div>
  <div class="pf-modal">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h6 class="mb-0"><i class="bi bi-pin-angle me-1"></i>Posti Fissi</h6>
      <button class="btn-close btn-close-sm" onclick={() => { pfOpen = false; }}></button>
    </div>

    {#if pfLoading}
      <div class="text-center py-3"><div class="spinner-border spinner-border-sm text-primary"></div></div>
    {:else}
      <!-- Lista posti fissi esistenti -->
      {#if pfData.length > 0 && pfEditId === null}
        <div class="table-responsive mb-2" style="max-height:250px; overflow-y:auto">
          <table class="table table-sm table-hover mb-0" style="font-size:.78rem">
            <thead class="table-light">
              <tr>
                <th style="width:36px" class="text-center"><input type="checkbox"
                  checked={pfData.length > 0 && pfData.every(p => p.is_active)}
                  onchange={() => { const val = !pfData.every(p => p.is_active); pfData.forEach(p => { if (!!p.is_active !== val) pfToggleActive(p); }); }}
                  title="Seleziona/deseleziona tutti"></th>
                <th>Nome</th>
                <th>Turno</th>
                <th>Giorno</th>
                <th>Utenti</th>
                <th style="width:130px" class="text-end">Azioni</th>
              </tr>
            </thead>
            <tbody>
              {#each pfData as pf}
                <tr class:table-secondary={!pf.is_active}>
                  <td class="text-center">
                    <input type="checkbox" checked={!!pf.is_active}
                           onchange={() => pfToggleActive(pf)}>
                  </td>
                  <td>{pf.nome || '—'}</td>
                  <td><span class="badge bg-secondary">{pf.turno_sigla ?? pf.preset_turno_id}</span></td>
                  <td>{giorniSettimana[pf.giorno_settimana] ?? pf.giorno_settimana}</td>
                  <td>
                    {#each pf.utenti as u}
                      <span class="badge bg-light text-dark border me-1">{u.sigla}</span>
                    {/each}
                  </td>
                  <td class="text-end text-nowrap">
                    <button class="btn btn-sm btn-outline-success py-0 px-1" title="Applica questo"
                            onclick={() => pfApplica([pf.id])} disabled={pfLoading}>
                      <i class="bi bi-play-fill"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-primary py-0 px-1" title="Modifica"
                            onclick={() => pfModifica(pf)}>
                      <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger py-0 px-1" title="Elimina"
                            onclick={() => { if (confirm('Eliminare questo posto fisso?')) pfElimina(pf.id); }}>
                      <i class="bi bi-trash"></i>
                    </button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else if pfEditId === null}
        <p class="text-muted small mb-2">Nessun posto fisso configurato.</p>
      {/if}

      <!-- Form nuovo/modifica -->
      {#if pfEditId !== null}
        <div class="border rounded p-2 mb-2" style="font-size:.8rem">
          <h6 class="mb-2" style="font-size:.82rem">
            {pfEditId === 'new' ? 'Nuovo posto fisso' : 'Modifica posto fisso'}
          </h6>
          <div class="row g-2 mb-2">
            <div class="col-sm-4">
              <label class="form-label mb-0">Nome</label>
              <input type="text" class="form-control form-control-sm"
                     bind:value={pfForm.nome} placeholder="es. RM giovedì">
            </div>
            <div class="col-sm-4">
              <label class="form-label mb-0">Turno</label>
              <select class="form-select form-select-sm" bind:value={pfForm.preset_turno_id}>
                <option value={null}>— scegli —</option>
                {#each _pfTurniList() as t}
                  <option value={t.id}>{t.sigla} ({t.sg} › {t.g})</option>
                {/each}
              </select>
            </div>
            <div class="col-sm-4">
              <label class="form-label mb-0">Giorno</label>
              <select class="form-select form-select-sm" bind:value={pfForm.giorno_settimana}>
                {#each giorniSettimana as gs, i}
                  <option value={i}>{gs}</option>
                {/each}
              </select>
            </div>
          </div>
          <label class="form-label mb-1">Utenti (rotazione equa)</label>
          <div class="pf-utenti-grid mb-2">
            {#each utenti as u}
              <label class="pf-utente-chip" class:pf-utente-sel={pfForm.utenti.includes(u.id)}>
                <input type="checkbox" class="d-none"
                       checked={pfForm.utenti.includes(u.id)}
                       onchange={() => _pfToggleUtente(u.id)}>
                {u.sigla}
              </label>
            {/each}
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-sm btn-primary" onclick={pfSalva}>
              <i class="bi bi-check-lg me-1"></i>Salva
            </button>
            <button class="btn btn-sm btn-secondary" onclick={() => { pfEditId = null; }}>Annulla</button>
          </div>
        </div>
      {/if}

      <!-- Azioni in basso -->
      <div class="d-flex justify-content-between align-items-center mt-2 pt-2 border-top">
        <div class="d-flex align-items-center gap-2">
          {#if pfEditId === null}
            <button class="btn btn-sm btn-outline-primary" onclick={pfNuovo}>
              <i class="bi bi-plus-lg me-1"></i>Nuovo
            </button>
          {/if}
        </div>
        <div class="d-flex flex-wrap align-items-center gap-2">
          <div class="form-check form-check-inline mb-0" style="font-size:.78rem">
            <input type="checkbox" class="form-check-input" id="pf-ignfest"
                   bind:checked={pfOpts.ignora_festivi}>
            <label class="form-check-label" for="pf-ignfest">Ignora festivi</label>
          </div>
          <div class="form-check form-check-inline mb-0" style="font-size:.78rem">
            <input type="checkbox" class="form-check-input" id="pf-ignsfest"
                   bind:checked={pfOpts.ignora_superfestivi}>
            <label class="form-check-label" for="pf-ignsfest">Ignora superfestivi</label>
          </div>
          <div class="form-check form-check-inline mb-0" style="font-size:.78rem">
            <input type="checkbox" class="form-check-input" id="pf-rispdes"
                   bind:checked={pfOpts.rispetta_desiderata}>
            <label class="form-check-label" for="pf-rispdes">Rispetta desiderata</label>
          </div>
          <div class="form-check form-check-inline mb-0" style="font-size:.78rem">
            <input type="checkbox" class="form-check-input" id="pf-sovrascrivi"
                   bind:checked={pfOpts.sovrascrivi}>
            <label class="form-check-label" for="pf-sovrascrivi">Sovrascrivi esistenti</label>
          </div>
          <button class="btn btn-sm btn-success" onclick={() => pfApplica()}
                  disabled={pfLoading || pfData.filter(p => p.is_active).length === 0}>
            <i class="bi bi-play-fill me-1"></i>Applica selezionati ({pfData.filter(p => p.is_active).length})
          </button>
        </div>
      </div>

      <!-- Risultato applicazione -->
      {#if pfResult}
        <div class="alert alert-info mt-2 mb-0 py-1 px-2" style="font-size:.78rem">
          <strong>Risultato:</strong> {pfResult.inseriti} inseriti, {pfResult.saltati} saltati
          {#if pfResult.dettagli?.length}
            <ul class="mb-0 mt-1">
              {#each pfResult.dettagli as d}
                <li>{d}</li>
              {/each}
            </ul>
          {/if}
        </div>
      {/if}
    {/if}
  </div>
{/if}

<!-- ── CONTENUTO ──────────────────────────────────────────────── -->
{#if loading}
  <div class="text-center py-5"><div class="spinner-border text-primary"></div></div>
{:else if !struttura}
  <div class="alert alert-info m-3">Nessun calendario disponibile.</div>

<!-- ── GRIGLIA TURNI ──────────────────────────────────────────── -->
{:else if vista === 'griglia'}
  {@const congelatiGriglia = !!struttura.calendario?.desiderata_congelati}
  {#if !congelatiGriglia}
    <div class="alert alert-warning m-2 py-2 small d-flex align-items-start gap-2">
      <i class="bi bi-exclamation-triangle-fill mt-1"></i>
      <div>
        <strong>Attenzione:</strong> i desiderata di
        <strong>{NOMI_MESI[struttura.calendario.mese]} {struttura.calendario.anno}</strong>
        sono ancora aperti e potrebbero cambiare in tempo reale se qualcuno li modifica.
        Non sarà possibile fare modifiche nella copia di lavoro dei desiderata (Working Desiderata).
        Prima di procedere all'inserimento turni è opportuno chiudere i desiderata.
      </div>
    </div>
  {/if}
  <div class="px-2 py-1 small text-muted d-flex gap-3" style="font-size:.8rem">
    <span><strong>Turni lavorativi:</strong> {turniDovuti}</span>
    <span><strong>Ore lavorative:</strong> {fmtOre(oreDovute)}</span>
  </div>
  <div class="overflow-auto" style="max-height: calc(100vh - 58px); {gridCssVars}">
  {#if !trasposto}
    <!-- ── GRIGLIA NORMALE: turni per riga, giorni per colonna ── -->
    <table class="table table-bordered table-sm mb-0 align-middle"
           style="min-width:max-content; border-collapse:separate; border-spacing:0; --col-turno-w:{colTurnoWidth}px; --cell-w:{cellWidth}px">

      <thead style="position:sticky;top:0;z-index:25;background:var(--gc-prima-riga-bg,#f8f9fa)">
        <tr>
          <th class="col-turno">Turno
            <div class="resize-handle" onmousedown={onResizeStart}></div>
          </th>
          {#if hasNotti}
            <th class="col-g col-notte-prec" title="Ultimo giorno mese precedente (turni notturni)">
              <div class="fw-bold" style="font-size:.65rem">Prec</div>
            </th>
          {/if}
          {#each Array(numGiorni) as _, i}
            {@const g = i + 1}
            <th class="col-g {thClass(g)}">
              <div class="fw-bold">{g}</div>
              <div style="font-size:.6rem;color:#666">{nomeGiorno(g)}</div>
            </th>
          {/each}
        </tr>
      </thead>

        {#each struttura.sovragruppi as sg, sgIdx}
          {@const sgStyle = effectiveSgStyle(sg)}
          {@const sgRepeat = sgStyle['--repeatName'] ?? false}
        <tbody>
          <tr>
            <td colspan={numGiorni + 1 + (hasNotti ? 1 : 0)} class="py-1 ps-2 sep-sg"
                style="position:sticky;left:0;z-index:5;font-size:.78rem;{toStyleStr(sgStyle)}"
                oncontextmenu={e => onSgContextMenu(e, sg)}>
              {#if sgRepeat}
                <div class="sep-repeat">
                  <span><i class="bi bi-collection me-1"></i>{sg.nome}</span>
                  <span>{sg.nome}</span>
                  <span>{sg.nome}</span>
                </div>
              {:else}
                <i class="bi bi-collection me-1"></i>{sg.nome}
              {/if}
            </td>
          </tr>

          {#each sg.gruppi as gruppo, gIdx}
            {@const gStyle = effectiveStyle(gruppo)}
            {@const repeatName = gStyle['--repeatName'] ?? false}
            <tr>
              <td colspan={numGiorni + 1 + (hasNotti ? 1 : 0)} class="py-0 ps-3 sep-gruppo"
                  style="position:sticky;left:0;z-index:5;font-size:.7rem;{borderVars(gruppo, sg)};{toStyleStr(gStyle)}"
                  oncontextmenu={e => onGruppoContextMenu(e, gruppo)}>
                {#if repeatName}
                  <div class="sep-repeat">
                    <span>{gruppo.nome}</span>
                    <span>{gruppo.nome}</span>
                    <span>{gruppo.nome}</span>
                  </div>
                {:else}
                  {gruppo.nome}
                {/if}
              </td>
            </tr>

            {#each gruppo.turni.filter(t => !t.is_hidden) as turno, tIdx}
              {@const visibleTurni = gruppo.turni.filter(t => !t.is_hidden)}
              {@const isFirstTurno = tIdx === 0}
              {@const isLastTurno = tIdx === visibleTurni.length - 1}
              {@const isFirstInSg = isFirstTurno && gIdx === 0}
              {@const isDisabled = !!turno.is_disabled}
              <tr style="{borderVars(gruppo, sg)}"
                  class="turno-row sg-row {isFirstTurno ? 'first-in-gruppo' : ''} {isLastTurno ? 'last-in-gruppo' : ''} {isFirstInSg ? 'first-in-sg' : ''}"
              >
                <td class="col-turno ps-4 fw-semibold {isDisabled ? 'gc-turno-disabled' : ''}"
                    style="{toStyleStr(effectiveColStyle(gruppo))}"
                    oncontextmenu={e => onGruppoContextMenu(e, gruppo)}>
                  {turno.descrizione || turno.sigla}
                  {#if isDisabled}<i class="bi bi-slash-circle text-muted ms-1" style="font-size:.65rem" title="Turno disattivato"></i>{/if}
                </td>

                {#if hasNotti}
                  {@const np = nottePrec(turno)}
                  {#if np === null}
                    <td class="cella cella-notte-prec cella-notte-prec-empty"></td>
                  {:else if np === undefined}
                    <td class="cella cella-notte-prec cella-notte-prec-missing" title="Nessun calendario precedente">{''}</td>
                  {:else}
                    <td class="cella cella-notte-prec" title="Notte ultimo giorno mese precedente">{np}</td>
                  {/if}
                {/if}

                {#each Array(numGiorni) as _, i}
                  {@const g   = i + 1}
                  {@const key = `${turno.id}-${g}`}
                  {@const chiusa = isCellaChiusa(turno.id, g)}
                  {@const noAccesso = isTurnoInaccessibile(turno.id) || isDisabled}
                  {@const locked = isCellaBloccata(turno.id, g)}
                  {@const bloccata = chiusa || noAccesso || locked}
                  {@const conflittoStyle = bloccata ? '' : cellConflittoStyle(key)}
                  {@const curVal = selectVal(key)}
                  {@const isFocused = focusedCell?.turnoId === turno.id && focusedCell?.giorno === g}
                  <td class="cella {cellClass(key, g)} {chiusa ? 'gc-chiusa' : ''} {noAccesso ? 'gc-no-accesso' : ''} {locked ? 'gc-locked' : ''} {isReadOnly ? 'gc-readonly' : ''} {isEffettivoMod(key) ? 'gc-effettivo-mod' : ''} {dragSource?.key === key ? 'cell-dragging-source' : ''} {dragSource && dragTarget?.key === key ? 'cell-drag-over' : ''} {selectedCells.has(key) ? 'gc-selected' : ''} {isFocused ? 'gc-focused' : ''}"
                      style="position:relative;{conflittoStyle}"
                      oncontextmenu={e => isReadOnly ? null : onCellContextMenu(e, turno.id, g, turno.sigla)}
                      onpointerdown={e => isReadOnly ? null : onCellPointerDown(e, turno.id, g, bloccata)}
                      onpointerup={onCellPointerUp}
                      onpointerenter={() => bloccata ? null : onCellPointerEnter(turno.id, g)}
                      onpointercancel={onCellPointerCancel}>
                    {#if chiusa}
                      <span class="cell-chiusa-marker"></span>
                    {:else if noAccesso}
                      {#if curVal}<span class="cell-noacc-sigla">{utenti.find(u => String(u.id) === curVal)?.sigla || ''}</span>{/if}
                    {:else if locked}
                      <span class="cell-locked-marker"><i class="bi bi-lock-fill"></i></span>
                      {#if curVal}<span class="cell-locked-sigla">{utenti.find(u => String(u.id) === curVal)?.sigla || ''}</span>{/if}
                    {:else}
                    <CellEditor
                      options={gridCellOptions(g, curVal)}
                      value={curVal}
                      style={conflittoStyle}
                      focused={isFocused}
                      readonly={isReadOnly}
                      onchange={v => onCellChange(turno.id, g, v)}
                      onfocusrequest={() => { focusedCell = { turnoId: turno.id, giorno: g }; selAnchor = { turnoId: turno.id, giorno: g }; focusedWdCell = null; }}
                      onkeynavigation={moveGridFocus}
                      onshiftnavigation={extendGridSelection}
                      onconfirm={() => onCellConfirm(turno.id, g)}
                    />

                    {#if syncStatus[key]}
                      <span class="sync-dot {syncStatus[key]}"></span>
                    {/if}
                    {/if}

                  </td>
                {/each}
              </tr>
            {/each}
          {/each}
          <tr>
            <td colspan={numGiorni + 1 + (hasNotti ? 1 : 0)} class="sep-sg-close"
                style="background:{sgBorderColor(sg)};height:{sgBorderWidth(sg)}"></td>
          </tr>
        </tbody>
        {/each}
    </table>

  {:else}
    <!-- ── GRIGLIA TRASPOSTA: giorni per riga, turni per colonna ── -->
    {@const flatTurni = struttura.sovragruppi.flatMap(sg =>
      sg.gruppi.flatMap((gruppo, gIdx) => {
        const visible = gruppo.turni.filter(t => !t.is_hidden);
        return visible.map((turno, tIdx) => ({
          sg, gruppo, turno,
          firstInGruppo: tIdx === 0,
          lastInGruppo: tIdx === visible.length - 1,
          firstInSg: tIdx === 0 && gIdx === 0,
          lastInSg: tIdx === visible.length - 1 && gIdx === sg.gruppi.length - 1,
        }));
      })
    )}
    {@const sgSpans = struttura.sovragruppi.map(sg => ({
      sg, span: sg.gruppi.reduce((sum, g) => sum + g.turni.filter(t => !t.is_hidden).length, 0)
    })).filter(x => x.span > 0)}
    {@const gruppoSpans = struttura.sovragruppi.flatMap(sg => {
      const filtered = sg.gruppi.filter(g => g.turni.some(t => !t.is_hidden));
      return filtered.map((g, i) => ({
        gruppo: g, sg, span: g.turni.filter(t => !t.is_hidden).length,
        firstInSg: i === 0,
        lastInSg: i === filtered.length - 1,
      }));
    })}

    <table class="table table-bordered table-sm mb-0 align-middle t-grid"
           style="min-width:max-content; border-collapse:separate; border-spacing:0; --cell-w:{cellWidth}px">

      <thead style="position:sticky;top:0;z-index:25;background:var(--gc-prima-riga-bg,#f8f9fa)">
        <!-- Riga 1: Sovragruppi -->
        <tr>
          <th class="t-col-giorno" rowspan="3">Giorno</th>
          {#each sgSpans as { sg, span }}
            <th colspan={span} class="t-th-sg sep-sg"
                style="{sgBorderVars(sg)};{toStyleStr(effectiveSgStyle(sg))}"
                oncontextmenu={e => onSgContextMenu(e, sg)}>
              {sg.nome}
            </th>
          {/each}
        </tr>
        <!-- Riga 2: Gruppi -->
        <tr>
          {#each gruppoSpans as { gruppo, sg, span, firstInSg, lastInSg }}
            <th colspan={span} class="t-th-gruppo sep-gruppo {firstInSg ? 'first-col-sg' : ''} {lastInSg ? 'last-col-sg' : ''}"
                style="{borderVars(gruppo, sg)};{toStyleStr(effectiveStyle(gruppo))}"
                oncontextmenu={e => onGruppoContextMenu(e, gruppo)}>
              {gruppo.nome}
            </th>
          {/each}
        </tr>
        <!-- Riga 3: Turni -->
        <tr>
          {#each flatTurni as { sg, gruppo, turno, firstInGruppo, lastInGruppo, firstInSg, lastInSg }}
            <th class="t-th-turno {firstInGruppo ? 'first-col-gruppo' : ''} {lastInGruppo ? 'last-col-gruppo' : ''} {firstInSg ? 'first-col-sg' : ''} {lastInSg ? 'last-col-sg' : ''} {turno.is_disabled ? 'gc-turno-disabled' : ''}"
                style="{toStyleStr(effectiveColStyle(gruppo))};{borderVars(gruppo, sg)}"
                oncontextmenu={e => onGruppoContextMenu(e, gruppo)}
                title={turno.descrizione || turno.sigla}>
              {turno.descrizione || turno.sigla}
            </th>
          {/each}
        </tr>
      </thead>

      <tbody>
        {#if hasNotti}
          <tr class="notte-prec-row">
            <td class="t-col-giorno fw-semibold" style="font-size:.65rem;color:#666" title="Ultimo giorno mese precedente (turni notturni)">Prec</td>
            {#each flatTurni as { sg, gruppo, turno, firstInGruppo, lastInGruppo, firstInSg, lastInSg }}
              {@const np = nottePrec(turno)}
              {#if np === null}
                <td class="cella cella-notte-prec cella-notte-prec-empty {firstInGruppo ? 'first-col-gruppo' : ''} {lastInGruppo ? 'last-col-gruppo' : ''} {firstInSg ? 'first-col-sg' : ''} {lastInSg ? 'last-col-sg' : ''}"
                    style="{borderVars(gruppo, sg)}"></td>
              {:else if np === undefined}
                <td class="cella cella-notte-prec cella-notte-prec-missing {firstInGruppo ? 'first-col-gruppo' : ''} {lastInGruppo ? 'last-col-gruppo' : ''} {firstInSg ? 'first-col-sg' : ''} {lastInSg ? 'last-col-sg' : ''}"
                    style="{borderVars(gruppo, sg)}" title="Nessun calendario precedente"></td>
              {:else}
                <td class="cella cella-notte-prec {firstInGruppo ? 'first-col-gruppo' : ''} {lastInGruppo ? 'last-col-gruppo' : ''} {firstInSg ? 'first-col-sg' : ''} {lastInSg ? 'last-col-sg' : ''}"
                    style="{borderVars(gruppo, sg)}" title="Notte ultimo giorno mese precedente">{np}</td>
              {/if}
            {/each}
          </tr>
        {/if}
        {#each Array(numGiorni) as _, i}
          {@const g = i + 1}
          <tr class="{i === 0 ? 'first-day-row' : ''} {i === numGiorni - 1 ? 'last-day-row' : ''}"
          >
            <td class="t-col-giorno fw-semibold {cellClass('', g)}">
              <span class="fw-bold">{g}</span>
              <span class="t-day-name">{nomeGiorno(g)}</span>
            </td>
            {#each flatTurni as { sg, gruppo, turno, firstInGruppo, lastInGruppo, firstInSg, lastInSg }}
              {@const key = `${turno.id}-${g}`}
              {@const chiusa = isCellaChiusa(turno.id, g)}
              {@const noAccesso = isTurnoInaccessibile(turno.id) || !!turno.is_disabled}
              {@const locked = isCellaBloccata(turno.id, g)}
              {@const bloccata = chiusa || noAccesso || locked}
              {@const conflittoStyle = bloccata ? '' : cellConflittoStyle(key)}
              {@const curVal = selectVal(key)}
              {@const isFocused = focusedCell?.turnoId === turno.id && focusedCell?.giorno === g}
              <td class="cella {cellClass(key, g)} {chiusa ? 'gc-chiusa' : ''} {noAccesso ? 'gc-no-accesso' : ''} {locked ? 'gc-locked' : ''} {isReadOnly ? 'gc-readonly' : ''} {isEffettivoMod(key) ? 'gc-effettivo-mod' : ''} {firstInGruppo ? 'first-col-gruppo' : ''} {lastInGruppo ? 'last-col-gruppo' : ''} {firstInSg ? 'first-col-sg' : ''} {lastInSg ? 'last-col-sg' : ''} {dragSource?.key === key ? 'cell-dragging-source' : ''} {dragSource && dragTarget?.key === key ? 'cell-drag-over' : ''} {selectedCells.has(key) ? 'gc-selected' : ''} {isFocused ? 'gc-focused' : ''}"
                  style="position:relative;{borderVars(gruppo, sg)};{conflittoStyle}"
                  oncontextmenu={e => isReadOnly ? null : onCellContextMenu(e, turno.id, g, turno.sigla)}
                  onpointerdown={e => isReadOnly ? null : onCellPointerDown(e, turno.id, g, bloccata)}
                  onpointerup={onCellPointerUp}
                  onpointerenter={() => bloccata ? null : onCellPointerEnter(turno.id, g)}
                  onpointercancel={onCellPointerCancel}>
                {#if chiusa}
                  <span class="cell-chiusa-marker"></span>
                {:else if noAccesso}
                  {#if curVal}<span class="cell-noacc-sigla">{utenti.find(u => String(u.id) === curVal)?.sigla || ''}</span>{/if}
                {:else if locked}
                  <span class="cell-locked-marker"><i class="bi bi-lock-fill"></i></span>
                  {#if curVal}<span class="cell-locked-sigla">{utenti.find(u => String(u.id) === curVal)?.sigla || ''}</span>{/if}
                {:else}
                <CellEditor
                  options={gridCellOptions(g, curVal)}
                  value={curVal}
                  style={conflittoStyle}
                  focused={isFocused}
                  readonly={isReadOnly}
                  onchange={v => onCellChange(turno.id, g, v)}
                  onfocusrequest={() => { focusedCell = { turnoId: turno.id, giorno: g }; selAnchor = { turnoId: turno.id, giorno: g }; focusedWdCell = null; }}
                  onkeynavigation={moveGridFocus}
                  onshiftnavigation={extendGridSelection}
                  onconfirm={() => onCellConfirm(turno.id, g)}
                />

                {#if syncStatus[key]}
                  <span class="sync-dot {syncStatus[key]}"></span>
                {/if}
                {/if}
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
  </div>

<!-- ── WORKING DESIDERATA ─────────────────────────────────────── -->
{:else if vista === 'working'}
  {@const congelati = !!struttura.calendario?.desiderata_congelati}
  <div style={gridCssVars}>
    {#if !congelati}
      <div class="alert alert-info m-2 py-2 small">
        <i class="bi bi-info-circle me-1"></i>
        Desiderata non ancora congelati — visualizzazione in sola lettura dei desiderata originali.
        Dopo il congelamento sarà possibile modificarli.
      </div>
    {/if}
    <div class="d-flex align-items-center gap-2 px-2 py-1 border-bottom bg-light">
      {#if congelati}
        <button class="btn btn-sm btn-outline-secondary"
                disabled={isReadOnly || !wdHistory.can_undo} onclick={doWdUndo}
                title="Annulla (Ctrl+Z)">
          <i class="bi bi-arrow-counterclockwise"></i> Annulla
        </button>
        <button class="btn btn-sm btn-outline-secondary"
                disabled={isReadOnly || !wdHistory.can_redo} onclick={doWdRedo}
                title="Ripristina (Ctrl+Y)">
          <i class="bi bi-arrow-clockwise"></i> Ripristina
        </button>
        {#if selectedWdCells.size > 0}
          <button class="btn btn-sm btn-outline-danger" onclick={bulkClearWd}>
            <i class="bi bi-trash"></i> Svuota {selectedWdCells.size} celle
          </button>
        {/if}
      {/if}
      <button class="btn btn-sm btn-outline-secondary" onclick={toggleDesTrasposto}
              title="Inverti righe e colonne">
        <i class="bi bi-arrow-left-right me-1"></i>{desTrasposto ? 'Giorni su righe' : 'Giorni su colonne'}
      </button>
      <label class="small mb-0 text-muted ms-2">Ordine</label>
      <select class="form-select form-select-sm w-auto"
              value={modalitaDesOrd}
              onchange={e => cambiaModalitaDesOrd(e.target.value)}>
        <option value="manuale">Manuale</option>
        <option value="alfabetico_globale">Alfabetico globale</option>
        <option value="alfabetico_intragruppo">Alfabetico intragruppo</option>
      </select>
      {#if modalitaDesOrd === 'manuale'}
        <button class="btn btn-sm {riordinoDesOn ? 'btn-warning' : 'btn-outline-warning'}"
                onclick={() => riordinoDesOn = !riordinoDesOn}
                title="Attiva/disattiva modalità riordino">
          <i class="bi bi-arrows-move"></i>
        </button>
      {/if}
      <div class="ms-auto"></div>
      {#if congelati}
        <button class="btn btn-sm btn-outline-warning" onclick={ricaricaDesiderataOriginali}
                title="Ricarica i desiderata originali (azzera modifiche WD)">
          <i class="bi bi-arrow-repeat"></i> Ricarica desiderata originali
        </button>
      {/if}
    </div>
    {#if !desTrasposto}
      <!-- Default: utenti-righe × giorni-colonne -->
      <div class="table-responsive des-wrap">
      <table class="table table-bordered table-sm align-middle small desiderata-grid mb-0"
             style="min-width:max-content">
        <thead>
          <tr>
            <th class="des-cell-label" style="min-width:60px">Sigla</th>
            {#each Array(numGiorni) as _, i}
              {@const g = i + 1}
              <th class="des-g {thClass(g)}">
                <div class="fw-bold">{g}</div>
                <div class="des-dow">{nomeGiorno(g)}</div>
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each desUserGroups as ug (ug.key)}
            {@const sgCss = desSgBlockStyle(ug.sovragruppo_id)}
            {@const sgRepeat = desSgRepeat(ug.sovragruppo_id)}
            {@const canReorder = modalitaDesOrd === 'manuale' && riordinoDesOn}
            {#if sgRepeat}
              <tr class="des-sg-row">
                <td class="des-cell-label des-sg-repeat" style={sgCss} colspan={numGiorni + 1}>
                  <div class="sep-repeat">
                    <span>
                      {ug.sg_sigla ?? '—'}
                      {#if canReorder && ug.sovragruppo_id != null}
                        <button class="btn btn-link btn-sm p-0 ms-1" title="Sposta SG su"
                                onclick={() => spostaSovragruppoDesOrd(ug.sovragruppo_id, -1)}>
                          <i class="bi bi-chevron-up"></i>
                        </button>
                        <button class="btn btn-link btn-sm p-0" title="Sposta SG giù"
                                onclick={() => spostaSovragruppoDesOrd(ug.sovragruppo_id, 1)}>
                          <i class="bi bi-chevron-down"></i>
                        </button>
                      {/if}
                    </span>
                    <span>{ug.sg_nome ?? ''}</span>
                    <span>{ug.sg_nome ?? ''}</span>
                  </div>
                </td>
              </tr>
            {:else}
              <tr class="des-sg-row">
                <td class="des-cell-label sg-label-cell" style={sgCss} title={ug.sg_nome ?? ''}>
                  {#if ug.sg_sigla}<span class="sg-label">{ug.sg_sigla}</span>{:else}<span class="text-muted">—</span>{/if}
                  {#if canReorder && ug.sovragruppo_id != null}
                    <span class="ms-1">
                      <button class="btn btn-link btn-sm p-0 me-1" title="Sposta SG su"
                              onclick={() => spostaSovragruppoDesOrd(ug.sovragruppo_id, -1)}>
                        <i class="bi bi-chevron-up"></i>
                      </button>
                      <button class="btn btn-link btn-sm p-0" title="Sposta SG giù"
                              onclick={() => spostaSovragruppoDesOrd(ug.sovragruppo_id, 1)}>
                        <i class="bi bi-chevron-down"></i>
                      </button>
                    </span>
                  {/if}
                </td>
                <td class="des-sg-spacer" style={sgCss} colspan={numGiorni}></td>
              </tr>
            {/if}
            {#each ug.users as u (u.id)}
              {@const uAccessibile = isUtenteAccessibile(u.id)}
              {@const isMe = u.id === $userStore?.id}
              <tr class="des-user-row {isMe ? 'user-me' : ''}">
                <td class="des-cell-label user-sigla {uAccessibile ? '' : 'des-no-accesso'} {isMe ? 'user-me' : ''}">
                  <span>{u.sigla}</span>
                  {#if canReorder}
                    <span class="ms-1">
                      <button class="btn btn-link btn-sm p-0 me-1" title="Sposta su"
                              onclick={() => spostaUtenteDesOrd(u.id, -1)}>
                        <i class="bi bi-chevron-up"></i>
                      </button>
                      <button class="btn btn-link btn-sm p-0" title="Sposta giù"
                              onclick={() => spostaUtenteDesOrd(u.id, 1)}>
                        <i class="bi bi-chevron-down"></i>
                      </button>
                    </span>
                  {/if}
                </td>
                {#each Array(numGiorni) as _, i}
                  {@const g     = i + 1}
                  {@const entry = congelati ? wdMap[u.id]?.[g] : desMap[u.id]?.[g]}
                  {@const wdKey = `${u.id}-${g}`}
                  {#if congelati && uAccessibile}
                    {@const wdVal = String(entry?.tipo_richiesta_id ?? '')}
                    {@const wdFocused = focusedWdCell?.userId === u.id && focusedWdCell?.giorno === g}
                    <td class="des-cell {thClass(g)} {isMe ? 'cell-me' : ''} {selectedWdCells.has(wdKey) ? 'wd-selected' : ''} {wdFocused ? 'gc-focused' : ''}"
                        onpointerdown={e => onWdCellPointerDown(e, u.id, g)}>
                      <CellEditor
                        options={wdCellOptions}
                        value={wdVal}
                        focused={wdFocused}
                        onchange={v => salvaWorkingDes(u.id, g, v ? +v : null)}
                        onfocusrequest={() => { focusedWdCell = { userId: u.id, giorno: g }; wdSelAnchor = { userId: u.id, giorno: g }; focusedCell = null; }}
                        onkeynavigation={moveWdFocus}
                        onshiftnavigation={extendWdSelection}
                        onconfirm={() => onWdCellConfirm(u.id, g)}
                      />
                    </td>
                  {:else}
                    <td class="des-cell {thClass(g)} {isMe ? 'cell-me' : ''} {uAccessibile ? '' : 'des-no-accesso'} {!congelati && uAccessibile ? 'des-wd-frozen-off' : ''} {entry?.req_tipo === 'lavorativo' ? 'des-working' : entry?.req_tipo === 'assenza' ? 'des-notworking' : ''}">
                      {#if entry}<span title={entry.note ?? ''}>{entry.req_sigla}</span>{/if}
                    </td>
                  {/if}
                {/each}
              </tr>
            {/each}
          {/each}
        </tbody>
      </table>
      </div>
    {:else}
      <!-- Trasposto: giorni-righe × utenti-colonne -->
      <div class="table-responsive des-wrap">
      <table class="table table-bordered table-sm align-middle small desiderata-grid mb-0"
             style="min-width:max-content">
        <thead>
          <!-- Riga SG con colspan -->
          <tr>
            <th class="des-cell-label"></th>
            <th class="des-cell-label"></th>
            {#each desUserGroups as ug (ug.key)}
              <th colspan={ug.count} class="sg-header"
                  style={desSgBlockStyle(ug.sovragruppo_id)}
                  title={ug.sg_nome ?? ''}>
                {#if ug.sg_sigla}<span class="sg-label">{ug.sg_sigla}</span>{:else}—{/if}
              </th>
            {/each}
          </tr>
          <!-- Riga sigle utenti -->
          <tr>
            <th class="des-cell-label" style="min-width:60px">Gg</th>
            <th class="des-cell-label"></th>
            {#each utentiBasic as u (u.id)}
              {@const uAccessibile = isUtenteAccessibile(u.id)}
              {@const isMe = u.id === $userStore?.id}
              <th class="des-g user-sigla {uAccessibile ? '' : 'des-no-accesso'} {isMe ? 'user-me' : ''}">{u.sigla}</th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each Array(numGiorni) as _, i}
            {@const g = i + 1}
            {@const tc = thClass(g)}
            <tr class={tc}>
              <td class="des-cell-label fw-bold {tc}">{g}</td>
              <td class="des-cell-label {tc}">{nomeGiorno(g)}</td>
              {#each utentiBasic as u (u.id)}
                {@const uAccessibile = isUtenteAccessibile(u.id)}
                {@const isMe = u.id === $userStore?.id}
                {@const entry = congelati ? wdMap[u.id]?.[g] : desMap[u.id]?.[g]}
                {@const wdKey = `${u.id}-${g}`}
                {#if congelati && uAccessibile}
                  {@const wdVal = String(entry?.tipo_richiesta_id ?? '')}
                  {@const wdFocused = focusedWdCell?.userId === u.id && focusedWdCell?.giorno === g}
                  <td class="des-cell {tc} {isMe ? 'cell-me' : ''} {selectedWdCells.has(wdKey) ? 'wd-selected' : ''} {wdFocused ? 'gc-focused' : ''}"
                      onpointerdown={e => onWdCellPointerDown(e, u.id, g)}>
                    <CellEditor
                      options={wdCellOptions}
                      value={wdVal}
                      focused={wdFocused}
                      onchange={v => salvaWorkingDes(u.id, g, v ? +v : null)}
                      onfocusrequest={() => { focusedWdCell = { userId: u.id, giorno: g }; wdSelAnchor = { userId: u.id, giorno: g }; focusedCell = null; }}
                      onkeynavigation={moveWdFocus}
                      onshiftnavigation={extendWdSelection}
                      onconfirm={() => onWdCellConfirm(u.id, g)}
                    />
                  </td>
                {:else}
                  <td class="des-cell {tc} {isMe ? 'cell-me' : ''} {uAccessibile ? '' : 'des-no-accesso'} {!congelati && uAccessibile ? 'des-wd-frozen-off' : ''} {entry?.req_tipo === 'lavorativo' ? 'des-working' : entry?.req_tipo === 'assenza' ? 'des-notworking' : ''}">
                    {#if entry}<span title={entry.note ?? ''}>{entry.req_sigla}</span>{/if}
                  </td>
                {/if}
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
      </div>
    {/if}
  </div>

<!-- ── DESIDERATA ORIGINALI ───────────────────────────────────── -->
{:else if vista === 'originali'}
  <div style={gridCssVars}>
    <div class="d-flex align-items-center gap-2 px-2 py-1 border-bottom bg-light">
      <button class="btn btn-sm btn-outline-secondary" onclick={toggleDesTrasposto}
              title="Inverti righe e colonne">
        <i class="bi bi-arrow-left-right me-1"></i>{desTrasposto ? 'Giorni su righe' : 'Giorni su colonne'}
      </button>
      <label class="small mb-0 text-muted ms-2">Ordine</label>
      <select class="form-select form-select-sm w-auto"
              value={modalitaDesOrd}
              onchange={e => cambiaModalitaDesOrd(e.target.value)}>
        <option value="manuale">Manuale</option>
        <option value="alfabetico_globale">Alfabetico globale</option>
        <option value="alfabetico_intragruppo">Alfabetico intragruppo</option>
      </select>
      {#if modalitaDesOrd === 'manuale'}
        <button class="btn btn-sm {riordinoDesOn ? 'btn-warning' : 'btn-outline-warning'}"
                onclick={() => riordinoDesOn = !riordinoDesOn}
                title="Attiva/disattiva modalità riordino">
          <i class="bi bi-arrows-move"></i>
        </button>
      {/if}
    </div>
    {#if !desTrasposto}
      <div class="table-responsive des-wrap">
      <table class="table table-bordered table-sm align-middle small desiderata-grid mb-0"
             style="min-width:max-content">
        <thead>
          <tr>
            <th class="des-cell-label" style="min-width:60px">Sigla</th>
            {#each Array(numGiorni) as _, i}
              {@const g = i + 1}
              <th class="des-g {thClass(g)}">
                <div class="fw-bold">{g}</div>
                <div class="des-dow">{nomeGiorno(g)}</div>
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each desUserGroups as ug (ug.key)}
            {@const sgCss = desSgBlockStyle(ug.sovragruppo_id)}
            {@const sgRepeat = desSgRepeat(ug.sovragruppo_id)}
            {@const canReorder = modalitaDesOrd === 'manuale' && riordinoDesOn}
            {#if sgRepeat}
              <tr class="des-sg-row">
                <td class="des-cell-label des-sg-repeat" style={sgCss} colspan={numGiorni + 1}>
                  <div class="sep-repeat">
                    <span>
                      {ug.sg_sigla ?? '—'}
                      {#if canReorder && ug.sovragruppo_id != null}
                        <button class="btn btn-link btn-sm p-0 ms-1" title="Sposta SG su"
                                onclick={() => spostaSovragruppoDesOrd(ug.sovragruppo_id, -1)}>
                          <i class="bi bi-chevron-up"></i>
                        </button>
                        <button class="btn btn-link btn-sm p-0" title="Sposta SG giù"
                                onclick={() => spostaSovragruppoDesOrd(ug.sovragruppo_id, 1)}>
                          <i class="bi bi-chevron-down"></i>
                        </button>
                      {/if}
                    </span>
                    <span>{ug.sg_nome ?? ''}</span>
                    <span>{ug.sg_nome ?? ''}</span>
                  </div>
                </td>
              </tr>
            {:else}
              <tr class="des-sg-row">
                <td class="des-cell-label sg-label-cell" style={sgCss} title={ug.sg_nome ?? ''}>
                  {#if ug.sg_sigla}<span class="sg-label">{ug.sg_sigla}</span>{:else}<span class="text-muted">—</span>{/if}
                  {#if canReorder && ug.sovragruppo_id != null}
                    <span class="ms-1">
                      <button class="btn btn-link btn-sm p-0 me-1" title="Sposta SG su"
                              onclick={() => spostaSovragruppoDesOrd(ug.sovragruppo_id, -1)}>
                        <i class="bi bi-chevron-up"></i>
                      </button>
                      <button class="btn btn-link btn-sm p-0" title="Sposta SG giù"
                              onclick={() => spostaSovragruppoDesOrd(ug.sovragruppo_id, 1)}>
                        <i class="bi bi-chevron-down"></i>
                      </button>
                    </span>
                  {/if}
                </td>
                <td class="des-sg-spacer" style={sgCss} colspan={numGiorni}></td>
              </tr>
            {/if}
            {#each ug.users as u (u.id)}
              {@const isMe = u.id === $userStore?.id}
              <tr class="des-user-row {isMe ? 'user-me' : ''}">
                <td class="des-cell-label user-sigla {isMe ? 'user-me' : ''}">
                  <span>{u.sigla}</span>
                  {#if canReorder}
                    <span class="ms-1">
                      <button class="btn btn-link btn-sm p-0 me-1" title="Sposta su"
                              onclick={() => spostaUtenteDesOrd(u.id, -1)}>
                        <i class="bi bi-chevron-up"></i>
                      </button>
                      <button class="btn btn-link btn-sm p-0" title="Sposta giù"
                              onclick={() => spostaUtenteDesOrd(u.id, 1)}>
                        <i class="bi bi-chevron-down"></i>
                      </button>
                    </span>
                  {/if}
                </td>
                {#each Array(numGiorni) as _, i}
                  {@const g = i + 1}
                  {@const d = desMap[u.id]?.[g]}
                  <td class="des-cell {thClass(g)} {isMe ? 'cell-me' : ''} {d?.req_tipo === 'lavorativo' ? 'des-working' : d?.req_tipo === 'assenza' ? 'des-notworking' : ''}">
                    {#if d}
                      <span title={d.note ?? ''}>{d.req_sigla}</span>
                    {/if}
                  </td>
                {/each}
              </tr>
            {/each}
          {/each}
        </tbody>
      </table>
      </div>
    {:else}
      <!-- Trasposto: giorni-righe × utenti-colonne -->
      <div class="table-responsive des-wrap">
      <table class="table table-bordered table-sm align-middle small desiderata-grid mb-0"
             style="min-width:max-content">
        <thead>
          <!-- Riga SG con colspan -->
          <tr>
            <th class="des-cell-label"></th>
            <th class="des-cell-label"></th>
            {#each desUserGroups as ug (ug.key)}
              <th colspan={ug.count} class="sg-header"
                  style={desSgBlockStyle(ug.sovragruppo_id)}
                  title={ug.sg_nome ?? ''}>
                {#if ug.sg_sigla}<span class="sg-label">{ug.sg_sigla}</span>{:else}—{/if}
              </th>
            {/each}
          </tr>
          <!-- Riga sigle utenti -->
          <tr>
            <th class="des-cell-label" style="min-width:60px">Gg</th>
            <th class="des-cell-label"></th>
            {#each utentiBasic as u (u.id)}
              {@const isMe = u.id === $userStore?.id}
              <th class="des-g user-sigla {isMe ? 'user-me' : ''}">{u.sigla}</th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each Array(numGiorni) as _, i}
            {@const g = i + 1}
            {@const tc = thClass(g)}
            <tr class={tc}>
              <td class="des-cell-label fw-bold {tc}">{g}</td>
              <td class="des-cell-label {tc}">{nomeGiorno(g)}</td>
              {#each utentiBasic as u (u.id)}
                {@const isMe = u.id === $userStore?.id}
                {@const d = desMap[u.id]?.[g]}
                <td class="des-cell {tc} {isMe ? 'cell-me' : ''} {d?.req_tipo === 'lavorativo' ? 'des-working' : d?.req_tipo === 'assenza' ? 'des-notworking' : ''}">
                  {#if d}
                    <span title={d.note ?? ''}>{d.req_sigla}</span>
                  {/if}
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
      </div>
    {/if}
  </div>

<!-- ── INSERISCI DESIDERATA (componente condiviso con /basic) ──── -->
{:else if vista === 'inserisci'}
  <DesiderataInserimento />
{/if}

<!-- ── CONTEXT MENU FORMATTAZIONE ──────────────────────────────── -->
{#if ctxMenu}
  {@const item = ctxMenu.item}
  {@const isSg = ctxMenu.tipo === 'sovragruppo'}
  <StyleContextMenu
    x={ctxMenu.x} y={ctxMenu.y}
    tipo={isSg ? 'sg' : 'gruppo'}
    sepStyle={item.style ?? {}}
    colStyle={isSg
      ? (item.gruppi?.[0]?.style?.['--columnStyle'] ?? {})
      : (item.style?.['--columnStyle'] ?? {})}
    borderColor={item.style?.['--borderColor'] ?? (isSg ? effectiveSgStyle(item).backgroundColor ?? '#d6d8db' : effectiveStyle(item).backgroundColor ?? '#e9ecef')}
    borderWidth={item.style?.['--borderWidth'] ?? (isSg ? 5 : 4)}
    repeatName={item.style?.['--repeatName'] ?? false}
    defaultBg={isSg ? '#d6d8db' : '#e9ecef'}
    defaultFg={isSg ? '#1a1a1a' : '#6c757d'}
    undoCount={styleUndoCount}
    showApplyAll={!isSg}
    onset={onCtxSetProp}
    onborderset={onCtxBorderSet}
    onapply={applicaCtxStyle}
    onclose={closeCtxMenu}
    onundo={undoCalendarStyle}
    onapplyall={() => applicaATutti(item)}
  />
{/if}

<!-- ── CONTEXT MENU ASSEGNAZIONE LAVORATORE ────────────────────── -->
{#if assMenu}
  {@const disp = getDisponibilita(assMenu.giorno)}
  {@const currentKey = `${assMenu.turnoId}-${assMenu.giorno}`}
  {@const currentUserId = localAss[currentKey]?.user_id ?? null}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="ctx-backdrop" style="position:fixed;inset:0;z-index:999"
       onclick={closeAssMenu} oncontextmenu={e => { e.preventDefault(); closeAssMenu(); }}></div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="ass-menu"
       style="left:{Math.min(assMenu.x, window.innerWidth - 380)}px;top:{assMenu.y + 350 > window.innerHeight ? Math.max(0, assMenu.y - 390) : assMenu.y}px">
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="ctx-drag-bar" onmousedown={onAssDragStart}>
      <span style="font-size:.85rem;font-weight:700;color:var(--ctx-fg, #212529);display:flex;align-items:center;gap:4px">
        <i class="bi bi-person-lines-fill me-1"></i>{assMenu.turnoSigla} —
        <button class="ass-nav-btn" disabled={assMenu.giorno <= 1} onclick={() => assMenuChangeDay(-1)}><i class="bi bi-chevron-left"></i></button>
        <span>Giorno {assMenu.giorno}</span>
        <button class="ass-nav-btn" disabled={assMenu.giorno >= numGiorni} onclick={() => assMenuChangeDay(1)}><i class="bi bi-chevron-right"></i></button>
      </span>
      <button class="ctx-close" onclick={closeAssMenu}>&times;</button>
    </div>

    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="ass-empty-row {currentUserId == null ? 'ass-current' : ''}"
         onclick={() => assegnaUtente(null, true)}>
      — CLIC per lasciare vuoto —
    </div>

    <div class="ass-table-wrap">
      <table class="ass-table">
        <thead>
          <tr style="text-align:center">
            <th>Lavoratore</th>
            {#if !assColHidden['wd']}<th class="ass-th-toggle"><span>WD</span><button class="ass-eye-btn" onclick={() => assColHidden = {...assColHidden, wd: true}}><i class="bi bi-eye-fill"></i></button></th>{/if}
            {#if !assColHidden['des']}<th class="ass-th-toggle"><span>Des</span><button class="ass-eye-btn" onclick={() => assColHidden = {...assColHidden, des: true}}><i class="bi bi-eye-fill"></i></button></th>{/if}
            {#if !assColHidden['note']}<th class="ass-th-toggle"><span>Note</span><button class="ass-eye-btn" onclick={() => assColHidden = {...assColHidden, note: true}}><i class="bi bi-eye-fill"></i></button></th>{/if}
            {#if !assColHidden['turni']}<th class="ass-th-toggle"><span>Turni</span><button class="ass-eye-btn" onclick={() => assColHidden = {...assColHidden, turni: true}}><i class="bi bi-eye-fill"></i></button></th>{/if}
            {#each conteggiConfig.filter(c => c.attivo) as cc}
              {#if !assColHidden[cc.id]}<th class="ass-th-toggle" title={cc.label} style="font-size:.7rem;white-space:nowrap"><span>{cc.label}</span><button class="ass-eye-btn" onclick={() => assColHidden = {...assColHidden, [cc.id]: true}}><i class="bi bi-eye-fill"></i></button></th>{/if}
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each disp as d}
            {@const stats = turniPerUtente[d.user_id]}
            {@const tLav = stats?.turni ?? 0}
            {@const oLav = stats?.ore ?? 0}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <tr class="ass-row {d.disponibile ? '' : 'ass-unavail'} {!d.disponibile && !forzaInserimento ? 'ass-blocked' : ''} {currentUserId === d.user_id ? 'ass-current' : ''}"
                onclick={() => assegnaUtente(d.user_id, d.disponibile)}>
              <td class="ass-sigla">{d.sigla}</td>
              {#if !assColHidden['wd']}
                <td class="{d.wd_tipo === 'assenza' ? 'text-danger' : d.wd_tipo === 'lavorativo' ? 'text-success' : ''}">
                  {d.wd_sigla ?? ''}
                </td>
              {/if}
              {#if !assColHidden['des']}
                <td class="{d.des_tipo === 'assenza' ? 'text-danger' : d.des_tipo === 'lavorativo' ? 'text-success' : ''}">
                  {d.des_sigla ?? ''}
                </td>
              {/if}
              {#if !assColHidden['note']}
                <td class="ass-note">
                  {d.wd_note || d.des_note || ''}
                </td>
              {/if}
              {#if !assColHidden['turni']}
                <td class="ass-turni" class:turni-over={tLav > turniDovuti} class:turni-ok={tLav === turniDovuti}>
                  <span class="turni-count">{tLav}/{turniDovuti}</span>
                  <span class="turni-ore">{fmtOre(oLav)}/{fmtOre(oreDovute)}</span>
                </td>
              {/if}
              {#each conteggiConfig.filter(c => c.attivo) as cc}
                {#if !assColHidden[cc.id]}<td class="text-center" style="font-size:.75rem">{stats?.[cc.id] ?? 0}</td>{/if}
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if Object.values(assColHidden).some(v => v)}
      <div style="padding:2px 10px;display:flex;gap:4px;flex-wrap:wrap;align-items:center;border-top:1px solid var(--ctx-sep, #eee)">
        <span style="font-size:.65rem;color:var(--ctx-muted)">Nascoste:</span>
        {#if assColHidden['wd']}<button class="ass-restore-btn" onclick={() => { const h = {...assColHidden}; delete h.wd; assColHidden = h; }}>WD</button>{/if}
        {#if assColHidden['des']}<button class="ass-restore-btn" onclick={() => { const h = {...assColHidden}; delete h.des; assColHidden = h; }}>Des</button>{/if}
        {#if assColHidden['note']}<button class="ass-restore-btn" onclick={() => { const h = {...assColHidden}; delete h.note; assColHidden = h; }}>Note</button>{/if}
        {#if assColHidden['turni']}<button class="ass-restore-btn" onclick={() => { const h = {...assColHidden}; delete h.turni; assColHidden = h; }}>Turni</button>{/if}
        {#each conteggiConfig.filter(c => c.attivo) as cc}
          {#if assColHidden[cc.id]}<button class="ass-restore-btn" onclick={() => { const h = {...assColHidden}; delete h[cc.id]; assColHidden = h; }}>{cc.label}</button>{/if}
        {/each}
      </div>
    {/if}

    <div style="padding:6px 10px;border-top:1px solid var(--ctx-sep, #eee);display:flex;align-items:center;justify-content:space-between;gap:8px">
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin:0;font-size:.75rem">
        <input type="checkbox" bind:checked={forzaInserimento} />
        <span>Forza inserimento</span>
      </label>
      <button class="btn btn-sm {isCellaBloccata(assMenu.turnoId, assMenu.giorno) ? 'btn-outline-warning' : 'btn-outline-secondary'} py-0"
              style="font-size:.7rem"
              onclick={() => { toggleCellaBloccata(assMenu.turnoId, assMenu.giorno); closeAssMenu(); }}>
        <i class="bi {isCellaBloccata(assMenu.turnoId, assMenu.giorno) ? 'bi-unlock' : 'bi-lock'} me-1"></i>
        {isCellaBloccata(assMenu.turnoId, assMenu.giorno) ? 'Sblocca' : 'Blocca'}
      </button>
    </div>

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="ctx-drag-bar ctx-drag-bottom" onmousedown={onAssDragStart}>
      <span style="font-size:.6rem;color:var(--ctx-muted)">⠿ trascina</span>
    </div>
  </div>
{/if}

<!-- ── MODALE ASPETTO GRIGLIA ─────────────────────────────────── -->
{#if appModalOpen}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-backdrop-custom" onclick={() => appModalOpen = false}></div>
  <div class="solver-modal" style="min-width:520px;max-width:620px">
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h6 class="mb-0 fw-bold"><i class="bi bi-palette me-2 text-info"></i>Aspetto griglia</h6>
      <button class="btn-close btn-close-sm" onclick={() => appModalOpen = false}></button>
    </div>

    <!-- Aspetto griglia -->
    <p class="text-muted small mb-2">
      Modifica i colori del calendario. Salvando, le modifiche sono visibili subito nella griglia.
    </p>
    <AppearanceEditor appearance={appLocal} onchange={onAppChange} />

    <!-- Separatore -->
    <hr class="my-3" />

    <!-- Colori intestazione Excel -->
    <p class="text-muted small mb-2 fw-semibold">
      <i class="bi bi-file-earmark-excel me-1 text-success"></i>Intestazione Excel
    </p>
    <div class="d-flex gap-3 flex-wrap align-items-center">
      <div class="d-flex align-items-center gap-2">
        <label class="small mb-0">Sfondo</label>
        <input type="color"
               class="form-control form-control-color form-control-sm"
               style="width:34px;height:26px;padding:2px"
               bind:value={exportHeaderBg} />
        <span class="font-monospace small">{exportHeaderBg}</span>
      </div>
      <div class="d-flex align-items-center gap-2">
        <label class="small mb-0">Testo</label>
        <input type="color"
               class="form-control form-control-color form-control-sm"
               style="width:34px;height:26px;padding:2px"
               bind:value={exportHeaderFg} />
        <span class="font-monospace small">{exportHeaderFg}</span>
      </div>
    </div>

    <!-- Footer -->
    <div class="d-flex gap-2 mt-3 justify-content-end">
      <button class="btn btn-secondary btn-sm" onclick={() => appModalOpen = false}>
        Chiudi
      </button>
      <button class="btn btn-primary btn-sm"
              onclick={salvaApp}
              disabled={!appLocalDirty || appLocalLoading}>
        {#if appLocalLoading}
          <span class="spinner-border spinner-border-sm me-1"></span>
        {/if}
        Salva aspetto
      </button>
    </div>
  </div>
{/if}
