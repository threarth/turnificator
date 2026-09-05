<script>
  import { onMount } from 'svelte';
  import { adminApi, exportApi } from '$lib/api.js';
  import { user as userStore } from '$lib/auth.js';
  import { showToast } from '$lib/toast.js';
  import GridPreview from '$lib/GridPreview.svelte';
  import {
    focusOnMount, focusIf, createAutoFocus, autowidth,
    editRowKeydown, startEditFromRow as _startEditFromRow
  } from '$lib/admin/actions.js';
  import DeleteButton from '$lib/admin/DeleteButton.svelte';
  import ImportDesiderata from '$lib/admin/ImportDesiderata.svelte';
  import FlagRow from '$lib/admin/FlagRow.svelte';
  import FlagForm from '$lib/admin/FlagForm.svelte';
  import ConfigurazioneGuidata from '$lib/admin/guidata/ConfigurazioneGuidata.svelte';
  import PropostaConfigurazione from '$lib/admin/PropostaConfigurazione.svelte';
  import { etichettaStruttura, etichettaManager,
           leggiEtichettaDaConfig, leggiEtichettaManager } from '$lib/etichette.js';
  import { decToHm, hmToDec, hmToMin, minToHm } from '$lib/admin/durate.js';
  import { NOME_TURNO_TIPO } from '$lib/fasceOrarie.js';
  import { TIPI_REGOLA, etichettaBreve } from '$lib/regole.js';
  import AccessoDropdown from '$lib/admin/AccessoDropdown.svelte';
  import EditableTable from '$lib/admin/EditableTable.svelte';
  import StyleContextMenu from '$lib/StyleContextMenu.svelte';
  import VincoliSolver from '$lib/admin/VincoliSolver.svelte';
  import AppearanceEditor, { APPEARANCE_DEFAULT as APP_DEFAULT } from '$lib/admin/AppearanceEditor.svelte';

  // Tab attiva
  let tab = 'calendari';

  // ── Calendari ──────────────────────────────────────────────────
  let calendari   = [];
  let nuovoCal    = { mese: '', anno: new Date().getFullYear() };
  // La struttura turni dell'organizzazione: ce n'e' una sola, ed e' quella
  // predefinita — o l'unica, se nessuna porta il segno.
  $: strutturaDelTenant = presets.find(p => p.is_default)
      ?? (presets.length ? presets[presets.length - 1] : null);

  // La scheda "Struttura turni" apre da sola quella dell'organizzazione:
  // e' una sola, e sceglierla da una lista non e' piu' una domanda sensata.
  $: if (tab === 'strutturaturni' && strutturaDelTenant
         && editPreset?.id !== strutturaDelTenant.id) {
    apriPreset(strutturaDelTenant);
  }
  let msgCal      = '';

  // ── Utenti ─────────────────────────────────────────────────────
  let utenti      = [];
  let nuovoUtente = { username: '', password: '', role: 'basic', sigla: '', sovragruppo_id: null };
  let editingUtente = null;   // inline edit row (click-to-edit pattern)
  let msgUtenti   = '';

  // Lista sovragruppi della struttura corrente (preset is_default)
  let sovragruppiDisponibili = [];

  // ── Accesso Manager ──────────────────────────────────────────
  let accessoManagerData = null;   // { managers, accesso_utenti, accesso_turni }
  let accessoVersion = 0;         // incrementato ad ogni salvataggio per forzare re-render label
  let accessoDropdownOpen = null;  // 'user_<id>' | 'turno_<id>' | 'sg_<id>' | 'g_<id>' | 'bulk_utenti' | null
  let accessoSaving = false;

  // ── Bulk generico utenti ─────────────────────────────────────
  // Pattern: seleziona utenti → scegli un campo → imposta valore → Applica.
  let bulkSelectedUsers = new Set();
  let bulkCampo = 'sovragruppo_id';  // campo su cui applicare la modifica
  let bulkValore = null;             // valore da applicare (tipo dipende dal campo)
  let bulkManagerChecked = new Set();  // usato solo quando bulkCampo === 'accesso_manager'
  let bulkManagerLabel = 'Tutti';
  let bulkLoading = false;
  $: bulkBasicUsers = utenti.filter(u => u.is_active);
  $: bulkAllSelected = bulkBasicUsers.length > 0 && bulkBasicUsers.every(u => bulkSelectedUsers.has(u.id));

  // ── Struttura preset ───────────────────────────────────────────
  let presets       = [];
  let msgStruttura  = '';
  let editPreset    = null;   // { id, nome, struttura: [...] }
  let autoSigla     = true;

  // Esclusioni turno per preset (sezione sotto l'editor struttura)
  let etPresetData    = [];     // [{id, user_id, tipo, target_id}] caricati dal backend
  let etPresetForm    = { user_id: null, tipo: 'turno', target_id: null };
  let etPresetLoading = false;
  let showEtSection   = false;  // sezione collassabile

  // Appearance preset
  let appearance     = { ...APP_DEFAULT };
  let appDirty       = false;
  let appLoading     = false;
  let showAppSection = false;

  // Form inline add
  let activeAddGruppo = null;          // sgId
  let activeAddTurno  = null;          // 'sgId:gId' stringa
  let nuovoSg     = { nome: '', sigla: '', ambito: '' };

  // Configurazione guidata: il tenant ne ha una sola, quindi si riapre
  // sempre quella, non se ne sceglie una fra tante.

  // Proposta arrivata dal gestore dell'installazione, se ce n'e' una.
  let proposta = null;

  let nuovoGruppo = { nome: '', sigla: '', flag_id: null };
  let nuovoTurno  = { nome: '', tipiQualitativoIds: [] };
  let showAddSg   = false;

  // Editing inline su nodi esistenti
  let editingNode  = null;   // 'sg:sgId' | 'g:sgId:gId' | 't:sgId:gId:tId'
  let editingValue = {};

  // Drag-to-reorder
  let dragItem = null;

  // Contatore local_id per nuovi nodi (temporanei, stringa es. 'n1')
  let _nextId = 0;
  function nextId() { return 'n' + (++_nextId); }

  // Auto-focus system per editing inline (usa createAutoFocus da actions.js)
  const { focusField: _focusField, autoFocus } = createAutoFocus();
  function startEditFromRow(e, setEdit) {
    _startEditFromRow(e, setEdit, { focusField: _focusField });
  }

  // ── Tipi qualitativo ─────────────────────────────────────────
  let tipiQualitativo     = [];
  let showAddTipoQual     = false;
  let nuovoTipoQual       = { nome: '', descrizione: '', carico_lavoro: 0 };
  // ── Regole conflitto ───────────────────────────────────────────
  let regoleConflitto = [];
  let showAddRegola   = false;
  let editingRegola   = null;
  const REGOLA_VUOTA = {
    nome: '', tipo_regola: 'tipo_vs_tipo', flag_a_id: null, flag_b_id: null,
    offset_giorni: 0, categoria: 'consigliata', stile: '{"backgroundColor":"#fff3cd","color":"#856404"}',
    blocca_inserimento: false, peso_numerico: 1.0
  };
  let nuovaRegola = { ...REGOLA_VUOTA };

  // ── Flag turno (globali) ──────────────────────────────────────
  // Pausa obbligatoria di default, in minuti: si somma alla durata netta.
  const PAUSA_DEFAULT_MINUTI = 10;


  let flagTurno       = [];
  // Tipo del flag in creazione ('lavorativo' | 'assenza'), null se il form
  // e' chiuso: distingue quale delle due tabelle mostra il form.
  let showAddFlag     = null;
  let editingFlag     = null;
  let nuovoFlag       = flagVuoto();
  let collapsedFlags  = new Set();

  // ── Tipi richiesta (desiderata, globali) ─────────────────────
  let tipiRichiesta     = [];
  let showAddTipoRich   = false;
  let nuovoTipoRich     ={ sigla: '', descrizione: '', tipo: 'lavorativo', counting_flag: true, ore_default: null, ordine: 0, flag_id: null };

  // ── Stili regole conflitto ────────────────────────────────────
  let regoleDirty = false;

  // ── Config ─────────────────────────────────────────────────────
  let config    = {};
  let msgConfig = '';
  let conteggiConfig = [];
  let showAddConteggio = false;
  // Un conteggio guarda una fascia oraria (per nome, con discendenza)
  // oppure una tipologia turno (per id). Quelli salvati prima non hanno
  // il campo `tipo` e si leggono come fascia.
  let nuovoConteggio = conteggioVuoto();
  // ── Vincoli Solver (stato gestito da VincoliSolver.svelte) ──
  let vincoliGlobali = [];
  let vincoliSolver = [];

  // ── Preset Ottimizzazione ────────────────────────────────────
  let presetOtt = [];
  let showAddPresetOtt = false;
  let nuovoPresetOtt = { nome: '', tipo: 'completo', ref_id: null, pesi: { ore: 1, target: 1, festivi: 1, peso: 1, varieta: 1, desiderata: 1 } };
  let editPresetOttId = null;

  async function caricaPresetOtt() {
    const r = await adminApi.getPresetOttimizzazione();
    presetOtt = r.preset ?? [];
  }

  async function creaPresetOtt() {
    const r = await adminApi.creaPresetOttimizzazione(nuovoPresetOtt);
    if (r.ok) {
      setMsg('cfg', 'Preset creato.');
      nuovoPresetOtt = { nome: '', tipo: 'completo', ref_id: null, pesi: { ore: 1, target: 1, festivi: 1, peso: 1, varieta: 1, desiderata: 1 } };
      showAddPresetOtt = false;
      await caricaPresetOtt();
    } else setMsg('cfg', r.errore || 'Errore', false);
  }

  async function salvaPresetOtt(p) {
    const r = await adminApi.editPresetOttimizzazione(p.id, p);
    if (r.ok) {
      setMsg('cfg', 'Preset aggiornato.');
      editPresetOttId = null;
      await caricaPresetOtt();
    } else setMsg('cfg', r.errore || 'Errore', false);
  }

  async function eliminaPresetOtt(id) {
    if (!confirm('Eliminare questo preset?')) return;
    const r = await adminApi.delPresetOttimizzazione(id);
    if (r.ok) {
      setMsg('cfg', 'Preset eliminato.');
      await caricaPresetOtt();
    } else setMsg('cfg', r.errore || 'Errore', false);
  }

  async function togglePresetOttActive(p) {
    p.is_active = p.is_active ? 0 : 1;
    await salvaPresetOtt(p);
  }

  // ── Export annuale ────────────────────────────────────────────
  let annoExport = new Date().getFullYear();
  let esclusiAnnuale = {};  // { cal_id: true } per calendari APERTO esclusi

  $: calendariAnno = calendari.filter(c => c.anno === annoExport);
  $: calendariApertiAnno = calendariAnno.filter(c => c.stato === 'APERTO');
  $: idsEsclusi = Object.entries(esclusiAnnuale).filter(([,v]) => v).map(([k]) => +k);
  function downloadAnnuale() { return exportApi.annuale(annoExport, idsEsclusi); }

  function resetEsclusi() { esclusiAnnuale = {}; }

  const NOMI_MESI = ['','Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
                     'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'];

  // Helper: formatta il nome di un flag con il concetto che lo contiene.
  // - fascia oraria: "concetto→fascia"
  // - concetto root: "concetto"
  function flagLabel(nameOrId, _flags = flagTurno) {
    if (!nameOrId && nameOrId !== 0) return '—';
    const f = typeof nameOrId === 'number'
      ? _flags.find(x => x.id === nameOrId)
      : _flags.find(x => x.nome === nameOrId);
    if (!f) return String(nameOrId);
    return f.parent_nome ? `${f.parent_nome}→${f.nome}` : f.nome;
  }

  function regolaStyle(r) {
    if (!r?.stile) return '';
    try {
      const st = typeof r.stile === 'string' ? JSON.parse(r.stile) : r.stile;
      return `background:${st.backgroundColor || '#6c757d'};color:${st.color || '#fff'}`;
    } catch { return ''; }
  }

  onMount(() => caricaTutto());

  async function caricaTutto() {
    const [rc, ru, rp, rtq, rrg, rfl, rtr, rac] = await Promise.all([
      adminApi.getCalendari(),
      adminApi.getUtenti(),
      adminApi.getPresets(),
      adminApi.getTipiQualitativo(),
      adminApi.getRegoleConflitto(),
      adminApi.getFlagTurno(),
      adminApi.getTipi(),
      adminApi.getAccessoManager(),
    ]);
    calendari       = rc.calendari      ?? [];
    utenti          = ru.utenti         ?? [];
    presets         = rp.presets        ?? [];
    tipiQualitativo = rtq.tipi          ?? [];
    regoleConflitto = rrg.regole        ?? [];
    flagTurno       = rfl.flags         ?? [];
    tipiRichiesta   = rtr.tipi          ?? [];
    accessoManagerData = rac.ok ? rac : null;
    // Inizializza flag_id default per nuovoGruppo (primo flag lavorativo)
    const flagStrutt = flagTurno.filter(f => f.mostra_in_struttura);
    if (flagStrutt.length && !nuovoGruppo.flag_id) {
      nuovoGruppo.flag_id = flagStrutt[0].id;
    }
    const cfg = await adminApi.getConfig();
    config = cfg.config ?? {};
    leggiEtichettaDaConfig(config);
    leggiEtichettaManager(config);
    try {
      proposta = (await adminApi.getProposta()).proposta ?? null;
    } catch { proposta = null; }
    try { conteggiConfig = JSON.parse(config['conteggi_context'] || '[]'); } catch { conteggiConfig = []; }
    // Vincoli solver
    const [rvg, rvs] = await Promise.all([
      adminApi.getVincoliGlobali(),
      adminApi.getVincoliSolver(),
    ]);
    vincoliGlobali = rvg.vincoli ?? [];
    vincoliSolver = rvs.vincoli ?? [];
    caricaPresetOtt();
    // Carica sovragruppi dalla struttura corrente (per select sovragruppo utente)
    try {
      const rord = await adminApi.getOrdinamentoDesiderata();
      sovragruppiDisponibili = rord.sovragruppi ?? [];
    } catch (err) {
      sovragruppiDisponibili = [];
    }
  }

  // ── Helper messaggi temporanei ─────────────────────────────────
  function setMsg(target, msg, ok = true) {
    if (target === 'cal')    { msgCal      = (ok ? '✓ ' : '✗ ') + msg; setTimeout(() => msgCal      = '', 3000); }
    if (target === 'utenti') { msgUtenti   = (ok ? '✓ ' : '✗ ') + msg; setTimeout(() => msgUtenti   = '', 3000); }
    if (target === 'stru')   { msgStruttura= (ok ? '✓ ' : '✗ ') + msg; setTimeout(() => msgStruttura= '', 3000); }
    if (target === 'cfg')    { msgConfig   = (ok ? '✓ ' : '✗ ') + msg; setTimeout(() => msgConfig   = '', 3000); }
    if (ok) showToast(msg);
    else showToast(msg, false);
  }

  // ── Calendari ──────────────────────────────────────────────────
  async function creaCal() {
    const r = await adminApi.creaCalendario(nuovoCal);
    if (r.ok) { setMsg('cal', r.messaggio); calendari = (await adminApi.getCalendari()).calendari ?? []; nuovoCal.mese = ''; }
    else setMsg('cal', r.errore, false);
  }
  async function eliminaCalendario(id, mese, anno) {
    if (!confirm(`Eliminare definitivamente il calendario ${NOMI_MESI[mese]} ${anno}?\nTutti i dati (assegnazioni, desiderata, history) verranno cancellati.`)) return;
    const r = await adminApi.eliminaCalendario(id);
    if (r.ok) { setMsg('cal', r.messaggio); calendari = (await adminApi.getCalendari()).calendari ?? []; }
    else setMsg('cal', r.errore, false);
  }
  async function riazzeraCalendario(id, mese, anno) {
    if (!confirm(`Riazzerare il calendario ${NOMI_MESI[mese]} ${anno}?\nLe assegnazioni e la history verranno cancellate. Desiderata e struttura resteranno invariati.`)) return;
    const r = await adminApi.riazzeraCalendario(id);
    if (r.ok) { setMsg('cal', r.messaggio); calendari = (await adminApi.getCalendari()).calendari ?? []; }
    else setMsg('cal', r.errore, false);
  }

  // Ricarica struttura calendario da preset
  let ricaricaPresetId = {};  // cal_id → preset selezionato
  async function ricaricaStruttura(calId, mese, anno, presetId) {
    if (!presetId) { setMsg('cal', 'Selezionare un preset.', false); return; }
    // 1. Preview
    const prev = await adminApi.ricaricaStruttura(calId, { mode: 'preview', preset_id: presetId });
    if (!prev.ok) { setMsg('cal', prev.errore, false); return; }
    const d = prev.diff;
    let msg = `Ricarica struttura ${NOMI_MESI[mese]} ${anno}:\n\n`;
    if (d.aggiunti.length) msg += `• Turni aggiunti: ${d.aggiunti.join(', ')}\n`;
    if (d.rimossi.length) msg += `• Turni rimossi: ${d.rimossi.join(', ')}\n`;
    msg += `• Turni aggiornati: ${d.aggiornati}\n`;
    if (d.assegnazioni_perse) msg += `\n⚠ ${d.assegnazioni_perse} assegnazioni verranno perse!\n`;
    msg += `\nVerranno aggiornati:\n` +
           `  - Struttura turni (sigla, flag, stile, ore, priorità)\n` +
           `  - Regole di conflitto\n` +
           `  - Vincoli globali e per utente\n` +
           `  - Vincoli solver (fascia oraria / tipologia)\n` +
           `  - Esclusioni utente\n` +
           `  - Accesso manager (turni e utenti)\n` +
           `  - Gerarchia flag turno\n` +
           `\nLa cronologia (undo/redo) verrà ripulita.\nOperazione non reversibile. Procedere?`;
    if (!confirm(msg)) return;
    // 2. Apply
    const r = await adminApi.ricaricaStruttura(calId, { mode: 'apply', preset_id: presetId });
    if (r.ok) { setMsg('cal', r.messaggio); calendari = (await adminApi.getCalendari()).calendari ?? []; }
    else setMsg('cal', r.errore, false);
  }
  async function avanzaStato(id, nuovoStato) {
    const msg = nuovoStato === 'CHIUSO'
      ? 'Chiudere il calendario?\n\nVerrà creato anche il calendario effettivo. Le modifiche saranno bloccate ma la history viene preservata.'
      : `Portare il calendario a ${nuovoStato}?`;
    if (!confirm(msg)) return;
    const r = await adminApi.statoCalendario(id, nuovoStato);
    if (r.ok) { setMsg('cal', r.messaggio); calendari = (await adminApi.getCalendari()).calendari ?? []; }
    else setMsg('cal', r.errore, false);
  }
  async function riapriCalendario(id) {
    if (!confirm(
      'Riaprire il calendario?\n\n' +
      '• Il calendario effettivo verrà eliminato (insieme alla sua history).\n' +
      '• Il calendario principale tornerà APERTO per modifiche; la sua history viene preservata.\n\n' +
      'Continuare?'
    )) return;
    const r = await adminApi.statoCalendario(id, 'APERTO');
    if (r.ok) { setMsg('cal', r.messaggio); calendari = (await adminApi.getCalendari()).calendari ?? []; }
    else setMsg('cal', r.errore, false);
  }
  async function congelaDesiderata(id) {
    if (!confirm(
      'Congelare i desiderata?\n\n' +
      '• I lavoratori non potranno più modificarli.\n' +
      '• Verrà creata una copia di lavoro (Working Desiderata) utilizzata in fase di inserimento turni per risolvere i conflitti.\n\n' +
      'Continuare?'
    )) return;
    const r = await adminApi.congelaDesiderata(id);
    if (r.ok) { setMsg('cal', r.messaggio); calendari = (await adminApi.getCalendari()).calendari ?? []; }
    else setMsg('cal', r.errore, false);
  }
  async function scongelaDesiderata(id) {
    if (!confirm(
      'Scongelare i desiderata?\n\n' +
      '• I lavoratori potranno nuovamente modificarli.\n' +
      '• I Working Desiderata verranno eliminati.\n\n' +
      'Continuare?'
    )) return;
    const r = await adminApi.scongelaDesiderata(id);
    if (r.ok) { setMsg('cal', r.messaggio); calendari = (await adminApi.getCalendari()).calendari ?? []; }
    else setMsg('cal', r.errore, false);
  }

  // ── Utenti ─────────────────────────────────────────────────────
  async function createUser() {
    const payload = { ...nuovoUtente };
    // sovragruppo_id vuoto o "null" (string dal select) → null effettivo
    if (payload.sovragruppo_id === '' || payload.sovragruppo_id === 'null') payload.sovragruppo_id = null;
    const r = await adminApi.createUser(payload);
    if (r.ok) {
      setMsg('utenti', 'Utente creato.');
      utenti = (await adminApi.getUtenti()).utenti ?? [];
      nuovoUtente = { username:'', password:'', role:'basic', sigla:'', sovragruppo_id: null };
    } else setMsg('utenti', r.errore, false);
  }
  async function salvaUtente() {
    const r = await adminApi.editUtente(editingUtente.id, editingUtente);
    if (r.ok) {
      setMsg('utenti', 'Utente aggiornato.');
      utenti = (await adminApi.getUtenti()).utenti ?? [];
      // Salva accesso manager se modificato
      if (editingUtente._accessoChecked) {
        const orig = editingUtente._accessoOriginal;
        const curr = editingUtente._accessoChecked;
        const changed = orig.size !== curr.size || [...orig].some(id => !curr.has(id));
        if (changed) await _salvaAccesso('utenti', editingUtente.id, checkedToDb(curr));
      }
      editingUtente = null;
    } else setMsg('utenti', r.errore, false);
  }
  async function disabilitaUtente(id) {
    if (!confirm('Disabilitare questo utente?')) return;
    const r = await adminApi.disUtente(id);
    if (r.ok) { setMsg('utenti', 'Utente disabilitato.'); utenti = (await adminApi.getUtenti()).utenti ?? []; }
    else setMsg('utenti', r.errore, false);
  }
  async function riattivaUtente(id) {
    const r = await adminApi.editUtente(id, { is_active: true });
    if (r.ok) { setMsg('utenti', 'Utente riattivato.'); utenti = (await adminApi.getUtenti()).utenti ?? []; }
    else setMsg('utenti', r.errore, false);
  }
  // ── Accesso Manager — helper ──────────────────────────────────
  // Lista manager attivi (admin ha sempre accesso completo, non serve nel dropdown)
  $: accessoManagers = accessoManagerData
    ? accessoManagerData.managers.filter(m => m.role === 'manager')
    : [];

  // Ritorna set di manager IDs checked.
  // Chiave assente nel map = nessuna restrizione → tutti checked.
  // Chiave presente con [] = ristretto a nessuno → set vuoto.
  function getAccessoChecked(tipo, entityId) {
    if (!accessoManagerData) return new Set();
    const map = tipo === 'utenti' ? accessoManagerData.accesso_utenti : accessoManagerData.accesso_turni;
    const ids = map[String(entityId)];
    if (ids === undefined) return new Set(accessoManagers.map(m => m.id));
    return new Set(ids);
  }

  function _accessoLabelFromSet(checked) {
    if (!accessoManagers.length) return 'Tutti';
    if (checked.size >= accessoManagers.length) return 'Tutti';
    const nomi = accessoManagers.filter(m => checked.has(m.id)).map(m => m.sigla).join(', ');
    return `${checked.size}/${accessoManagers.length}${nomi ? ': ' + nomi : ''}`;
  }
  function accessoLabel(tipo, entityId, _v) {
    // _v = accessoVersion, usato per forzare reattività in Svelte 4
    return _accessoLabelFromSet(getAccessoChecked(tipo, entityId));
  }

  function toggleAccessoDropdown(key) {
    accessoDropdownOpen = accessoDropdownOpen === key ? null : key;
  }

  // Converti set checked → valore DB.
  // Tutti checked → null (rimuovi restrizione, chiave sparisce dal map).
  // 0 checked → [] (sentinel: ristretto a nessuno).
  // N checked → [id1, id2, ...].
  function checkedToDb(checked) {
    if (checked.size >= accessoManagers.length) return null;
    return [...checked];
  }

  async function _salvaAccesso(tipo, entityId, dbVal) {
    const key = String(entityId);
    const map = tipo === 'utenti' ? accessoManagerData.accesso_utenti : accessoManagerData.accesso_turni;
    if (dbVal === null) {
      delete map[key];  // null = rimuovi restrizione (chiave assente = tutti)
    } else {
      map[key] = dbVal;  // [] = nessun manager, [ids] = whitelist
    }
    accessoManagerData = accessoManagerData;
    accessoVersion++;
    try {
      if (tipo === 'utenti') await adminApi.setAccessoUtenti({ accesso: { [key]: dbVal } });
      else await adminApi.setAccessoTurni({ accesso: { [key]: dbVal } });
    } catch (err) {
      console.error('Errore salvataggio accesso:', err);
      setMsg('struttura', 'Errore salvataggio accesso manager.', false);
    }
  }

  async function toggleAccessoSingolo(tipo, entityId, managerId) {
    const checked = getAccessoChecked(tipo, entityId);
    if (checked.has(managerId)) checked.delete(managerId);
    else checked.add(managerId);
    await _salvaAccesso(tipo, entityId, checkedToDb(checked));
  }

  async function toggleAccessoTutti(tipo, entityId) {
    const checked = getAccessoChecked(tipo, entityId);
    const allChecked = checked.size >= accessoManagers.length;
    // Tutti checked → deseleziona tutti (nessun manager); altrimenti → seleziona tutti
    const nuovi = allChecked ? [] : accessoManagers.map(m => m.id);
    const nuovoChecked = new Set(nuovi);
    await _salvaAccesso(tipo, entityId, checkedToDb(nuovoChecked));
  }

  // ── Accesso bulk SG / gruppo ─────────────────────────────────
  function _isDbId(id) {
    return typeof id === 'number' || (typeof id === 'string' && !id.startsWith('n'));
  }

  function _hasUnsavedTurni(type, entityId) {
    if (!editPreset) return false;
    for (const sg of editPreset.struttura) {
      if (type === 'sg' && String(sg.id) !== String(entityId)) continue;
      for (const g of sg.gruppi) {
        if (type === 'g' && String(g.id) !== String(entityId)) continue;
        for (const t of g.turni) {
          if (!_isDbId(t.id)) return true;
        }
        if (type === 'g') break;
      }
      if (type === 'sg') break;
    }
    return false;
  }

  function _collectTurniIds(type, entityId) {
    const ids = [];
    if (!editPreset) return ids;
    for (const sg of editPreset.struttura) {
      if (type === 'sg' && String(sg.id) !== String(entityId)) continue;
      for (const g of sg.gruppi) {
        if (type === 'g' && String(g.id) !== String(entityId)) continue;
        for (const t of g.turni) ids.push(t.id);
        if (type === 'g') break;
      }
      if (type === 'sg') break;
    }
    return ids;
  }

  function accessoLabelBulk(type, entityId, _v) {
    const turniIds = _collectTurniIds(type, entityId);
    if (!turniIds.length) return 'Tutti';
    const sets = turniIds.map(tid => getAccessoChecked('turni', tid));
    const first = sets[0];
    const allSame = sets.every(s => s.size === first.size && [...first].every(id => s.has(id)));
    if (allSame) return _accessoLabelFromSet(first);
    return 'Misto';
  }

  function _getBulkChecked(type, entityId) {
    const ids = _collectTurniIds(type, entityId);
    if (!ids.length) return new Set(accessoManagers.map(m => m.id));
    const sets = ids.map(tid => getAccessoChecked('turni', tid));
    const first = sets[0];
    const same = sets.every(s => s.size === first.size && [...first].every(id => s.has(id)));
    return same ? new Set(first) : new Set(accessoManagers.map(m => m.id));
  }

  async function salvaAccessoBulk(type, entityId, checkedSet) {
    if (_hasUnsavedTurni(type, entityId)) {
      setMsg('stru', 'Salva prima la struttura: ci sono turni non ancora salvati.', false);
      return;
    }
    const turniIds = _collectTurniIds(type, entityId);
    if (!turniIds.length) return;
    const dbVal = checkedToDb(checkedSet);
    const accesso = {};
    for (const tid of turniIds) {
      const key = String(tid);
      accesso[key] = dbVal;
      if (dbVal === null) delete accessoManagerData.accesso_turni[key];
      else accessoManagerData.accesso_turni[key] = dbVal;
    }
    accessoManagerData = accessoManagerData;
    accessoVersion++;
    try {
      await adminApi.setAccessoTurni({ accesso });
    } catch (err) {
      console.error('Errore salvataggio accesso bulk:', err);
      setMsg('stru', 'Errore salvataggio accesso manager.', false);
    }
  }

  // Applica una modifica bulk a un campo qualunque su N utenti selezionati.
  // Caso speciale: 'accesso_manager' non e' un campo della tabella users,
  // quindi va dispacciato al vecchio endpoint set_accesso_utenti.
  async function applicaBulkUtenti() {
    if (bulkSelectedUsers.size === 0) return;
    bulkLoading = true;
    try {
      if (bulkCampo === 'accesso_manager') {
        const dbVal = checkedToDb(bulkManagerChecked);
        const accesso = {};
        for (const uid of bulkSelectedUsers) {
          const key = String(uid);
          accesso[key] = dbVal;
          if (dbVal === null) delete accessoManagerData.accesso_utenti[key];
          else accessoManagerData.accesso_utenti[key] = dbVal;
        }
        accessoManagerData = accessoManagerData;
        accessoVersion++;
        await adminApi.setAccessoUtenti({ accesso });
        setMsg('utenti', `Accesso manager aggiornato per ${bulkSelectedUsers.size} utenti.`);
      } else {
        // Campo normale della tabella users → bulk generico
        const fields = { [bulkCampo]: _coerceBulkValore(bulkCampo, bulkValore) };
        const r = await adminApi.bulkEditUtenti([...bulkSelectedUsers], fields);
        if (!r.ok) { setMsg('utenti', r.errore || 'Errore', false); return; }
        utenti = (await adminApi.getUtenti()).utenti ?? [];
        setMsg('utenti', `Aggiornati ${bulkSelectedUsers.size} utenti (${_labelCampoBulk(bulkCampo)}).`);
      }
      bulkSelectedUsers = new Set();
    } catch (err) {
      setMsg('utenti', 'Errore applicazione bulk.', false);
    } finally {
      bulkLoading = false;
    }
  }

  // Coerce del valore bulk in base al campo selezionato
  function _coerceBulkValore(campo, val) {
    if (campo === 'sovragruppo_id') {
      if (val === '' || val === null || val === undefined || val === 'null') return null;
      return Number(val);
    }
    if (campo === 'is_active' || campo === 'escluso_turni' || campo === 'puo_gestire_calendari') {
      return val ? 1 : 0;
    }
    if (campo === 'role') return String(val);
    if (campo === 'offusca') return Number(val);
    return val;
  }

  function _labelCampoBulk(campo) {
    return {
      sovragruppo_id:         'Sovragruppo',
      is_active:              'Attivo',
      escluso_turni:          'Escluso turni',
      puo_gestire_calendari:  'Gestione calendari',
      role:                   'Ruolo',
      offusca:                'Privacy',
      accesso_manager:        'Accesso manager',
    }[campo] || campo;
  }

  // Reset valore bulk quando cambia il campo selezionato
  $: if (bulkCampo) {
    if (bulkCampo === 'sovragruppo_id') bulkValore = null;
    else if (bulkCampo === 'role')       bulkValore = 'basic';
    else if (bulkCampo === 'offusca')    bulkValore = 0;
    else if (bulkCampo === 'is_active' || bulkCampo === 'escluso_turni' || bulkCampo === 'puo_gestire_calendari') bulkValore = 1;
  }

  // ── Orfani accesso manager ────────────────────────────────────
  $: accessoOrfani = accessoManagerData?.orfani ?? null;
  $: hasOrfani = accessoOrfani?.has_orfani ?? false;
  let pulisciaOrfaniLoading = false;

  async function pulisciOrfani() {
    pulisciaOrfaniLoading = true;
    try {
      const r = await adminApi.pulisciOrfaniAccesso();
      if (r.ok) {
        setMsg('utenti', `Orfani rimossi: ${r.turni_rimossi} turni, ${r.utenti_rimossi} utenti, ${r.managers_rimossi} manager.`);
        // Ricarica dati accesso
        const rac = await adminApi.getAccessoManager();
        accessoManagerData = rac.ok ? rac : null;
        accessoVersion++;
      }
    } catch {
      setMsg('utenti', 'Errore pulizia orfani.', false);
    }
    pulisciaOrfaniLoading = false;
  }

  // ── Tipi qualitativo ───────────────────────────────────────────
  async function creaTipoQual() {
    const r = await adminApi.creaTipoQualitativo({ ...nuovoTipoQual });
    if (r.ok) {
      tipiQualitativo = (await adminApi.getTipiQualitativo()).tipi ?? [];
      nuovoTipoQual = { nome: '', descrizione: '', carico_lavoro: 0 };
      showAddTipoQual = false;
      setMsg('stru', 'Tipologia creata.');
    } else setMsg('stru', r.errore, false);
  }
  async function salvaTipoQual(obj) {
    const r = await adminApi.editTipoQualitativo(obj.id, obj);
    if (r.ok) {
      tipiQualitativo = (await adminApi.getTipiQualitativo()).tipi ?? [];
      setMsg('stru', 'Tipologia aggiornata.');
    } else setMsg('stru', r.errore, false);
  }
  async function eliminaTipoQual(id) {
    const r = await adminApi.delTipoQualitativo(id);
    if (r.ok) {
      tipiQualitativo = (await adminApi.getTipiQualitativo()).tipi ?? [];
      setMsg('stru', 'Tipologia eliminata.');
    } else if (r.dipendenze) alert(`${r.errore}\n\n${r.dipendenze.join('\n')}`);
    else setMsg('stru', r.errore, false);
  }

  // ── Tipi richiesta (desiderata, globali) ──────────────────────
  async function creaTipoRich() {
    const payload = {
      ...nuovoTipoRich,
      ore_default: nuovoTipoRich.ore_default || null,
      flag_id: nuovoTipoRich.flag_id || null,
    };
    const r = await adminApi.creaTipo(payload);
    if (r.ok) {
      tipiRichiesta = (await adminApi.getTipi()).tipi ?? [];
      nuovoTipoRich = { sigla: '', descrizione: '', tipo: 'lavorativo', counting_flag: true, ore_default: null, ordine: 0, flag_id: null };
      showAddTipoRich = false;
      setMsg('cfg', 'Tipo richiesta creato.');
    } else setMsg('cfg', r.errore, false);
  }
  async function salvaTipoRich(obj) {
    const r = await adminApi.editTipo(obj.id, obj);
    if (r.ok) {
      tipiRichiesta = (await adminApi.getTipi()).tipi ?? [];
      setMsg('cfg', 'Tipo richiesta aggiornato.');
    } else setMsg('cfg', r.errore, false);
  }
  async function eliminaTipoRich(id) {
    const r = await adminApi.delTipo(id);
    if (r.ok) {
      tipiRichiesta = (await adminApi.getTipi()).tipi ?? [];
      setMsg('cfg', 'Tipo richiesta eliminato.');
    } else if (r.dipendenze) alert(`${r.errore}\n\n${r.dipendenze.join('\n')}`);
    else setMsg('cfg', r.errore, false);
  }

  // ── Regole conflitto ───────────────────────────────────────────
  async function creaRegola() {
    const r = await adminApi.creaRegola({ ...nuovaRegola });
    if (r.ok) {
      regoleConflitto = (await adminApi.getRegoleConflitto()).regole ?? [];
      showAddRegola = false;
      nuovaRegola = { ...REGOLA_VUOTA };
      setMsg('cfg', 'Regola creata.');
    } else setMsg('cfg', r.errore, false);
  }
  async function salvaRegola() {
    try {
      const r = await adminApi.editRegola(editingRegola.id, editingRegola);
      if (r.ok) {
        regoleConflitto = (await adminApi.getRegoleConflitto()).regole ?? [];
        editingRegola = null;
        setMsg('cfg', 'Regola aggiornata.');
      } else setMsg('cfg', r.errore || 'Errore salvataggio regola.', false);
    } catch (e) {
      setMsg('cfg', 'Errore salvataggio regola.', false);
    }
  }
  async function eliminaRegola(id) {
    const r = await adminApi.delRegola(id);
    if (r.ok) {
      regoleConflitto = (await adminApi.getRegoleConflitto()).regole ?? [];
      setMsg('cfg', 'Regola eliminata.');
    } else setMsg('cfg', r.errore, false);
  }

  // ── Flag turno ───────────────────────────────────────────────
  // Stato iniziale del form "nuovo flag". I campi con underscore sono le
  // durate in h:mm digitate dall'utente, convertite in decimali al salvataggio.
  function flagVuoto(parentId = null, tipo = 'lavorativo') {
    return {
      nome: '', descrizione: '', parent_id: parentId, tipo,
      orario_inizio: '', orario_fine: '', pausa_minuti: PAUSA_DEFAULT_MINUTI,
      peso_turno: null, _ore_turno: '', _ore_primo: '', _ore_ultimo: '',
    };
  }

  // Converte le durate digitate in h:mm nei decimali attesi dall'API.
  function payloadFlag(flag) {
    const payload = {
      ...flag,
      durata_netta_minuti: hmToMin(flag._netta),
      ore_turno: hmToDec(flag._ore_turno),
      ore_primo_giorno: hmToDec(flag._ore_primo),
      ore_ultimo_giorno: hmToDec(flag._ore_ultimo),
    };
    delete payload._netta;
    delete payload._ore_turno; delete payload._ore_primo; delete payload._ore_ultimo;
    return payload;
  }

  // Apre o chiude le fasce di un concetto nella tabella.
  function toggleCollapseFlag(id) {
    if (collapsedFlags.has(id)) collapsedFlags.delete(id);
    else collapsedFlags.add(id);
    collapsedFlags = collapsedFlags;
  }

  // Apre il form di creazione nella tabella del tipo indicato, o lo richiude.
  function apriNuovoFlag(tipo) {
    if (showAddFlag === tipo) { showAddFlag = null; return; }
    nuovoFlag = flagVuoto(null, tipo);
    showAddFlag = tipo;
  }

  // Una fascia nasce sotto il concetto da cui eredita il tipo.
  function addChildFlag(concetto) {
    nuovoFlag = flagVuoto(concetto.id, concetto.tipo || 'lavorativo');
    showAddFlag = nuovoFlag.tipo;
  }
  function startEditFlag(f) {
    editingFlag = {
      ...f,
      mostra_in_struttura: !!f.mostra_in_struttura,
      orario_inizio: f.orario_inizio || '',
      orario_fine: f.orario_fine || '',
      _netta: minToHm(f.durata_netta_minuti),
      _ore_turno: decToHm(f.ore_turno),
      _ore_primo: decToHm(f.ore_primo_giorno),
      _ore_ultimo: decToHm(f.ore_ultimo_giorno),
    };
  }
  async function creaFlag() {
    const r = await adminApi.creaFlagTurno(payloadFlag(nuovoFlag));
    if (r.ok) {
      flagTurno = (await adminApi.getFlagTurno()).flags ?? [];
      showAddFlag = null;
      nuovoFlag = flagVuoto();
      setMsg('cfg', 'Flag creato.');
    } else setMsg('cfg', r.errore, false);
  }
  async function salvaFlag() {
    const payload = payloadFlag(editingFlag);
    const r = await adminApi.editFlagTurno(payload.id, payload);
    if (r.ok) {
      flagTurno = (await adminApi.getFlagTurno()).flags ?? [];
      editingFlag = null;
      setMsg('cfg', 'Flag aggiornato.');
    } else setMsg('cfg', r.errore, false);
  }

  /**
   * Fasce orarie agganciabili a un gruppo della struttura `sg`.
   *
   * Una fascia vale una volta sola per struttura — il gruppo E' l'insieme dei
   * turni di quella fascia — quindi le fasce gia' usate spariscono dal menu.
   * La fascia del gruppo in modifica resta, o il menu perderebbe il suo valore.
   *
   * @param sg — sovragruppo (struttura) a cui appartiene il gruppo
   * @param gruppoId — id del gruppo in modifica, null se e' nuovo
   * @param _flags — elenco flag, passato per rendere esplicita la dipendenza
   */
  function fasceDisponibili(sg, gruppoId = null, _flags = flagTurno) {
    const usate = new Set(
      (sg?.gruppi ?? [])
        .filter(g => g.id !== gruppoId && g.flag_id != null)
        .map(g => g.flag_id)
    );
    return _flags.filter(f => f.mostra_in_struttura && !usate.has(f.id));
  }
  async function eliminaFlag(id) {
    const r = await adminApi.delFlagTurno(id);
    if (r.ok) {
      flagTurno = (await adminApi.getFlagTurno()).flags ?? [];
      setMsg('cfg', 'Flag eliminato.');
    } else if (r.ha_figli) {
      if (confirm(`${r.errore}\n\nFigli: ${r.dipendenze.join(', ')}\n\nEliminare padre e tutti i figli?`)) {
        const r2 = await adminApi.delFlagTurno(id, { cascade: true });
        if (r2.ok) {
          flagTurno = (await adminApi.getFlagTurno()).flags ?? [];
          setMsg('cfg', 'Flag e figli eliminati.');
        } else if (r2.dipendenze) alert(`${r2.errore}\n\n${r2.dipendenze.join('\n')}`);
        else setMsg('cfg', r2.errore, false);
      }
    } else if (r.dipendenze) {
      alert(`${r.errore}\n\n${r.dipendenze.join('\n')}`);
    } else {
      setMsg('cfg', r.errore, false);
    }
  }
  async function ripristinaFlagDefault() {
    if (!confirm('Ripristinare i flag di default? I flag esistenti non verranno eliminati.')) return;
    const r = await adminApi.ripristinaFlagDefault();
    if (r.ok) {
      flagTurno = (await adminApi.getFlagTurno()).flags ?? [];
      setMsg('cfg', r.messaggio, true);
    } else setMsg('cfg', r.errore, false);
  }

  // Helper: flag radice e figli per organizzazione gerarchica
  $: flagRadice = flagTurno.filter(f => !f.parent_id);
  // Le assenze non sono fasce orarie: vivono in una tabella separata.
  $: concettiLavorativi = flagRadice.filter(f => (f.tipo || 'lavorativo') !== 'assenza');
  $: concettiAssenza    = flagRadice.filter(f => f.tipo === 'assenza');
  $: flagFigli  = (parentId) => flagTurno.filter(f => f.parent_id === parentId);
  // Flag ordinati padre→figli per i <select>
  $: flagOrdinati = flagRadice.flatMap(r => [r, ...flagTurno.filter(f => f.parent_id === r.id)]);

  // Una regola tipo_vs_tipo confronta due turni gia' assegnati: le assenze
  // in griglia non compaiono mai, e il turno tipo e' solo l'unita' di misura
  // del peso. Offrirli sarebbe offrire voci che non scatteranno mai.
  $: fasceRegolaConflitto = flagOrdinati.filter(
    f => (f.tipo || 'lavorativo') !== 'assenza' && f.nome !== NOME_TURNO_TIPO
  );

  // L'intero vocabolario meno il turno tipo, che non classifica nulla:
  // e' l'elenco di cio' che un lavoratore puo' avere in una giornata.
  $: fasceEAssenze = flagOrdinati.filter(f => f.nome !== NOME_TURNO_TIPO);

  // ── Stili regole conflitto ───────────────────────────────────
  async function salvaStiliRegole() {
    let ok = true;
    for (const r of regoleConflitto) {
      const res = await adminApi.editRegola(r.id, r);
      if (!res.ok) { ok = false; setMsg('cfg', res.errore || 'Errore salvataggio stile.', false); break; }
    }
    if (ok) {
      regoleConflitto = (await adminApi.getRegoleConflitto()).regole ?? [];
      regoleDirty = false;
    }
  }
  async function ripristinaStiliRegole() {
    regoleConflitto = (await adminApi.getRegoleConflitto()).regole ?? [];
    regoleDirty = false;
  }

  // ── Struttura preset ───────────────────────────────────────────

  // Auto-sigla da nome
  // I ruoli si mostrano con le parole dell'utente; nel database restano
  // 'basic', 'manager' e 'admin'.
  function nomeRuolo(ruolo) {
    if (ruolo === 'manager') return $etichettaManager.toLowerCase();
    if (ruolo === 'basic') return 'lavoratore';
    if (ruolo === 'admin') return 'amministratore';
    return ruolo;
  }

  function toSigla(nome) {
    return nome.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8) || 'X';
  }
  function turnoSigla(nomeT, g) {
    const base = toSigla(nomeT);
    return autoSigla ? `${base}_${g.sigla}` : base;
  }

  // La configurazione guidata ha scritto la struttura dell'organizzazione:
  // si passa alla scheda che la modifica, dove si rifinisce a mano.
  async function wizardCompletato(presetId, etichetta) {
    etichettaStruttura.set(etichetta);
    presets = (await adminApi.getPresets()).presets ?? [];
    // Solo se una struttura c'e' davvero: mandare a una scheda spenta
    // lascerebbe la pagina su un caricamento che non finisce.
    if (strutturaDelTenant) tab = 'strutturaturni';
    setMsg('stru', 'Struttura turni salvata. Puoi rifinirla qui.');
  }

  async function apriPreset(p) {
    const r = await adminApi.getStrutturaPreset(p.id);
    editPreset = { id: p.id, nome: p.nome, struttura: r.struttura ?? [] };
    editingNode = null;
    activeAddGruppo = null;
    activeAddTurno = null;
    showAddSg = false;
    // Carica esclusioni turno preset e appearance
    etPresetData = [];
    etPresetForm = { user_id: null, tipo: 'turno', target_id: null };
    showEtSection = false;
    showAppSection = false;
    const [re, ra] = await Promise.all([
      adminApi.getEsclusioni_turno(p.id),
      adminApi.getAppearance(p.id),
    ]);
    etPresetData = re.esclusioni ?? [];
    appearance = ra.ok ? { ...APP_DEFAULT, ...ra.appearance } : { ...APP_DEFAULT };
    appDirty = false;
  }

  // ── Esclusioni turno preset (admin editor) ───────────────────

  function _etPresetTargets(tipo) {
    const sgs = editPreset?.struttura ?? [];
    if (tipo === 'sovragruppo') {
      return sgs.map(sg => ({ id: sg.id, label: `${sg.sigla} — ${sg.nome}` }));
    }
    if (tipo === 'gruppo') {
      return sgs.flatMap(sg =>
        sg.gruppi.map(g => ({ id: g.id, label: `${g.sigla} — ${g.nome}` }))
      );
    }
    return sgs.flatMap(sg =>
      sg.gruppi.flatMap(g =>
        g.turni.map(t => ({ id: t.id, label: `${t.sigla} — ${t.nome || t.sigla}` }))
      )
    );
  }

  /**
   * Ritorna i figli/nipoti selezionabili come eccezioni per una esclusione di tipo gruppo/SG.
   * Per gruppo: turni del gruppo. Per SG: gruppi e turni del SG.
   */
  function _etPresetFigli(esc) {
    const sgs = editPreset?.struttura ?? [];
    if (esc.tipo === 'gruppo') {
      for (const sg of sgs) {
        const g = sg.gruppi.find(g => g.id === esc.target_id);
        if (g) return g.turni.map(t => ({ id: t.id, label: t.sigla }));
      }
      return [];
    }
    if (esc.tipo === 'sovragruppo') {
      const sg = sgs.find(sg => sg.id === esc.target_id);
      if (!sg) return [];
      const result = [];
      for (const g of sg.gruppi) {
        result.push({ id: g.id, label: g.sigla, tipo: 'gruppo' });
        for (const t of g.turni) {
          result.push({ id: t.id, label: `  ${t.sigla}`, tipo: 'turno' });
        }
      }
      return result;
    }
    return [];
  }

  async function etPresetToggleEccezione(esc, childId) {
    const ecc = esc.eccezioni ?? [];
    const nuove = ecc.includes(childId)
      ? ecc.filter(e => e !== childId)
      : [...ecc, childId];
    await adminApi.updEsclTurno(editPreset.id, esc.id, nuove);
    const re = await adminApi.getEsclusioni_turno(editPreset.id);
    etPresetData = re.esclusioni ?? [];
  }

  function _etPresetLabel(esc) {
    const targets = _etPresetTargets(esc.tipo);
    const found = targets.find(t => t.id === esc.target_id);
    return found?.label ?? `id:${esc.target_id}`;
  }

  async function etPresetAggiungi() {
    if (!editPreset || !etPresetForm.user_id || !etPresetForm.target_id) return;
    etPresetLoading = true;
    const r = await adminApi.addEsclTurno(editPreset.id, {
      user_id: etPresetForm.user_id,
      tipo: etPresetForm.tipo,
      target_id: etPresetForm.target_id,
    });
    etPresetLoading = false;
    if (r.ok) {
      const re = await adminApi.getEsclusioni_turno(editPreset.id);
      etPresetData = re.esclusioni ?? [];
      etPresetForm = { ...etPresetForm, target_id: null };
    }
  }

  async function etPresetRimuovi(esc) {
    if (!editPreset) return;
    await adminApi.delEsclTurno(editPreset.id, esc.id);
    const re = await adminApi.getEsclusioni_turno(editPreset.id);
    etPresetData = re.esclusioni ?? [];
  }

  // ── Appearance ────────────────────────────────────────────────

  async function appCarica(pid) {
    const r = await adminApi.getAppearance(pid);
    appearance = r.ok ? { ...APP_DEFAULT, ...r.appearance } : { ...APP_DEFAULT };
    appDirty = false;
  }

  async function appSalva() {
    if (!editPreset) return;
    appLoading = true;
    const r = await adminApi.salvaAppearance(editPreset.id, appearance);
    appLoading = false;
    if (r.ok) { appDirty = false; setMsg('stru', 'Appearance salvata.'); }
    else setMsg('stru', r.errore || 'Errore salvataggio appearance.', false);
  }

  async function salvaPreset() {
    const r = await adminApi.salvaStrutturaPreset(editPreset.id, {
      struttura: editPreset.struttura,
    });
    if (r.ok) {
      editPreset.struttura = r.struttura; // aggiorna con IDs reali dal DB
      presets = (await adminApi.getPresets()).presets ?? [];
      setMsg('stru', 'Preset salvato.');
    } else setMsg('stru', r.errore, false);
  }
  // ── JSON manipulation (tutto locale, salvaPreset per persistere) ──

  function addSg() {
    if (!nuovoSg.nome.trim()) return;
    const sigla = nuovoSg.sigla.trim() || toSigla(nuovoSg.nome);
    const id = nextId();
    editPreset.struttura = [...editPreset.struttura, { id, sigla, nome: nuovoSg.nome.trim(), ambito: nuovoSg.ambito.trim(), gruppi: [] }];
    nuovoSg = { nome: '', sigla: '', ambito: '' };
    showAddSg = false;
  }
  function delSg(sgId) {
    editPreset.struttura = editPreset.struttura.filter(sg => sg.id !== sgId);
    editPreset = { ...editPreset };
    if (editingNode?.startsWith(`sg:${sgId}`) || editingNode?.startsWith(`g:${sgId}`) || editingNode?.startsWith(`t:${sgId}`)) editingNode = null;
  }

  function duplicaGruppo(sgId, g) {
    const sg = editPreset.struttura.find(s => String(s.id) === String(sgId));
    if (!sg) return;
    const nuovoNome = g.nome + ' (copia)';
    const nuovaSigla = toSigla(nuovoNome) + '_' + sg.sigla;
    const nuoviTurni = g.turni.map(t => {
      const nuovaTSigla = autoSigla
        ? `${toSigla(t.nome)}_${nuovaSigla}`
        : t.sigla;
      return { ...t, id: nextId(), sigla: nuovaTSigla };
    });
    editPreset.struttura = editPreset.struttura.map(s =>
      String(s.id) !== String(sgId) ? s :
      { ...s, gruppi: [...s.gruppi, {
          id: nextId(), sigla: nuovaSigla, nome: nuovoNome,
          flag_id: g.flag_id, flag_nome: g.flag_nome, turni: nuoviTurni
        }] }
    );
  }

  function addGruppo(sgId) {
    if (!nuovoGruppo.nome.trim()) return;
    const sigla = nuovoGruppo.sigla.trim() || toSigla(nuovoGruppo.nome);
    const id = nextId();
    const fl = flagTurno.find(f => f.id === nuovoGruppo.flag_id);
    editPreset.struttura = editPreset.struttura.map(sg =>
      sg.id !== sgId ? sg :
      { ...sg, gruppi: [...sg.gruppi, {
          id, sigla, nome: nuovoGruppo.nome.trim(),
          flag_id: nuovoGruppo.flag_id,
          flag_nome: fl?.nome ?? null,
          turni: []
        }] }
    );
    nuovoGruppo = { nome: '', sigla: '', flag_id: flagTurno.find(f => f.mostra_in_struttura)?.id ?? null };
    activeAddGruppo = null;
  }
  function delGruppo(sgId, gId) {
    editPreset.struttura = editPreset.struttura.map(sg =>
      sg.id !== sgId ? sg : { ...sg, gruppi: sg.gruppi.filter(g => g.id !== gId) }
    );
    editPreset = { ...editPreset };
  }

  function addTurno(sgId, gId) {
    if (!nuovoTurno.nome.trim()) return;
    const sg = editPreset.struttura.find(s => s.id === sgId);
    const g = sg?.gruppi.find(gr => gr.id === gId);
    if (!sg || !g) return;
    const id = nextId();
    const sigla = turnoSigla(nuovoTurno.nome, g);
    const tqIds = nuovoTurno.tipiQualitativoIds || [];
    editPreset.struttura = editPreset.struttura.map(s =>
      s.id !== sgId ? s : { ...s, gruppi: s.gruppi.map(gr =>
        gr.id !== gId ? gr :
        { ...gr, turni: [...gr.turni, { id, sigla, nome: nuovoTurno.nome.trim(), tipi_qualitativi: tqIds, priorita_solver: 'automatico', peso_priorita_solver: 50, apri_festivi: 0, apri_superfestivi: 0, is_disabled: 0, is_hidden: 0 }] }
      )}
    );
    nuovoTurno = { nome: '', tipiQualitativoIds: [] };
    activeAddTurno = null;
  }
  function delTurno(sgId, gId, tId) {
    editPreset.struttura = editPreset.struttura.map(s =>
      s.id !== sgId ? s : { ...s, gruppi: s.gruppi.map(gr =>
        gr.id !== gId ? gr : { ...gr, turni: gr.turni.filter(t => t.id !== tId) }
      )}
    );
    editPreset = { ...editPreset };
  }

  // Inline editing
  let editFocus = 'nome';  // 'nome' | 'sigla'

  function startEditSg(sg, focus = 'nome') {
    editFocus = focus;
    editingNode = `sg:${sg.id}`;
    editingValue = { sigla: sg.sigla, nome: sg.nome, ambito: sg.ambito ?? '' };
  }
  function startEditG(sgId, g, focus = 'nome') {
    editFocus = focus;
    editingNode = `g:${sgId}:${g.id}`;
    editingValue = { sigla: g.sigla, nome: g.nome, flag_id: g.flag_id, style: { ...(g.style ?? {}) } };
  }
  function startEditT(sgId, gId, t, focus = 'nome') {
    editFocus = focus;
    editingNode = `t:${sgId}:${gId}:${t.id}`;
    const accChecked = getAccessoChecked('turni', t.id);
    editingValue = { sigla: t.sigla, nome: t.nome, tipi_qualitativi: tqToIds(t.tipi_qualitativi),
                     priorita_solver: t.priorita_solver || 'automatico', peso_priorita_solver: t.peso_priorita_solver ?? 50,
                     apri_festivi: t.apri_festivi || 0, apri_superfestivi: t.apri_superfestivi || 0,
                     is_disabled: t.is_disabled || 0, is_hidden: t.is_hidden || 0,
                     _accessoChecked: accChecked,
                     _accessoLabel: _accessoLabelFromSet(accChecked),
                     _accessoOriginal: getAccessoChecked('turni', t.id) };
  }
  // tipi_qualitativi può essere [{id,nome},...] (dal backend) o [id,...] (locale)
  function tqToIds(arr) {
    return (arr || []).map(x => typeof x === 'object' ? x.id : x);
  }
  function toggleQualId(arr, id) {
    const ids = tqToIds(arr);
    return ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id];
  }
  function qualNomi(arr) {
    return tqToIds(arr).map(id => tipiQualitativo.find(t => t.id === id)?.nome).filter(Boolean);
  }
  function cancelEdit() { editingNode = null; }
  async function applyEdit() {
    if (!editingNode) return;
    const parts = editingNode.split(':');
    const type = parts[0];
    const sgId = parts[1];
    const gId  = parts[2];
    const tId  = parts[3];
    // Confronto robusto: converte entrambi a stringa (ID DB sono int, ID locali sono 'nX')
    const eqId = (a, b) => String(a) === String(b);
    editPreset.struttura = editPreset.struttura.map(sg => {
      if (!eqId(sg.id, sgId)) return sg;
      if (type === 'sg') {
        const oldSgSigla = sg.sigla;
        const newSgSigla = editingValue.sigla;
        const gruppi = (autoSigla && oldSgSigla !== newSgSigla)
          ? sg.gruppi.map(g => {
              const newGSigla = g.sigla.endsWith('_' + oldSgSigla)
                ? g.sigla.slice(0, -oldSgSigla.length) + newSgSigla
                : toSigla(g.nome) + '_' + newSgSigla;
              return {
                ...g,
                sigla: newGSigla,
                turni: g.turni.map(t => ({ ...t, sigla: `${toSigla(t.nome)}_${newGSigla}` }))
              };
            })
          : sg.gruppi;
        return { ...sg, sigla: newSgSigla, nome: editingValue.nome, ambito: editingValue.ambito ?? '', gruppi };
      }
      return { ...sg, gruppi: sg.gruppi.map(g => {
        if (!eqId(g.id, gId)) return g;
        if (type === 'g') {
          const fl = flagTurno.find(f => f.id === editingValue.flag_id);
          const oldGSigla = g.sigla;
          const newGSigla = editingValue.sigla;
          const turni = (autoSigla && oldGSigla !== newGSigla)
            ? g.turni.map(t => ({ ...t, sigla: `${toSigla(t.nome)}_${newGSigla}` }))
            : g.turni;
          return { ...g, sigla: newGSigla, nome: editingValue.nome,
                   flag_id: editingValue.flag_id, flag_nome: fl?.nome ?? null,
                   style: editingValue.style ?? {}, turni };
        }
        return { ...g, turni: g.turni.map(t =>
          !eqId(t.id, tId) ? t : { ...t, sigla: editingValue.sigla, nome: editingValue.nome, tipi_qualitativi: editingValue.tipi_qualitativi ?? [],
                                    priorita_solver: editingValue.priorita_solver || 'automatico', peso_priorita_solver: editingValue.peso_priorita_solver ?? 50,
                                    apri_festivi: editingValue.apri_festivi || 0, apri_superfestivi: editingValue.apri_superfestivi || 0,
                                    is_disabled: editingValue.is_disabled || 0, is_hidden: editingValue.is_hidden || 0 }
        )};
      })};
    });
    // Salva accesso manager turno se modificato (solo per turni con ID numerico = già salvati in DB)
    if (type === 't' && editingValue._accessoChecked) {
      const isDbId = typeof tId === 'number' || (typeof tId === 'string' && !tId.startsWith('n'));
      if (isDbId) {
        const orig = editingValue._accessoOriginal;
        const curr = editingValue._accessoChecked;
        const changed = orig.size !== curr.size || [...orig].some(id => !curr.has(id)) || [...curr].some(id => !orig.has(id));
        if (changed) {
          await _salvaAccesso('turni', tId, checkedToDb(curr));
        }
      } else {
        setMsg('struttura', 'Salva prima la struttura per modificare l\'accesso manager di questo turno.', false);
      }
    }
    accessoDropdownOpen = null;
    editingNode = null;
  }
  function onEditKeydown(e) {
    if (e.key === 'Enter') applyEdit();
    if (e.key === 'Escape') cancelEdit();
  }

  // Auto-aggiorna sigla dal nome durante editing
  function syncSigla() {
    editingValue.sigla = toSigla(editingValue.nome);
  }

  // Drag-to-reorder (index-based)
  function onDragStartSg(idx) { dragItem = { type: 'sg', idx }; }
  function onDropSg(targetIdx) {
    if (!dragItem || dragItem.type !== 'sg' || dragItem.idx === targetIdx) { dragItem = null; return; }
    const arr = [...editPreset.struttura];
    const [item] = arr.splice(dragItem.idx, 1);
    arr.splice(targetIdx, 0, item);
    editPreset.struttura = arr;
    dragItem = null;
  }
  function onDragStartGruppo(sgId, idx) { dragItem = { type: 'g', sgId, idx }; }
  function onDropGruppo(sgId, targetIdx) {
    if (!dragItem || dragItem.type !== 'g' || dragItem.sgId !== sgId || dragItem.idx === targetIdx) { dragItem = null; return; }
    editPreset.struttura = editPreset.struttura.map(sg => {
      if (sg.id !== sgId) return sg;
      const arr = [...sg.gruppi];
      const [item] = arr.splice(dragItem.idx, 1);
      arr.splice(targetIdx, 0, item);
      return { ...sg, gruppi: arr };
    });
    dragItem = null;
  }
  function onDragStartTurno(sgId, gId, idx) { dragItem = { type: 't', sgId, gId, idx }; }
  function onDropTurno(sgId, gId, targetIdx) {
    if (!dragItem || dragItem.type !== 't' || dragItem.sgId !== sgId || dragItem.gId !== gId || dragItem.idx === targetIdx) { dragItem = null; return; }
    editPreset.struttura = editPreset.struttura.map(sg => {
      if (sg.id !== sgId) return sg;
      return { ...sg, gruppi: sg.gruppi.map(g => {
        if (g.id !== gId) return g;
        const arr = [...g.turni];
        const [item] = arr.splice(dragItem.idx, 1);
        arr.splice(targetIdx, 0, item);
        return { ...g, turni: arr };
      })};
    });
    dragItem = null;
  }

  // ── Config ─────────────────────────────────────────────────────
  async function salvaConfig() {
    const r = await adminApi.setConfig(config);
    if (r.ok) setMsg('cfg', 'Configurazione salvata.');
    else setMsg('cfg', r.errore, false);
  }
  async function salvaConteggi() {
    config['conteggi_context'] = JSON.stringify(conteggiConfig);
    const r = await adminApi.setConfig({ conteggi_context: JSON.stringify(conteggiConfig) });
    if (r.ok) setMsg('cfg', 'Conteggi salvati.');
    else setMsg('cfg', r.errore, false);
  }
  // Stato iniziale del form conteggio: una sola definizione.
  function conteggioVuoto() {
    return { id: '', label: '', tipo: 'fascia', flag_nome: '', ref_id: null,
             giorno_settimana: null, negato: false, attivo: true };
  }

  function addConteggio() {
    if (!nuovoConteggio.id.trim() || !nuovoConteggio.label.trim()) return;
    // Senza un riferimento il conteggio non conterebbe nulla.
    const haRiferimento = nuovoConteggio.tipo === 'tipologia'
      ? nuovoConteggio.ref_id != null
      : !!nuovoConteggio.flag_nome;
    if (!haRiferimento) { setMsg('cfg', 'Scegli cosa deve contare.', false); return; }

    conteggiConfig = [...conteggiConfig, { ...nuovoConteggio }];
    nuovoConteggio = conteggioVuoto();
    salvaConteggi();
  }
  function removeConteggio(idx) {
    conteggiConfig = conteggiConfig.filter((_, i) => i !== idx);
    salvaConteggi();
  }
  function toggleConteggio(idx) {
    conteggiConfig = conteggiConfig.map((c, i) => i === idx ? { ...c, attivo: !c.attivo } : c);
    salvaConteggi();
  }
  function salvaEditConteggio(obj) {
    const { _idx, ...fields } = obj;
    conteggiConfig = conteggiConfig.map((c, i) => i === _idx ? fields : c);
    salvaConteggi();
  }

  // ── Vincoli Solver — stato e logica gestiti da VincoliSolver.svelte ──

  function badgeStato(stato) {
    return { APERTO:'success', CHIUSO:'primary' }[stato] ?? 'secondary';
  }

  // ── Context menu formattazione struttura ─────────────────────────
  // ── Anteprima griglia ──────────────────────────────────────────
  let showPreview = true;
  let previewWidth = 50;  // percentuale (50%)
  let resizingPreview = false;

  function onPreviewResizeStart(e) {
    e.preventDefault();
    resizingPreview = true;
    const splitEl = e.target.closest('.struttura-split');
    if (!splitEl) return;
    function onMove(ev) {
      const rect = splitEl.getBoundingClientRect();
      const pct = ((ev.clientX - rect.left) / rect.width) * 100;
      previewWidth = Math.max(20, Math.min(70, 100 - pct));
    }
    function onUp() {
      resizingPreview = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  let ctxMenuStru = null;   // { x, y, tipo: 'sg'|'gruppo', item }
  let ctxStyleSnapshot = null;  // snapshot degli stili all'apertura (per rollback)
  let styleUndoCount = 0;       // contatore undo disponibili

  function _snapshotStyles(tipo, item) {
    if (tipo === 'sg') {
      return {
        itemStyle: JSON.parse(JSON.stringify(item.style ?? {})),
        childStyles: (item.gruppi ?? []).map(g => JSON.parse(JSON.stringify(g.style ?? {}))),
        childTurniStyles: (item.gruppi ?? []).map(g =>
          (g.turni ?? []).map(t => JSON.parse(JSON.stringify(t.style ?? {})))
        )
      };
    }
    if (tipo === 'gruppo') {
      return {
        itemStyle: JSON.parse(JSON.stringify(item.style ?? {})),
        turniStyles: (item.turni ?? []).map(t => JSON.parse(JSON.stringify(t.style ?? {})))
      };
    }
    return {
      itemStyle: JSON.parse(JSON.stringify(item.style ?? {})),
      turniStyles: (item.turni ?? []).map(t => JSON.parse(JSON.stringify(t.style ?? {})))
    };
  }

  function onSgCtxMenu(e, sg) {
    e.preventDefault();
    ctxStyleSnapshot = _snapshotStyles('sg', sg);
    ctxMenuStru = { x: e.clientX, y: e.clientY, tipo: 'sg', item: sg };
  }
  function onGruppoCtxMenu(e, g) {
    e.preventDefault();
    ctxStyleSnapshot = _snapshotStyles('gruppo', g);
    ctxMenuStru = { x: e.clientX, y: e.clientY, tipo: 'gruppo', item: g };
  }

  function closeCtxMenuStru() {
    // Rollback: ripristina stili dallo snapshot
    if (ctxStyleSnapshot && ctxMenuStru) {
      const item = ctxMenuStru.item;
      item.style = ctxStyleSnapshot.itemStyle;
      if (ctxMenuStru.tipo === 'sg') {
        (item.gruppi ?? []).forEach((g, i) => {
          if (ctxStyleSnapshot.childStyles?.[i]) g.style = ctxStyleSnapshot.childStyles[i];
          (g.turni ?? []).forEach((t, j) => {
            if (ctxStyleSnapshot.childTurniStyles?.[i]?.[j]) t.style = ctxStyleSnapshot.childTurniStyles[i][j];
          });
        });
      } else if (ctxMenuStru.tipo === 'gruppo') {
        (item.turni ?? []).forEach((t, j) => {
          if (ctxStyleSnapshot.turniStyles?.[j]) t.style = ctxStyleSnapshot.turniStyles[j];
        });
      }
      editPreset = { ...editPreset };
    }
    ctxMenuStru = null;
    ctxStyleSnapshot = null;
  }

  async function applicaCtxStruStyle() {
    if (!ctxMenuStru || !ctxStyleSnapshot || !editPreset?.id) return;
    const item = ctxMenuStru.item;
    const tipo = ctxMenuStru.tipo;
    const items = [];

    if (tipo === 'sg') {
      items.push({
        tipo: 'sg', id: item.id, tab: 'separatore',
        style_before: JSON.parse(JSON.stringify(ctxStyleSnapshot.itemStyle)),
        style_after: JSON.parse(JSON.stringify(item.style ?? {}))
      });
      (item.gruppi ?? []).forEach((g, i) => {
        items.push({
          tipo: 'gruppo', id: g.id, tab: 'colonna',
          style_before: JSON.parse(JSON.stringify(ctxStyleSnapshot.childStyles?.[i] ?? {})),
          style_after: JSON.parse(JSON.stringify(g.style ?? {}))
        });
        // Includi turni modificati dalla cascata colonna
        (g.turni ?? []).forEach((t, j) => {
          const before = ctxStyleSnapshot.childTurniStyles?.[i]?.[j] ?? {};
          const after = t.style ?? {};
          if (JSON.stringify(before) !== JSON.stringify(after)) {
            items.push({
              tipo: 'turno', id: t.id, tab: 'separatore',
              style_before: JSON.parse(JSON.stringify(before)),
              style_after: JSON.parse(JSON.stringify(after))
            });
          }
        });
      });
    } else if (tipo === 'gruppo') {
      // Detect if turni were also modified (colonna cascade)
      const turniChanged = (item.turni ?? []).some((t, j) => {
        const before = ctxStyleSnapshot.turniStyles?.[j] ?? {};
        return JSON.stringify(before) !== JSON.stringify(t.style ?? {});
      });
      items.push({
        tipo: 'gruppo', id: item.id, tab: turniChanged ? 'colonna' : 'separatore',
        style_before: JSON.parse(JSON.stringify(ctxStyleSnapshot.itemStyle)),
        style_after: JSON.parse(JSON.stringify(item.style ?? {}))
      });
      // Includi turni modificati dalla cascata colonna
      (item.turni ?? []).forEach((t, j) => {
        const before = ctxStyleSnapshot.turniStyles?.[j] ?? {};
        const after = t.style ?? {};
        if (JSON.stringify(before) !== JSON.stringify(after)) {
          items.push({
            tipo: 'turno', id: t.id, tab: 'separatore',
            style_before: JSON.parse(JSON.stringify(before)),
            style_after: JSON.parse(JSON.stringify(after))
          });
        }
      });
    }

    const r = await adminApi.salvaStyleItem(editPreset.id, items);
    if (r.ok) styleUndoCount = r.undo_count;

    ctxMenuStru = null;
    ctxStyleSnapshot = null;
  }

  async function applicaATuttiPreset(gruppo) {
    if (!editPreset?.id) return;
    const items = [];
    for (const sg of (editPreset.struttura ?? [])) {
      for (const g of (sg.gruppi ?? [])) {
        const isCurrentItem = (g === gruppo && ctxStyleSnapshot);
        const before = isCurrentItem ? { ...ctxStyleSnapshot.itemStyle } : { ...(g.style ?? {}) };
        const after = { ...(gruppo.style ?? {}) };
        if (JSON.stringify(before) !== JSON.stringify(after)) {
          items.push({
            tipo: 'gruppo', id: g.id, tab: 'separatore',
            style_before: before, style_after: after
          });
        }
        g.style = { ...after };
      }
    }
    editPreset = { ...editPreset };
    if (items.length > 0) {
      const r = await adminApi.salvaStyleItem(editPreset.id, items);
      if (r.ok) styleUndoCount = r.undo_count;
    }
    ctxMenuStru = null;
    ctxStyleSnapshot = null;
  }

  async function undoPresetStyle() {
    if (!editPreset?.id) return;
    const r = await adminApi.undoStyle(editPreset.id);
    if (r.ok) {
      styleUndoCount = r.undo_count;
      // Ricarica struttura per riflettere i cambiamenti
      const sr = await adminApi.getStrutturaPreset(editPreset.id);
      if (sr.ok) editPreset = { ...editPreset, struttura: sr.struttura };
    }
  }

  function setCtxItemStyle(prop, value) {
    if (!ctxMenuStru) return;
    const item = ctxMenuStru.item;
    item.style = { ...(item.style ?? {}), [prop]: value };
    editPreset = { ...editPreset }; // trigger reactivity
  }

  function setCtxGruppoColStyle(prop, value) {
    if (!ctxMenuStru) return;
    const item = ctxMenuStru.item;
    const colStyle = { ...(item.style?.['--columnStyle'] ?? {}), [prop]: value };
    item.style = { ...(item.style ?? {}), '--columnStyle': colStyle };
    // Rimuovi la stessa proprietà dai turni figli (la colonna sovrascrive)
    for (const t of (item.turni ?? [])) {
      if (t.style && prop in t.style) {
        const { [prop]: _, ...rest } = t.style;
        t.style = rest;
      }
    }
    editPreset = { ...editPreset };
  }

  function setCtxSgColStyle(prop, value) {
    if (!ctxMenuStru) return;
    const sg = ctxMenuStru.item;
    // Applica a cascata a tutti i gruppi figli
    for (const g of (sg.gruppi ?? [])) {
      const colStyle = { ...(g.style?.['--columnStyle'] ?? {}), [prop]: value };
      g.style = { ...(g.style ?? {}), '--columnStyle': colStyle };
      // Rimuovi la stessa proprietà dai turni figli (la colonna sovrascrive)
      for (const t of (g.turni ?? [])) {
        if (t.style && prop in t.style) {
          const { [prop]: _, ...rest } = t.style;
          t.style = rest;
        }
      }
    }
    editPreset = { ...editPreset };
  }

  function toggleCtxRepeatName() {
    if (!ctxMenuStru) return;
    const item = ctxMenuStru.item;
    const current = item.style?.['--repeatName'] ?? false;
    item.style = { ...(item.style ?? {}), '--repeatName': !current };
    editPreset = { ...editPreset };
  }

  // Handler unificato per StyleContextMenu onset(prop, value, tab)
  function onCtxSetProp(prop, value, tab) {
    if (!ctxMenuStru) return;
    const isSg = ctxMenuStru.tipo === 'sg';
    if (tab === 'colonna') {
      isSg ? setCtxSgColStyle(prop, value) : setCtxGruppoColStyle(prop, value);
    } else {
      setCtxItemStyle(prop, value);
    }
  }

  function onCtxBorderSet(prop, value) {
    if (!ctxMenuStru) return;
    if (prop === '--repeatName') {
      toggleCtxRepeatName();
    } else {
      setCtxItemStyle(prop, value);
    }
  }
</script>

<svelte:window on:click={e => {
  if (ctxMenuStru && !e.target.closest('.scm-menu')) closeCtxMenuStru();
  if (accessoDropdownOpen && !e.target.closest('.accesso-dropdown') && !e.target.closest('[data-accesso-toggle]')) accessoDropdownOpen = null;
}} on:mousedown={e => {
  // Click-outside chiude righe in editing
  // Salta se click su riga editing, riga cliccabile, pulsante elimina, o albero struttura
  if (e.target.closest('.table-warning') || e.target.closest('.editable-row')
      || e.target.closest('.del-btn') || e.target.closest('.struttura-list')) return;
  editingFlag = null;
  editingRegola = null; editingUtente = null;
  editPresetOttId = null; editingNode = null;
}} on:keydown={e => {
  if (e.key === 'Escape') { editingFlag = null; editingRegola = null; editingUtente = null; editPresetOttId = null; editingNode = null; }
}} />

<div class="container-fluid py-3">
  <h5 class="fw-bold mb-3">
    <i class="bi bi-gear-fill me-2 text-primary"></i>
    {$userStore?.role === 'manager' ? 'Gestione' : 'Amministrazione'}
  </h5>

  <!-- Tabs — manager vede solo Calendari + Struttura turni -->
  <ul class="nav nav-tabs mb-3">
    {#each (
      $userStore?.role === 'manager'
        ? [['calendari','calendar3','Calendari',false],
           ['struttura','compass','Configurazione guidata',false]]
        : [['calendari','calendar3','Calendari',false],
           ['utenti','people-fill','Utenti',false],
           ['configurazione','sliders','Configurazione manuale',false],
           ['struttura','compass','Configurazione guidata',false],
           ['strutturaturni','diagram-3','Struttura turni',true]]
    ) as [k,ico,lbl,vuoleStruttura]}
      {@const spenta = vuoleStruttura && !strutturaDelTenant}
      <li class="nav-item">
        <!-- Senza una configurazione globale non c'e' struttura da
             modificare: la scheda resta sbiadita invece di aprirsi vuota. -->
        <button class="nav-link {tab===k?'active':''}" disabled={spenta}
                title={spenta ? 'Prima crea la configurazione globale' : null}
                on:click={() => tab=k}>
          <i class="bi bi-{ico} me-1"></i>{lbl}
        </button>
      </li>
    {/each}
  </ul>

  <!-- ═══════════════ TAB CALENDARI ═══════════════ -->
  {#if tab === 'calendari'}
    {#if msgCal}<div class="alert py-2 small {msgCal.startsWith('✓')?'alert-success':'alert-danger'}">{msgCal}</div>{/if}

    {#if $userStore?.role !== 'manager' || $userStore?.puo_gestire_calendari}
    <ImportDesiderata onimportati={async () => {
      calendari = (await adminApi.getCalendari()).calendari ?? [];
    }} />

    <div class="card mb-3">
      <div class="card-header fw-semibold">Crea nuovo calendario</div>
      <div class="card-body">
        <div class="row g-2 align-items-end">
          <div class="col-auto">
            <label class="form-label small">Mese</label>
            <select class="form-select form-select-sm" bind:value={nuovoCal.mese}>
              <option value="">— mese —</option>
              {#each NOMI_MESI.slice(1) as m, i}
                <option value={i+1}>{m}</option>
              {/each}
            </select>
          </div>
          <div class="col-auto">
            <label class="form-label small">Anno</label>
            <input class="form-control form-control-sm" type="number" bind:value={nuovoCal.anno} style="width:90px" />
          </div>
          <!-- Nessuna scelta di struttura: l'organizzazione ne ha una sola,
               ed e' quella della configurazione. -->
          <div class="col-auto">
            <div class="form-label small">Struttura turni</div>
            <div class="form-control-plaintext form-control-sm py-0">
              {strutturaDelTenant?.nome ?? '— nessuna: creala dalla configurazione —'}
            </div>
          </div>
          <div class="col-auto">
            <button class="btn btn-primary btn-sm" on:click={creaCal}>
              <i class="bi bi-plus-lg me-1"></i>Crea
            </button>
          </div>
        </div>
      </div>
    </div>
    {/if}

    <div class="table-responsive">
      <table class="table table-sm table-hover align-middle">
        <thead class="table-light">
          <tr>
            <th>Periodo</th><th>Stato</th><th>Desiderata</th><th style="min-width:120px">Azioni</th>
          </tr>
        </thead>
        <tbody>
          {#each calendari.filter(c => (c.tipo || 'programmato') === 'programmato') as c}
            <tr>
              <td class="fw-semibold">{NOMI_MESI[c.mese]} {c.anno}</td>
              <td>
                <span class="badge bg-{badgeStato(c.stato)}">{c.stato}</span>
                {#if c.versione > 1}<span class="badge bg-light text-dark ms-1">v{c.versione}</span>{/if}
              </td>
              <td>
                <div class="d-flex gap-1 flex-wrap">
                {#if c.desiderata_congelati}
                  <span class="badge bg-danger align-self-center"><i class="bi bi-lock-fill me-1"></i>Congelati</span>
                  <button class="btn btn-outline-secondary btn-sm py-0" on:click={() => scongelaDesiderata(c.id)}>
                    <i class="bi bi-unlock me-1"></i>Scongela
                  </button>
                {:else}
                  <button class="btn btn-outline-warning btn-sm py-0" on:click={() => congelaDesiderata(c.id)}>
                    <i class="bi bi-snow me-1"></i>Congela
                  </button>
                {/if}
                </div>
              </td>
              <td><div class="d-flex gap-1 flex-wrap">
                {#if c.stato === 'APERTO'}
                  <button class="btn btn-outline-primary btn-sm py-0" on:click={() => avanzaStato(c.id, 'CHIUSO')}>
                    <i class="bi bi-check2-circle me-1"></i>Chiudi
                  </button>
                {:else if c.stato === 'CHIUSO'}
                  <button class="btn btn-outline-warning btn-sm py-0" on:click={() => riapriCalendario(c.id)}>
                    <i class="bi bi-arrow-counterclockwise me-1"></i>Riapri
                  </button>
                {/if}
                {#if c.stato !== 'APERTO'}
                <button class="btn btn-outline-success btn-sm py-0" on:click={() => exportApi.turni(c.id)}>
                  <i class="bi bi-file-earmark-excel"></i>
                </button>
                <button class="btn btn-outline-info btn-sm py-0" on:click={() => exportApi.ore(c.id)}>
                  <i class="bi bi-file-earmark-bar-graph"></i>
                </button>
                {/if}
                <button class="btn btn-outline-warning btn-sm py-0" title="Riazzera assegnazioni"
                        on:click={() => riazzeraCalendario(c.id, c.mese, c.anno)}>
                  <i class="bi bi-arrow-counterclockwise"></i>
                </button>
                {#if $userStore?.role !== 'manager' || $userStore?.puo_gestire_calendari}
                <button class="btn btn-outline-danger btn-sm py-0" title="Elimina calendario"
                        on:click={() => eliminaCalendario(c.id, c.mese, c.anno)}>
                  <i class="bi bi-trash"></i>
                </button>
                {/if}
                {#if c.stato === 'APERTO'}
                <select class="form-select form-select-sm d-inline-block py-0" style="width:120px;font-size:.75rem"
                        bind:value={ricaricaPresetId[c.id]}
                        on:change={() => {}}>
                  <option value={undefined}>— preset —</option>
                  {#each presets as p}
                    <option value={p.id}>{p.nome}</option>
                  {/each}
                </select>
                <button class="btn btn-outline-primary btn-sm py-0" title="Ricarica struttura e configurazione da preset"
                        on:click={() => ricaricaStruttura(c.id, c.mese, c.anno, ricaricaPresetId[c.id])}>
                  <i class="bi bi-arrow-repeat"></i>
                </button>
                {/if}
              </div></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <!-- Export annuale -->
    <div class="card mt-3">
      <div class="card-header fw-semibold d-flex align-items-center gap-2">
        <i class="bi bi-file-earmark-bar-graph"></i>Export ore annuali
        <input type="number" class="form-control form-control-sm" style="width:90px"
               bind:value={annoExport} on:change={resetEsclusi} min="2020" max="2099" />
      </div>
      <div class="card-body py-2">
        {#if calendariApertiAnno.length > 0}
          <p class="small text-muted mb-2">Deseleziona i calendari aperti da escludere dal conteggio:</p>
          <div class="d-flex flex-wrap gap-3 mb-2">
            {#each calendariApertiAnno as c}
              <div class="form-check">
                <input class="form-check-input" type="checkbox" id="exc-{c.id}"
                       checked={!esclusiAnnuale[c.id]}
                       on:change={() => esclusiAnnuale[c.id] = !esclusiAnnuale[c.id]} />
                <label class="form-check-label small" for="exc-{c.id}">
                  {NOMI_MESI[c.mese]}
                  <span class="badge bg-success ms-1">APERTO</span>
                </label>
              </div>
            {/each}
          </div>
        {/if}
        {#if calendariAnno.length === 0}
          <p class="small text-muted mb-0">Nessun calendario per il {annoExport}.</p>
        {:else}
          <button class="btn btn-outline-primary btn-sm" on:click={downloadAnnuale}>
            <i class="bi bi-download me-1"></i>Scarica Excel {annoExport}
            {#if idsEsclusi.length > 0}
              <span class="badge bg-warning text-dark ms-1">{calendariApertiAnno.length - idsEsclusi.length}/{calendariApertiAnno.length} aperti inclusi</span>
            {/if}
          </button>
        {/if}
      </div>
    </div>

  <!-- ═══════════════ TAB UTENTI ═══════════════ -->
  {:else if tab === 'utenti'}
    {#if msgUtenti}<div class="alert py-2 small {msgUtenti.startsWith('✓')?'alert-success':'alert-danger'}">{msgUtenti}</div>{/if}

    <div class="card mb-3">
      <div class="card-header fw-semibold">Crea utente</div>
      <div class="card-body">
        <div class="row g-2 align-items-end">
          <div class="col"><label class="form-label small">Username</label>
            <input class="form-control form-control-sm" bind:value={nuovoUtente.username} /></div>
          <div class="col"><label class="form-label small">Password</label>
            <input class="form-control form-control-sm" type="password" bind:value={nuovoUtente.password} /></div>
          <div class="col-auto"><label class="form-label small">Ruolo</label>
            <select class="form-select form-select-sm" bind:value={nuovoUtente.role}>
              <option value="basic">lavoratore</option>
              <option value="manager">{$etichettaManager.toLowerCase()}</option>
              <option value="admin">amministratore</option>
            </select></div>
          <div class="col-auto"><label class="form-label small">Sigla</label>
            <input class="form-control form-control-sm" bind:value={nuovoUtente.sigla} style="width:80px" /></div>
          <div class="col-auto"><label class="form-label small">{$etichettaStruttura.singolare}</label>
            <select class="form-select form-select-sm" bind:value={nuovoUtente.sovragruppo_id} style="min-width:140px">
              <option value={null}>— Nessuno —</option>
              {#each sovragruppiDisponibili as sg (sg.id)}
                <option value={sg.id}>{sg.sigla} — {sg.nome}</option>
              {/each}
            </select></div>
          <div class="col-auto">
            <button class="btn btn-primary btn-sm" on:click={createUser}>
              <i class="bi bi-person-plus me-1"></i>Crea
            </button>
          </div>
        </div>
      </div>
    </div>

    {#if hasOrfani}
      <div class="alert alert-warning py-2 px-3 d-flex align-items-center gap-2 mb-2" style="font-size:.8rem">
        <i class="bi bi-exclamation-triangle-fill"></i>
        <div class="flex-grow-1">
          <strong>Riferimenti orfani nella gestione accessi.</strong>
          {#if accessoOrfani.turni.length > 0}
            {accessoOrfani.turni.length} turni eliminati dalla struttura.
          {/if}
          {#if accessoOrfani.utenti.length > 0}
            {accessoOrfani.utenti.length} utenti non più attivi.
          {/if}
          {#if accessoOrfani.managers.length > 0}
            {accessoOrfani.managers.length} manager non più attivi.
          {/if}
          Ricontrollare la gestione accessi.
        </div>
        <button class="btn btn-warning btn-sm py-0 px-2" style="font-size:.75rem"
                on:click={pulisciOrfani} disabled={pulisciaOrfaniLoading}>
          {#if pulisciaOrfaniLoading}
            <span class="spinner-border spinner-border-sm me-1"></span>
          {/if}
          Pulisci
        </button>
      </div>
    {/if}

    <div class="d-flex align-items-center gap-3 mb-2 p-2 border rounded bg-light flex-wrap">
      <label class="form-check mb-0">
        <input type="checkbox" class="form-check-input"
               checked={bulkAllSelected}
               on:change={() => { bulkSelectedUsers = bulkAllSelected ? new Set() : new Set(bulkBasicUsers.map(u => u.id)); }} />
        <span class="form-check-label small fw-semibold">Seleziona tutti</span>
      </label>
      <span class="small text-muted">{bulkSelectedUsers.size} selezionati</span>

      <div class="d-flex align-items-center gap-1">
        <label class="small mb-0">Campo</label>
        <select class="form-select form-select-sm" style="width:auto" bind:value={bulkCampo}>
          <option value="sovragruppo_id">{$etichettaStruttura.singolare}</option>
          <option value="is_active">Attivo</option>
          <option value="escluso_turni">Escluso turni</option>
          <option value="puo_gestire_calendari">Gestione calendari</option>
          <option value="role">Ruolo</option>
          <option value="offusca">Privacy desiderata</option>
          {#if accessoManagerData && accessoManagers.length > 0}
            <option value="accesso_manager">Accesso manager</option>
          {/if}
        </select>
      </div>

      <div class="d-flex align-items-center gap-1">
        <label class="small mb-0">Valore</label>
        {#if bulkCampo === 'sovragruppo_id'}
          <select class="form-select form-select-sm" style="width:auto" bind:value={bulkValore}>
            <option value={null}>— Nessuno —</option>
            {#each sovragruppiDisponibili as sg (sg.id)}
              <option value={sg.id}>{sg.sigla} — {sg.nome}</option>
            {/each}
          </select>
        {:else if bulkCampo === 'role'}
          <select class="form-select form-select-sm" style="width:auto" bind:value={bulkValore}>
            <option value="basic">lavoratore</option>
            <option value="manager">{$etichettaManager.toLowerCase()}</option>
            <option value="admin">amministratore</option>
          </select>
        {:else if bulkCampo === 'offusca'}
          <select class="form-select form-select-sm" style="width:auto" bind:value={bulkValore}>
            <option value={0}>Nessuna</option>
            <option value={1}>Offusca assenze (X)</option>
            <option value={2}>Offusca tutto</option>
          </select>
        {:else if bulkCampo === 'accesso_manager'}
          <AccessoDropdown
            managers={accessoManagers}
            checked={bulkManagerChecked}
            isOpen={accessoDropdownOpen === 'bulk_utenti'}
            label={bulkManagerLabel}
            minWidth="60px"
            ontoggleopen={() => toggleAccessoDropdown('bulk_utenti')}
            onchange={s => { bulkManagerChecked = s; bulkManagerLabel = _accessoLabelFromSet(s); }}
          />
        {:else}
          <!-- Campi booleani (is_active / escluso_turni / puo_gestire_calendari) -->
          <select class="form-select form-select-sm" style="width:auto" bind:value={bulkValore}>
            <option value={1}>Sì</option>
            <option value={0}>No</option>
          </select>
        {/if}
      </div>

      <button class="btn btn-primary btn-sm" disabled={bulkSelectedUsers.size === 0 || bulkLoading}
              on:click={applicaBulkUtenti}>
        {#if bulkLoading}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
        <i class="bi bi-check2-all me-1"></i>Applica
      </button>
    </div>

    <div class="table-responsive">
      <table class="table table-sm table-hover align-middle table-config table-config-fixed" style="font-size:.85rem">
        <thead class="table-light">
          <tr>
            <th style="width:30px"></th>
            <th style="width:80px">Sigla</th><th style="width:120px">Username</th><th style="width:100px">Ruolo</th><th style="width:140px">{$etichettaStruttura.singolare}</th><th style="width:85px">Attivo</th><th style="width:50px" title="Incluso nel sistema turni">Turni</th><th style="width:50px" title="Può creare/eliminare calendari">Cal.</th><th style="width:100px">Manager</th><th style="width:60px"></th>
          </tr>
        </thead>
        <tbody>
          {#each utenti as u (u.id)}
            {#if editingUtente?.id === u.id}
              <tr class="table-warning">
                <td></td>
                <td data-field="sigla"><input class="form-control form-control-sm" use:autoFocus={'sigla'} bind:value={editingUtente.sigla} style="width:80px"
                     on:keydown={editRowKeydown(salvaUtente, () => editingUtente=null)} /></td>
                <td data-field="username"><input class="form-control form-control-sm" use:autoFocus={'username'} bind:value={editingUtente.username} style="min-width:100px"
                     on:keydown={editRowKeydown(salvaUtente, () => editingUtente=null)} /></td>
                <td data-field="role">
                  <select class="form-select form-select-sm" style="width:100px" bind:value={editingUtente.role}
                          on:keydown={editRowKeydown(salvaUtente, () => editingUtente=null)}>
                    <option value="basic">lavoratore</option><option value="manager">{$etichettaManager.toLowerCase()}</option><option value="admin">amministratore</option>
                  </select>
                </td>
                <td data-field="sovragruppo_id">
                  <select class="form-select form-select-sm" style="min-width:130px" bind:value={editingUtente.sovragruppo_id}
                          on:keydown={editRowKeydown(salvaUtente, () => editingUtente=null)}>
                    <option value={null}>—</option>
                    {#each sovragruppiDisponibili as sg (sg.id)}
                      <option value={sg.id}>{sg.sigla} — {sg.nome}</option>
                    {/each}
                  </select>
                </td>
                <td>
                  <button class="btn btn-sm py-0 px-2 {editingUtente.is_active ? 'btn-success' : 'btn-danger'}"
                          on:click|stopPropagation={() => { editingUtente.is_active = editingUtente.is_active ? 0 : 1; editingUtente = editingUtente; }}>
                    {editingUtente.is_active ? 'Abilitato' : 'Disabilitato'}
                  </button>
                </td>
                <td on:click|stopPropagation>
                  <input type="checkbox" class="form-check-input" title="Incluso nel sistema turni"
                         checked={!editingUtente.escluso_turni}
                         on:change={() => { editingUtente.escluso_turni = editingUtente.escluso_turni ? 0 : 1; editingUtente = editingUtente; }} />
                </td>
                <td on:click|stopPropagation>
                  {#if editingUtente.role === 'manager' || editingUtente.role === 'admin'}
                    <input type="checkbox" class="form-check-input" title="Può gestire calendari"
                           checked={!!editingUtente.puo_gestire_calendari}
                           on:change={() => { editingUtente.puo_gestire_calendari = editingUtente.puo_gestire_calendari ? 0 : 1; editingUtente = editingUtente; }} />
                  {:else}
                    <span class="text-muted">--</span>
                  {/if}
                </td>
                <td>
                  {#if accessoManagerData && accessoManagers.length > 0}
                    <AccessoDropdown
                      managers={accessoManagers}
                      checked={editingUtente._accessoChecked || new Set()}
                      isOpen={accessoDropdownOpen === 'user_' + u.id}
                      label={editingUtente._accessoLabel || 'Tutti'}
                      showIcon={false}
                      ontoggleopen={() => toggleAccessoDropdown('user_' + u.id)}
                      onchange={s => { editingUtente._accessoChecked = s; editingUtente._accessoLabel = _accessoLabelFromSet(s); editingUtente = editingUtente; }}
                    />
                  {:else}
                    <span class="text-muted small">--</span>
                  {/if}
                </td>
                <td style="white-space:nowrap" on:click|stopPropagation>
                  <button class="btn btn-success btn-sm py-0" on:click={salvaUtente}><i class="bi bi-check-lg"></i></button>
                  <button class="btn btn-secondary btn-sm py-0" on:click={() => editingUtente=null}><i class="bi bi-x"></i></button>
                </td>
              </tr>
            {:else}
              <!-- svelte-ignore a11y-click-events-have-key-events -->
              <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
              <tr class="editable-row {u.is_active ? '' : 'text-muted'}" on:click={e => startEditFromRow(e, () => {
                const accChecked = getAccessoChecked('utenti', u.id);
                editingUtente = { ...u, password: '',
                  _accessoChecked: accChecked,
                  _accessoLabel: _accessoLabelFromSet(accChecked),
                  _accessoOriginal: getAccessoChecked('utenti', u.id) };
              })}>
                <td on:click|stopPropagation>
                  {#if u.is_active}
                    <input type="checkbox" class="form-check-input"
                           checked={bulkSelectedUsers.has(u.id)}
                           on:change={() => {
                             const s = new Set(bulkSelectedUsers);
                             if (s.has(u.id)) s.delete(u.id); else s.add(u.id);
                             bulkSelectedUsers = s;
                           }} />
                  {/if}
                </td>
                <td class="fw-bold" data-field="sigla">{u.sigla}</td>
                <td data-field="username">{u.username}</td>
                <td data-field="role"><span class="badge bg-secondary">{nomeRuolo(u.role)}</span></td>
                <td data-field="sovragruppo_id">
                  {#if u.sovragruppo_sigla}
                    <span class="badge bg-info text-dark" style="font-size:.7rem" title={u.sovragruppo_nome || ''}>{u.sovragruppo_sigla}</span>
                  {:else}
                    <span class="text-muted small">—</span>
                  {/if}
                </td>
                <td>
                  <span class="badge {u.is_active ? 'bg-success' : 'bg-danger'}" style="font-size:.7rem">
                    {u.is_active ? 'Abilitato' : 'Disabilitato'}
                  </span>
                </td>
                <td>
                  <input type="checkbox" class="form-check-input" title="Incluso nel sistema turni (modifica in edit mode)"
                         checked={!u.escluso_turni}
                         disabled />
                </td>
                <td>
                  {#if u.role === 'manager' || u.role === 'admin'}
                    <input type="checkbox" class="form-check-input" title="Può gestire calendari (modifica in edit mode)"
                           checked={!!u.puo_gestire_calendari}
                           disabled />
                  {:else}
                    <span class="text-muted">--</span>
                  {/if}
                </td>
                <td>
                  {#if accessoManagerData}
                    <span class="badge bg-light text-dark fw-normal" style="font-size:.7rem">
                      <i class="bi bi-people-fill me-1"></i>{accessoLabel('utenti', u.id, accessoVersion)}
                    </span>
                  {:else}
                    <span class="text-muted small">--</span>
                  {/if}
                </td>
                <td></td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>

  <!-- ═══════════════ TAB CONFIGURAZIONE ═══════════════ -->
  {:else if tab === 'configurazione'}
    {#if msgConfig}<div class="alert py-2 small {msgConfig.startsWith('✓')?'alert-success':'alert-danger'}">{msgConfig}</div>{/if}

    <!-- ═══ 1a. Fasce orarie ═══ -->
    <div class="card mb-4" style="max-width:1240px">
      <div class="card-header fw-semibold d-flex justify-content-between align-items-center">
        Fasce orarie dei turni
        <div class="d-flex gap-2">
          <button class="btn btn-sm btn-outline-secondary" on:click={ripristinaFlagDefault}>
            <i class="bi bi-arrow-counterclockwise me-1"></i>Ripristina default
          </button>
          <button class="btn btn-sm btn-outline-primary" on:click={() => apriNuovoFlag('lavorativo')}>
            <i class="bi bi-plus me-1"></i>Nuova fascia
          </button>
        </div>
      </div>
      <div class="card-body p-2">
        {#if showAddFlag === 'lavorativo'}
          <FlagForm bind:flag={nuovoFlag} concetti={concettiLavorativi}
                    oncreate={creaFlag} oncancel={() => showAddFlag = null} />
        {/if}
        {#if concettiLavorativi.length === 0}
          <div class="text-muted small text-center py-3">Nessuna fascia definita. Ripristina i default per abilitare la configurazione.</div>
        {:else}
          <table class="table table-sm table-hover table-config table-config-fixed mb-0" style="font-size:.85rem">
            <thead><tr>
              <th style="width:110px">Nome</th>
              <th style="width:130px">Descrizione</th>
              <th style="width:80px">Concetto</th>
              <th style="width:65px">Inizio</th>
              <th style="width:65px">Fine</th>
              <th style="width:60px" title="Pausa obbligatoria in minuti">Pausa</th>
              <th style="width:60px" title="Lavoro effettivo, senza pausa">Netta</th>
              <th style="width:60px" title="Durata totale, pausa inclusa">Ore</th>
              <th style="width:55px">Peso</th>
              <th style="width:60px">1°</th>
              <th style="width:60px">Ult.</th>
              <th style="width:90px">Tipo</th>
              <th style="width:50px" title="Mostra in struttura turni">Strutt.</th>
              <th style="width:60px"></th>
            </tr></thead>
            <tbody>
            {#each concettiLavorativi as fr (fr.id)}
              {@const figli = flagFigli(fr.id)}
              {@const espanso = !collapsedFlags.has(fr.id)}
              <FlagRow flag={fr} haFigli={figli.length > 0} {espanso}
                       bind:editing={editingFlag} {autoFocus}
                       ontogglecollapse={() => toggleCollapseFlag(fr.id)}
                       onstartedit={e => startEditFromRow(e, () => startEditFlag(fr))}
                       onsave={salvaFlag}
                       oncancel={() => editingFlag = null}
                       ondelete={() => eliminaFlag(fr.id)}
                       onaddchild={() => addChildFlag(fr)} />
              {#if espanso}
                {#each figli as fc (fc.id)}
                  <FlagRow flag={fc} figlio parentNome={fr.nome}
                           bind:editing={editingFlag} {autoFocus}
                           onstartedit={e => startEditFromRow(e, () => startEditFlag(fc))}
                           onsave={salvaFlag}
                           oncancel={() => editingFlag = null}
                           ondelete={() => eliminaFlag(fc.id)} />
                {/each}
              {/if}
            {/each}
            </tbody>
          </table>
        {/if}
      </div>
    </div>

    <!-- ═══ 1b. Assenze ═══ -->
    <div class="card mb-4" style="max-width:820px">
      <div class="card-header fw-semibold d-flex justify-content-between align-items-center">
        Assenze
        <button class="btn btn-sm btn-outline-primary" on:click={() => apriNuovoFlag('assenza')}>
          <i class="bi bi-plus me-1"></i>Nuovo tipo di assenza
        </button>
      </div>
      <div class="card-body p-2">
        <div class="form-text small mb-2">
          Un'assenza non ha orari: non è una fascia oraria, e non entra nella struttura turni.
        </div>
        {#if showAddFlag === 'assenza'}
          <FlagForm bind:flag={nuovoFlag} concetti={[]} assenza
                    oncreate={creaFlag} oncancel={() => showAddFlag = null} />
        {/if}
        {#if concettiAssenza.length === 0}
          <div class="text-muted small text-center py-3">Nessuna assenza definita.</div>
        {:else}
          <table class="table table-sm table-hover table-config table-config-fixed mb-0" style="font-size:.85rem">
            <thead><tr>
              <th style="width:110px">Nome</th>
              <th style="width:160px">Descrizione</th>
              <th style="width:80px">Concetto</th>
              <th style="width:60px" title="Ore giustificate">Ore</th>
              <th style="width:60px">1°</th>
              <th style="width:60px">Ult.</th>
              <th style="width:90px">Tipo</th>
              <th style="width:60px"></th>
            </tr></thead>
            <tbody>
            {#each concettiAssenza as fr (fr.id)}
              {@const figli = flagFigli(fr.id)}
              {@const espanso = !collapsedFlags.has(fr.id)}
              <FlagRow flag={fr} assenza haFigli={figli.length > 0} {espanso}
                       bind:editing={editingFlag} {autoFocus}
                       ontogglecollapse={() => toggleCollapseFlag(fr.id)}
                       onstartedit={e => startEditFromRow(e, () => startEditFlag(fr))}
                       onsave={salvaFlag}
                       oncancel={() => editingFlag = null}
                       ondelete={() => eliminaFlag(fr.id)} />
              {#if espanso}
                {#each figli as fc (fc.id)}
                  <FlagRow flag={fc} assenza figlio parentNome={fr.nome}
                           bind:editing={editingFlag} {autoFocus}
                           onstartedit={e => startEditFromRow(e, () => startEditFlag(fc))}
                           onsave={salvaFlag}
                           oncancel={() => editingFlag = null}
                           ondelete={() => eliminaFlag(fc.id)} />
                {/each}
              {/if}
            {/each}
            </tbody>
          </table>
        {/if}
      </div>
    </div>

    <!-- Card Tipologie turno -->
    <div class="card mb-4" style="max-width:600px">
      <div class="card-header fw-semibold d-flex justify-content-between align-items-center">
        Tipologie turno
        <button class="btn btn-sm btn-outline-primary" on:click={() => { showAddTipoQual = !showAddTipoQual; }}>
          <i class="bi bi-plus me-1"></i>Nuova tipologia
        </button>
      </div>
      <div class="card-body p-2">
        {#if showAddTipoQual}
          <div class="d-flex gap-2 mb-2 align-items-center flex-wrap">
            <input class="form-control form-control-sm" use:focusOnMount placeholder="Nome" bind:value={nuovoTipoQual.nome} style="width:100px"
                   on:keydown={e => e.key === 'Enter' && creaTipoQual()} />
            <input class="form-control form-control-sm" placeholder="Descrizione" bind:value={nuovoTipoQual.descrizione} style="width:150px"
                   on:keydown={e => e.key === 'Enter' && creaTipoQual()} />
            <input class="form-control form-control-sm" type="number" step="5" min="0" placeholder="Carico" bind:value={nuovoTipoQual.carico_lavoro} style="width:70px" />
            <button class="btn btn-success btn-sm" on:click={creaTipoQual}><i class="bi bi-check-lg"></i></button>
            <button class="btn btn-secondary btn-sm" on:click={() => { showAddTipoQual = false; nuovoTipoQual = {nome:'',descrizione:'',carico_lavoro:0}; }}><i class="bi bi-x"></i></button>
          </div>
        {/if}
        <EditableTable
          items={tipiQualitativo}
          columns={[
            { key: 'nome', label: 'Nome', width: '80px', viewClass: 'fw-semibold' },
            { key: 'descrizione', label: 'Descrizione', width: '120px', viewClass: 'small text-muted' },
            { key: 'carico_lavoro', label: 'Carico', type: 'number', step: 5, min: 0, width: '70px', viewClass: 'small' },
          ]}
          onsave={salvaTipoQual}
          ondelete={tq => eliminaTipoQual(tq.id)}
        />
      </div>
    </div>

    <!-- ═══ 3. Tipi richiesta lavorativa / assenza (desiderata) ═══ -->
    <div class="card mb-4" style="max-width:900px">
      <div class="card-header fw-semibold d-flex justify-content-between align-items-center">
        Tipi richiesta lavorativa / assenza
        <button class="btn btn-sm btn-outline-primary" on:click={() => { showAddTipoRich = !showAddTipoRich; }}>
          <i class="bi bi-plus me-1"></i>Nuovo tipo richiesta
        </button>
      </div>
      <div class="card-body p-2">
        {#if showAddTipoRich}
          <div class="d-flex gap-2 mb-2 align-items-center flex-wrap" style="font-size:.85rem">
            <input class="form-control form-control-sm" use:focusOnMount placeholder="Sigla" bind:value={nuovoTipoRich.sigla} style="width:60px"
                   on:keydown={e => e.key === 'Enter' && creaTipoRich()} />
            <input class="form-control form-control-sm" placeholder="Descrizione" bind:value={nuovoTipoRich.descrizione} style="width:140px"
                   on:keydown={e => e.key === 'Enter' && creaTipoRich()} />
            <select class="form-select form-select-sm" style="width:110px" bind:value={nuovoTipoRich.tipo}>
              <option value="lavorativo">lavorativo</option>
              <option value="assenza">assenza</option>
            </select>
            <label class="form-check-label small d-flex align-items-center gap-1">
              <input type="checkbox" bind:checked={nuovoTipoRich.counting_flag} /> Conta
            </label>
            <input class="form-control form-control-sm" type="number" step="0.5" placeholder="Ore" bind:value={nuovoTipoRich.ore_default} style="width:60px" />
            <input class="form-control form-control-sm" type="number" placeholder="Ord." bind:value={nuovoTipoRich.ordine} style="width:55px" />
            <select class="form-select form-select-sm" style="width:130px" bind:value={nuovoTipoRich.flag_id}>
              <option value={null}>— fascia o assenza —</option>
              {#each fasceEAssenze as f}
                <option value={f.id}>{f.parent_nome ? f.parent_nome + '→' : ''}{f.nome}</option>
              {/each}
            </select>
            <button class="btn btn-success btn-sm" on:click={creaTipoRich}><i class="bi bi-check-lg"></i></button>
            <button class="btn btn-secondary btn-sm" on:click={() => showAddTipoRich = false}><i class="bi bi-x"></i></button>
          </div>
        {/if}
        <EditableTable
          items={tipiRichiesta}
          columns={[
            { key: 'sigla', label: 'Sigla', width: '55px', viewClass: 'fw-semibold' },
            { key: 'descrizione', label: 'Descrizione', width: '130px' },
            { key: 'tipo', label: 'Tipo', type: 'select', width: '110px',
              options: [{value:'lavorativo',label:'lavorativo'},{value:'assenza',label:'assenza'}],
              badgeClass: (v) => v==='lavorativo' ? 'bg-primary' : 'bg-warning text-dark' },
            { key: 'counting_flag', label: 'Conta', type: 'checkbox', width: '50px' },
            { key: 'ore_default', label: 'Ore', type: 'number', step: 0.5, width: '55px', viewClass: 'small' },
            { key: 'flag_id', label: 'Fascia o assenza', type: 'select', width: '130px',
              options: [{value:null,label:'—'}, ...fasceEAssenze.map(f => ({value:f.id, label:(f.parent_nome ? f.parent_nome+'→':'')+f.nome}))],
              formatHtml: (v) => `<span class="badge bg-secondary small">${flagLabel(v, flagTurno)}</span>` },
            { key: 'ordine', label: 'Ord.', type: 'number', width: '50px' },
          ]}
          emptyText="Nessun tipo richiesta definito."
          prepareEdit={tr => ({...tr, counting_flag: !!tr.counting_flag})}
          onsave={salvaTipoRich}
          ondelete={tr => eliminaTipoRich(tr.id)}
        />
      </div>
    </div>

    <!-- ═══ 4. Regole di conflitto ═══ -->
    <div class="card mb-4">
      <div class="card-header fw-semibold d-flex justify-content-between align-items-center">
        Regole di conflitto
        <button class="btn btn-sm btn-outline-primary" on:click={() => showAddRegola = !showAddRegola}>
          <i class="bi bi-plus me-1"></i>Nuova regola
        </button>
      </div>
      <div class="card-body p-2">

    {#if showAddRegola}
      <div class="card mb-3 border-primary">
        <div class="card-header fw-semibold text-primary">Crea regola conflitto</div>
        <div class="card-body">
          <div class="row g-2 mb-2">
            <div class="col-md-3">
              <label class="form-label small">Nome *</label>
              <input class="form-control form-control-sm" bind:value={nuovaRegola.nome} placeholder="es. Notte con altri" />
            </div>
            <div class="col-md-2">
              <label class="form-label small">Tipo regola</label>
              <select class="form-select form-select-sm" bind:value={nuovaRegola.tipo_regola}>
                {#each TIPI_REGOLA as t}
                  <option value={t.valore}>{t.esteso}</option>
                {/each}
              </select>
            </div>
            {#if nuovaRegola.tipo_regola === 'tipo_vs_tipo'}
              <div class="col-md-2">
                <label class="form-label small">Fascia oraria A</label>
                <select class="form-select form-select-sm" bind:value={nuovaRegola.flag_a_id}>
                  <option value={null}>— qualsiasi —</option>
                  {#each fasceRegolaConflitto as f}
                    <option value={f.id}>{f.parent_nome ? f.parent_nome + '→' : ''}{f.nome}</option>
                  {/each}
                </select>
              </div>
              <div class="col-md-2">
                <label class="form-label small">Fascia oraria B</label>
                <select class="form-select form-select-sm" bind:value={nuovaRegola.flag_b_id}>
                  <option value={null}>— qualsiasi —</option>
                  {#each fasceRegolaConflitto as f}
                    <option value={f.id}>{f.parent_nome ? f.parent_nome + '→' : ''}{f.nome}</option>
                  {/each}
                </select>
              </div>
              <div class="col-md-1">
                <label class="form-label small">Offset</label>
                <input class="form-control form-control-sm" type="number" bind:value={nuovaRegola.offset_giorni} min="-1" max="1" />
              </div>
            {/if}
            <div class="col-md-2">
              <label class="form-label small">Categoria</label>
              <select class="form-select form-select-sm" bind:value={nuovaRegola.categoria}>
                <option value="facoltativa">facoltativa</option>
                <option value="consigliata">consigliata</option>
                <option value="critica">critica</option>
              </select>
            </div>
          </div>
          <div class="row g-2 mb-2">
            <div class="col-md-2">
              <label class="form-label small">Peso numerico</label>
              <input class="form-control form-control-sm" type="number" step="0.1" bind:value={nuovaRegola.peso_numerico} />
            </div>
            <div class="col-md-2 d-flex align-items-end">
              <div class="form-check">
                <input class="form-check-input" type="checkbox" id="nrBlocca" bind:checked={nuovaRegola.blocca_inserimento} />
                <label class="form-check-label small" for="nrBlocca">Blocca inserimento</label>
              </div>
            </div>
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-primary btn-sm" on:click={creaRegola}>
              <i class="bi bi-plus-lg me-1"></i>Crea
            </button>
            <button class="btn btn-secondary btn-sm" on:click={() => showAddRegola = false}>Annulla</button>
          </div>
        </div>
      </div>
    {/if}

      <table class="table table-sm table-hover table-config table-config-fixed align-middle mb-0" style="font-size:.85rem">
        <thead>
          <tr>
            <th style="width:130px">Nome</th><th style="width:110px">Tipo</th><th style="width:120px">Fascia oraria A</th><th style="width:120px">Fascia oraria B</th>
            <th style="width:55px">Offset</th><th style="width:110px">Categoria</th><th style="width:45px">Sfondo</th><th style="width:45px">Testo</th><th style="width:50px">Blocca</th><th style="width:55px">Peso</th><th style="width:50px">Attiva</th><th style="width:60px"></th>
          </tr>
        </thead>
        <tbody>
          {#each regoleConflitto as r (r.id)}
            {#if editingRegola?.id === r.id}
              <tr class="table-warning" on:keydown={editRowKeydown(salvaRegola, () => editingRegola=null)}>
                <td><input class="form-control form-control-sm" use:autoFocus={'nome'} bind:value={editingRegola.nome} style="width:140px" /></td>
                <td>
                  <select class="form-select form-select-sm" use:autoFocus={'tipo_regola'} style="width:110px" bind:value={editingRegola.tipo_regola}>
                    {#each TIPI_REGOLA as t}
                      <option value={t.valore}>{t.breve}</option>
                    {/each}
                  </select>
                </td>
                <td>
                  {#if editingRegola.tipo_regola === 'tipo_vs_tipo'}
                    <select class="form-select form-select-sm" use:autoFocus={'flag_a_id'} style="width:120px" bind:value={editingRegola.flag_a_id}>
                      <option value={null}>qualsiasi</option>
                      {#each fasceRegolaConflitto as f}
                        <option value={f.id}>{f.parent_nome ? f.parent_nome + '→' : ''}{f.nome}</option>
                      {/each}
                    </select>
                  {:else}<span class="text-muted small">qualsiasi</span>{/if}
                </td>
                <td>
                  {#if editingRegola.tipo_regola === 'tipo_vs_tipo'}
                    <select class="form-select form-select-sm" use:autoFocus={'flag_b_id'} style="width:120px" bind:value={editingRegola.flag_b_id}>
                      <option value={null}>qualsiasi</option>
                      {#each fasceRegolaConflitto as f}
                        <option value={f.id}>{f.parent_nome ? f.parent_nome + '→' : ''}{f.nome}</option>
                      {/each}
                    </select>
                  {:else}<span class="text-muted small">qualsiasi</span>{/if}
                </td>
                <td>
                  {#if editingRegola.tipo_regola === 'tipo_vs_tipo'}
                    <input class="form-control form-control-sm" use:autoFocus={'offset_giorni'} type="number" bind:value={editingRegola.offset_giorni} min="-1" max="1" style="width:55px" />
                  {:else}—{/if}
                </td>
                <td>
                  <select class="form-select form-select-sm" use:autoFocus={'categoria'} style="width:110px" bind:value={editingRegola.categoria}>
                    <option value="facoltativa">facoltativa</option>
                    <option value="consigliata">consigliata</option>
                    <option value="critica">critica</option>
                  </select>
                </td>
                <td><input type="color" value={(() => { try { return (typeof editingRegola.stile === 'string' ? JSON.parse(editingRegola.stile) : editingRegola.stile)?.backgroundColor ?? '#ffffff'; } catch { return '#ffffff'; } })()}
                       on:input={e => { const st = typeof editingRegola.stile === 'string' ? JSON.parse(editingRegola.stile || '{}') : {...editingRegola.stile}; st.backgroundColor = e.target.value; editingRegola.stile = JSON.stringify(st); }} /></td>
                <td><input type="color" value={(() => { try { return (typeof editingRegola.stile === 'string' ? JSON.parse(editingRegola.stile) : editingRegola.stile)?.color ?? '#000000'; } catch { return '#000000'; } })()}
                       on:input={e => { const st = typeof editingRegola.stile === 'string' ? JSON.parse(editingRegola.stile || '{}') : {...editingRegola.stile}; st.color = e.target.value; editingRegola.stile = JSON.stringify(st); }} /></td>
                <td><input type="checkbox" bind:checked={editingRegola.blocca_inserimento} /></td>
                <td><input class="form-control form-control-sm" use:autoFocus={'peso_numerico'} type="number" step="0.1" bind:value={editingRegola.peso_numerico} style="width:55px" /></td>
                <td><input type="checkbox" bind:checked={editingRegola.is_active} title="Attiva" /></td>
                <td style="white-space:nowrap" on:click|stopPropagation>
                  <button class="btn btn-success btn-sm py-0" on:click={salvaRegola}><i class="bi bi-check-lg"></i></button>
                  <button class="btn btn-secondary btn-sm py-0" on:click={() => editingRegola = null}><i class="bi bi-x"></i></button>
                </td>
              </tr>
            {:else}
              <!-- svelte-ignore a11y-click-events-have-key-events -->
              <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
              <tr class="editable-row {r.is_active ? '' : 'text-muted'}" on:click={e => startEditFromRow(e, () => editingRegola = {...r})}>
                <td class="fw-semibold" data-field="nome">{r.nome}</td>
                <td class="small" data-field="tipo_regola">{etichettaBreve(r.tipo_regola)}</td>
                <td data-field="flag_a_id">
                  {#if r.flag_a_id}<span class="badge bg-secondary">{@html flagLabel(r.flag_a_id, flagTurno)}</span>
                  {:else}<span class="text-muted small">qualsiasi</span>{/if}
                </td>
                <td data-field="flag_b_id">
                  {#if r.flag_b_id}<span class="badge bg-secondary">{@html flagLabel(r.flag_b_id, flagTurno)}</span>
                  {:else}<span class="text-muted small">qualsiasi</span>{/if}
                </td>
                <td class="small" data-field="offset_giorni">{r.tipo_regola === 'tipo_vs_tipo' ? ((r.offset_giorni > 0 ? '+' : '') + r.offset_giorni) : '—'}</td>
                <td data-field="categoria">
                  <span class="badge" style={regolaStyle(r)}>
                    {r.categoria ?? 'consigliata'}
                  </span>
                </td>
                <td on:click|stopPropagation>
                  <input type="color" value={(() => { try { return (typeof r.stile === 'string' ? JSON.parse(r.stile) : r.stile)?.backgroundColor ?? '#ffffff'; } catch { return '#ffffff'; } })()}
                         on:input={e => { const idx = regoleConflitto.findIndex(x => x.id === r.id); const st = typeof r.stile === 'string' ? JSON.parse(r.stile || '{}') : {...r.stile}; st.backgroundColor = e.target.value; regoleConflitto[idx].stile = JSON.stringify(st); regoleDirty = true; }} />
                </td>
                <td on:click|stopPropagation>
                  <input type="color" value={(() => { try { return (typeof r.stile === 'string' ? JSON.parse(r.stile) : r.stile)?.color ?? '#000000'; } catch { return '#000000'; } })()}
                         on:input={e => { const idx = regoleConflitto.findIndex(x => x.id === r.id); const st = typeof r.stile === 'string' ? JSON.parse(r.stile || '{}') : {...r.stile}; st.color = e.target.value; regoleConflitto[idx].stile = JSON.stringify(st); regoleDirty = true; }} />
                </td>
                <td data-field="blocca_inserimento">{r.blocca_inserimento ? '🚫' : ''}</td>
                <td class="small" data-field="peso_numerico">{r.peso_numerico}</td>
                <td data-field="is_active">{r.is_active ? '✓' : '—'}</td>
                <td style="white-space:nowrap" on:click|stopPropagation>
                  <DeleteButton ondelete={() => eliminaRegola(r.id)} stopPropagation />
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    {#if regoleDirty}
      <div class="d-flex gap-2 mt-2">
        <button class="btn btn-success btn-sm" on:click={salvaStiliRegole}>
          <i class="bi bi-check-lg me-1"></i>Applica colori
        </button>
        <button class="btn btn-outline-secondary btn-sm" on:click={ripristinaStiliRegole}>
          <i class="bi bi-arrow-counterclockwise me-1"></i>Ripristina
        </button>
      </div>
    {/if}
      </div>
    </div>

    <!-- ═══ 4. Parametri + Desiderata presets ═══ -->
    <h6 class="text-muted text-uppercase mb-3"><i class="bi bi-palette me-1"></i>Parametri</h6>

    <div class="d-flex gap-3 flex-wrap align-items-start mb-4">

    <!-- Parametri di sistema -->
    <div class="card" style="max-width:400px;flex:1">
      <div class="card-header fw-semibold">Parametri di sistema</div>
      <div class="card-body">
        {#each Object.entries(config).filter(([k]) => k !== 'conteggi_context') as [k, v]}
          <div class="mb-3">
            <label class="form-label small fw-semibold">{k}</label>
            <input class="form-control form-control-sm"
                   value={v}
                   on:change={e => config[k] = e.target.value} />
          </div>
        {/each}
        <button class="btn btn-primary btn-sm" on:click={salvaConfig}>
          <i class="bi bi-save me-1"></i>Salva
        </button>
      </div>
    </div>

    </div>

    <!-- Conteggi context menu lavoratore -->
    <div class="card mb-4" style="max-width:700px">
      <div class="card-header fw-semibold d-flex justify-content-between align-items-center">
        Conteggi context menu lavoratore
        <button class="btn btn-sm btn-outline-primary" on:click={() => { showAddConteggio = !showAddConteggio; }}>
          <i class="bi bi-plus me-1"></i>Nuovo conteggio
        </button>
      </div>
      <div class="card-body p-2">
        {#if showAddConteggio}
          <div class="d-flex gap-2 mb-2 align-items-center flex-wrap" style="font-size:.8rem">
            <input class="form-control form-control-sm" style="width:80px" use:focusOnMount placeholder="ID"
                   bind:value={nuovoConteggio.id}
                   on:keydown={e => e.key === 'Enter' && addConteggio()} />
            <input class="form-control form-control-sm" style="width:100px" placeholder="Etichetta"
                   bind:value={nuovoConteggio.label}
                   on:keydown={e => e.key === 'Enter' && addConteggio()} />
            <select class="form-select form-select-sm" style="width:110px"
                    bind:value={nuovoConteggio.tipo}>
              <option value="fascia">fascia oraria</option>
              <option value="tipologia">tipologia</option>
            </select>
            {#if nuovoConteggio.tipo === 'tipologia'}
              <select class="form-select form-select-sm" style="width:140px"
                      bind:value={nuovoConteggio.ref_id}>
                <option value={null}>— scegli —</option>
                {#each tipiQualitativo as tq}
                  <option value={tq.id}>{tq.nome}</option>
                {/each}
              </select>
            {:else}
              <select class="form-select form-select-sm" style="width:140px"
                      bind:value={nuovoConteggio.flag_nome}>
                <option value="">— scegli —</option>
                {#each fasceRegolaConflitto as f}
                  <option value={f.nome}>{f.parent_nome ? f.parent_nome + '→' : ''}{f.nome}</option>
                {/each}
              </select>
            {/if}
            <select class="form-select form-select-sm" style="width:80px"
                    bind:value={nuovoConteggio.giorno_settimana}>
              <option value={null}>Tutti</option>
              <option value={1}>Lun</option><option value={2}>Mar</option>
              <option value={3}>Mer</option><option value={4}>Gio</option>
              <option value={5}>Ven</option><option value={6}>Sab</option>
              <option value={0}>Dom</option>
            </select>
            <label class="form-check-label small">
              <input type="checkbox" bind:checked={nuovoConteggio.negato} /> NOT
            </label>
            <button class="btn btn-success btn-sm" on:click={() => { addConteggio(); showAddConteggio = false; }}><i class="bi bi-check-lg"></i></button>
            <button class="btn btn-secondary btn-sm" on:click={() => showAddConteggio = false}><i class="bi bi-x"></i></button>
          </div>
        {/if}
        <EditableTable
          items={conteggiConfig.map((c, i) => ({...c, _idx: i}))}
          idKey="_idx"
          columns={[
            { key: 'id', label: 'ID', width: '70px' },
            { key: 'label', label: 'Etichetta', width: '90px' },
            { key: 'tipo', label: 'Guarda', type: 'select', width: '95px',
              options: [{value:'fascia',label:'fascia oraria'},{value:'tipologia',label:'tipologia'}],
              format: (v) => v === 'tipologia' ? 'tipologia' : 'fascia oraria' },
            { key: 'flag_nome', label: 'Quale', width: '120px',
              formatHtml: (v, item) => item.tipo === 'tipologia'
                ? (tipiQualitativo.find(t => t.id === item.ref_id)?.nome ?? '—')
                : flagLabel(v, flagTurno) },
            { key: 'giorno_settimana', label: 'Giorno', type: 'select', width: '75px',
              options: [{value:null,label:'Tutti'},{value:1,label:'Lun'},{value:2,label:'Mar'},{value:3,label:'Mer'},{value:4,label:'Gio'},{value:5,label:'Ven'},{value:6,label:'Sab'},{value:0,label:'Dom'}],
              format: (v) => v != null ? ['Dom','Lun','Mar','Mer','Gio','Ven','Sab'][v] : 'tutti' },
            { key: 'negato', label: 'NOT logico', type: 'checkbox', width: '70px', format: (v) => v ? 'si' : 'no' },
            { key: 'attivo', label: 'Attivo', type: 'checkbox', width: '50px' },
          ]}
          fontSize=".8rem"
          rowClass={item => !item.attivo ? 'text-muted' : ''}
          onsave={salvaEditConteggio}
          ondelete={item => removeConteggio(item._idx)}
        />
      </div>
    </div>

    <!-- ═══ Vincoli Solver ═══ -->
    <div class="card mb-4" style="max-width:900px">
      <div class="card-header fw-semibold">
        <i class="bi bi-cpu me-1"></i>Vincoli Solver (auto-riempimento)
      </div>
      <div class="card-body p-2">
        <VincoliSolver
          {adminApi}
          {flagTurno}
          {tipiQualitativo}
          initGlobali={vincoliGlobali}
          initSolver={vincoliSolver}
          onmsg={(text, ok) => setMsg('cfg', text, ok)}
        />
      </div>
    </div>

    <!-- ═══ Preset Ottimizzazione ═══ -->
    <div class="card mb-4" style="max-width:900px">
      <div class="card-header fw-semibold d-flex justify-content-between align-items-center">
        <span><i class="bi bi-sliders2 me-1"></i>Preset Ottimizzazione</span>
        <button class="btn btn-sm btn-outline-primary" on:click={() => { showAddPresetOtt = !showAddPresetOtt; }}>
          <i class="bi bi-plus me-1"></i>Nuovo
        </button>
      </div>
      <div class="card-body p-2">
        {#if showAddPresetOtt}
          <div class="border rounded p-2 mb-3 bg-light">
            <div class="row g-2 mb-2">
              <div class="col-auto">
                <input class="form-control form-control-sm" placeholder="Nome"
                       bind:value={nuovoPresetOtt.nome} style="width:180px" />
              </div>
              <div class="col-auto">
                <select class="form-select form-select-sm" style="width:150px"
                        bind:value={nuovoPresetOtt.tipo}>
                  <option value="completo">Completo</option>
                  <option value="per_flag">Per flag</option>
                  <option value="per_parametro">Per parametro</option>
                  <option value="personalizzato">Personalizzato</option>
                </select>
              </div>
              {#if nuovoPresetOtt.tipo === 'per_flag'}
                <div class="col-auto">
                  <select class="form-select form-select-sm" style="width:150px"
                          bind:value={nuovoPresetOtt.ref_id}>
                    <option value={null}>— flag —</option>
                    {#each fasceEAssenze as f}
                      <option value={f.id}>{f.nome}</option>
                    {/each}
                  </select>
                </div>
              {/if}
            </div>
            <div class="row g-2 mb-2">
              {#each ['ore','target','festivi','peso','varieta','desiderata'] as k}
                <div class="col-auto">
                  <label class="form-label small mb-0">{k}</label>
                  <input type="number" class="form-control form-control-sm" style="width:70px"
                         bind:value={nuovoPresetOtt.pesi[k]} min="0" max="10" step="0.5" />
                </div>
              {/each}
            </div>
            <button class="btn btn-sm btn-success" on:click={creaPresetOtt}
                    disabled={!nuovoPresetOtt.nome}>
              <i class="bi bi-check me-1"></i>Crea
            </button>
          </div>
        {/if}

        {#if presetOtt.length === 0}
          <div class="text-muted small fst-italic">Nessun preset configurato.</div>
        {:else}
          <table class="table table-sm table-hover mb-0" style="font-size:.82rem">
            <thead class="table-light"><tr>
              <th>Nome</th>
              <th>Tipo</th>
              <th>Flag</th>
              <th>Pesi</th>
              <th style="width:50px">Attivo</th>
              <th style="width:40px">Default</th>
              <th style="width:40px"></th>
            </tr></thead>
            <tbody>
            {#each presetOtt as p}
              {#if editPresetOttId === p.id}
                <tr class="table-warning {p.is_active ? '' : 'text-muted'}">
                  <td><input class="form-control form-control-sm" bind:value={p.nome} style="width:150px" /></td>
                  <td>
                    <select class="form-select form-select-sm" style="width:120px" bind:value={p.tipo}>
                      <option value="completo">Completo</option>
                      <option value="per_flag">Per flag</option>
                      <option value="per_parametro">Per parametro</option>
                      <option value="personalizzato">Personalizzato</option>
                    </select>
                  </td>
                  <td>
                    {#if p.tipo === 'per_flag'}
                      <select class="form-select form-select-sm" style="width:120px" bind:value={p.ref_id}>
                        <option value={null}>—</option>
                        {#each fasceEAssenze as f}
                          <option value={f.id}>{f.nome}</option>
                        {/each}
                      </select>
                    {:else}<span class="text-muted">—</span>{/if}
                  </td>
                  <td>
                    <div class="d-flex gap-1 flex-wrap">
                      {#each ['ore','target','festivi','peso','varieta','desiderata'] as k}
                        <div style="width:55px">
                          <label class="form-label small mb-0" style="font-size:.7rem">{k}</label>
                          <input type="number" class="form-control form-control-sm py-0" style="font-size:.75rem"
                                 bind:value={p.pesi[k]} min="0" max="10" step="0.5" />
                        </div>
                      {/each}
                    </div>
                  </td>
                  <td class="text-center">
                    <input type="checkbox" checked={!!p.is_active}
                           on:change={() => { p.is_active = p.is_active ? 0 : 1; }} />
                  </td>
                  <td class="text-center">{p.is_default ? 'Si' : ''}</td>
                  <td class="text-nowrap" on:click|stopPropagation>
                    <button class="btn btn-sm btn-outline-success py-0 me-1" on:click={() => salvaPresetOtt(p)}>
                      <i class="bi bi-check"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-secondary py-0" on:click={() => { editPresetOttId = null; caricaPresetOtt(); }}>
                      <i class="bi bi-x"></i>
                    </button>
                  </td>
                </tr>
              {:else}
                <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
                <tr class="editable-row {p.is_active ? '' : 'text-muted'}" style="cursor:pointer"
                    on:click={e => startEditFromRow(e, () => editPresetOttId = p.id)}>
                  <td data-field="nome">{p.nome}</td>
                  <td><span class="badge bg-secondary">{p.tipo}</span></td>
                  <td>{#if p.tipo === 'per_flag'}{flagTurno.find(f => f.id === p.ref_id)?.nome || '?'}{:else}—{/if}</td>
                  <td>
                    <span class="small text-muted">
                      {#each Object.entries(p.pesi || {}) as [k, v]}
                        <span class="me-1" class:fw-bold={v > 1.5}>{k}:{v}</span>
                      {/each}
                    </span>
                  </td>
                  <td class="text-center" data-field="is_active">{p.is_active ? '✓' : '—'}</td>
                  <td class="text-center">{p.is_default ? 'Si' : ''}</td>
                  <td>
                    {#if !p.is_default}
                      <DeleteButton ondelete={() => eliminaPresetOtt(p.id)} stopPropagation />
                    {/if}
                  </td>
                </tr>
              {/if}
            {/each}
            </tbody>
          </table>
        {/if}
      </div>
    </div>

  <!-- ═══════════════ TAB STRUTTURA ═══════════════ -->
  {:else if tab === 'struttura'}
    {#if msgStruttura}<div class="alert py-2 small {msgStruttura.startsWith('✓')?'alert-success':'alert-danger'}">{msgStruttura}</div>{/if}

    <PropostaConfigurazione {proposta} ondecisa={caricaTutto} />

    <ConfigurazioneGuidata fasce={flagTurno} tipologie={tipiQualitativo}
                             presetEsistente={strutturaDelTenant}
                             conteggi={conteggiConfig}
                             {utenti} sovragruppi={sovragruppiDisponibili}
                             tipiRichiesta={tipiRichiesta}
                             regole={regoleConflitto} {config}
                             etichetta={$etichettaStruttura}
                             {vincoliGlobali} {vincoliSolver}
                             oncompletata={wizardCompletato}
                             onannulla={() => tab = 'calendari'}
                             onfasceaggiornate={async () => {
                               flagTurno = (await adminApi.getFlagTurno()).flags ?? [];
                             }}
                             ontipologieaggiornate={async () => {
                               tipiQualitativo = (await adminApi.getTipiQualitativo()).tipi ?? [];
                             }}
                             onconteggiaggiornati={async (nuovi) => {
                               conteggiConfig = nuovi;
                               await salvaConteggi();
                             }}
                             onutentiaggiornati={async () => {
                               utenti = (await adminApi.getUtenti()).utenti ?? [];
                             }}
                             onvocabolarioaggiornato={async () => {
                               flagTurno = (await adminApi.getFlagTurno()).flags ?? [];
                               tipiRichiesta = (await adminApi.getTipi()).tipi ?? [];
                             }}
                             onregoleaggiornate={async () => {
                               regoleConflitto = (await adminApi.getRegoleConflitto()).regole ?? [];
                             }}
                             onconfigaggiornata={async () => {
                               config = (await adminApi.getConfig()).config ?? {};
                             }}
                             onstrutturaimportata={async () => {
                               // Un import dal foglio cambia struttura, persone e
                               // tipologie insieme: si ricarica tutto, invece di
                               // inseguire un pezzo per volta.
                               editPreset = null;
                               await caricaTutto();
                             }} />

  {:else if tab === 'strutturaturni'}
    {#if msgStruttura}<div class="alert py-2 small {msgStruttura.startsWith('✓')?'alert-success':'alert-danger'}">{msgStruttura}</div>{/if}

    {#if !strutturaDelTenant}
      <div class="text-muted small">
        Questa organizzazione non ha ancora una struttura turni: creala dalla
        <button class="btn btn-link btn-sm p-0 align-baseline"
                on:click={() => tab = 'struttura'}>configurazione guidata</button>.
      </div>
    {:else if !editPreset}
      <div class="text-muted small">Caricamento della struttura turni…</div>
    {:else}
      <!-- ── Editor preset ── -->
      <div class="d-flex align-items-center gap-2 mb-3 flex-wrap">
        <!-- Nome preset inline editable -->
        <input class="form-control form-control-sm fw-semibold" style="width:200px"
               bind:value={editPreset.nome} />

        <div class="form-check mb-0">
          <input class="form-check-input" type="checkbox" id="autoSigla" bind:checked={autoSigla} />
          <label class="form-check-label small" for="autoSigla">
            Auto-sigla turni
          </label>
        </div>

        <div class="ms-auto d-flex gap-2">
          <button class="btn btn-sm {showPreview ? 'btn-outline-primary' : 'btn-outline-secondary'}"
                  on:click={() => showPreview = !showPreview}
                  title="{showPreview ? 'Nascondi' : 'Mostra'} anteprima griglia">
            <i class="bi bi-eye{showPreview ? '' : '-slash'} me-1"></i>Anteprima
          </button>
          <button class="btn btn-success btn-sm" on:click={salvaPreset}>
            <i class="bi bi-save me-1"></i>Salva
          </button>
          <button class="btn btn-secondary btn-sm" on:click={() => editPreset = null}>
            <i class="bi bi-arrow-left me-1"></i>Chiudi
          </button>
        </div>
      </div>

      <!-- Split: albero struttura + anteprima griglia -->
      <div class="struttura-split" class:resizing-preview={resizingPreview}>

      <!-- Albero struttura -->
      <div class="struttura-list border rounded overflow-hidden">

        {#each editPreset.struttura as sg, sgIdx (sg.id)}
          <!-- Riga sovragruppo -->
          {#if editingNode === `sg:${sg.id}`}
            <div class="stru-sg stru-editing d-flex align-items-center gap-2 px-2 py-1 border-bottom">
              <i class="bi bi-collection text-primary"></i>
              <input class="form-control form-control-sm" use:autowidth use:focusIf={editFocus==='nome'} placeholder="Nome"
                     bind:value={editingValue.nome}
                     on:input={syncSigla}
                     on:keydown={onEditKeydown} />
              <label class="form-label mb-0 small text-muted">Sigla:</label>
              <input class="form-control form-control-sm" use:autowidth use:focusIf={editFocus==='sigla'} placeholder="Sigla"
                     bind:value={editingValue.sigla} on:keydown={onEditKeydown} />
              <label class="form-label mb-0 small text-muted">Ambito:</label>
              <input class="form-control form-control-sm" use:autowidth use:focusIf={editFocus==='ambito'} placeholder="es. Radiologia"
                     bind:value={editingValue.ambito} on:keydown={onEditKeydown} />
              <button class="btn btn-success btn-sm py-0 px-2" on:click={applyEdit}><i class="bi bi-check-lg"></i></button>
              <button class="btn btn-secondary btn-sm py-0 px-2" on:click={cancelEdit}><i class="bi bi-x-lg"></i></button>
            </div>
          {:else}
            <div class="stru-sg d-flex align-items-center gap-2 px-2 py-1 fw-bold border-bottom"
                 draggable="true"
                 on:dragstart={() => onDragStartSg(sgIdx)}
                 on:dragover|preventDefault
                 on:drop|preventDefault={() => onDropSg(sgIdx)}
                 on:contextmenu={e => onSgCtxMenu(e, sg)}>
              <i class="bi bi-grip-vertical text-muted grip"></i>
              <i class="bi bi-collection text-primary"></i>
              <button class="btn btn-link p-0 text-dark fw-bold text-decoration-none"
                      on:click={() => startEditSg(sg, 'nome')}>{sg.nome || sg.sigla}</button>
              <button class="btn btn-link p-0 text-decoration-none"
                      on:click={() => startEditSg(sg, 'sigla')}>
                <span class="badge bg-secondary fw-normal">{sg.sigla}</span>
              </button>
              {#if sg.ambito}
                <button class="btn btn-link p-0 text-decoration-none"
                        on:click={() => startEditSg(sg, 'ambito')}>
                  <span class="badge bg-info fw-normal text-dark" style="font-size:.7rem">{sg.ambito}</span>
                </button>
              {/if}
              {#if sg.style?.backgroundColor}
                <span class="badge fw-normal" style="font-size:.65rem;background:{sg.style.backgroundColor};color:{sg.style.color ?? '#1a1a1a'};border:1px solid #ccc">stile</span>
              {/if}
              {#if accessoManagerData && accessoManagers.length > 0}
                <AccessoDropdown
                  managers={accessoManagers}
                  checked={_getBulkChecked('sg', sg.id)}
                  isOpen={accessoDropdownOpen === 'sg_' + sg.id}
                  label={accessoLabelBulk('sg', sg.id, accessoVersion)}
                  disabled={_hasUnsavedTurni('sg', sg.id)}
                  title="Manager accesso per tutti i turni: {$etichettaStruttura.singolare.toLowerCase()}"
                  ontoggleopen={() => { if (!_hasUnsavedTurni('sg', sg.id)) toggleAccessoDropdown('sg_' + sg.id); else setMsg('stru', 'Salva prima la struttura: ci sono turni non ancora salvati.', false); }}
                  onchange={s => salvaAccessoBulk('sg', sg.id, s)}
                />
              {/if}
              <button class="btn btn-outline-success btn-sm py-0 px-1 ms-2"
                      on:click={() => { activeAddTurno=null; activeAddGruppo = activeAddGruppo===sg.id?null:sg.id; nuovoGruppo={nome:'',sigla:'',flag_id:fasceDisponibili(sg, null, flagTurno)[0]?.id ?? null}; }}>
                <i class="bi bi-plus-lg"></i> Gruppo
              </button>
              <button class="btn btn-outline-primary btn-sm py-0 px-1" title="Salva struttura"
                      on:click|stopPropagation={salvaPreset}>
                <i class="bi bi-save"></i>
              </button>
              <DeleteButton ondelete={() => delSg(sg.id)} stopPropagation />
            </div>
          {/if}

          <!-- Gruppi del sovragruppo -->
          {#each sg.gruppi as g, gIdx (g.id)}

            <!-- Riga gruppo -->
            {#if editingNode === `g:${sg.id}:${g.id}`}
              <div class="stru-g stru-editing d-flex align-items-center gap-2 border-bottom">
                <i class="bi bi-layers text-secondary"></i>
                <input class="form-control form-control-sm" use:autowidth use:focusIf={editFocus==='nome'} placeholder="Nome"
                       bind:value={editingValue.nome}
                       on:input={syncSigla}
                       on:keydown={onEditKeydown} />
                <label class="form-label mb-0 small text-muted">Sigla:</label>
                <input class="form-control form-control-sm" use:autowidth use:focusIf={editFocus==='sigla'} placeholder="Sigla"
                       bind:value={editingValue.sigla} on:keydown={onEditKeydown} />
                <label class="form-label mb-0 small text-muted">Fascia</label>
                <select class="form-select form-select-sm" style="width:140px" bind:value={editingValue.flag_id}>
                  <option value={null}>— nessuna fascia —</option>
                  {#each fasceDisponibili(sg, g.id, flagTurno) as f}
                    <option value={f.id}>{f.parent_id ? '└ ' : ''}{f.nome}</option>
                  {/each}
                </select>
                <button class="btn btn-success btn-sm py-0 px-2" on:click={applyEdit}><i class="bi bi-check-lg"></i></button>
                <button class="btn btn-secondary btn-sm py-0 px-2" on:click={cancelEdit}><i class="bi bi-x-lg"></i></button>
              </div>
            {:else}
              <div class="stru-g d-flex align-items-center gap-2 border-bottom"
                   draggable="true"
                   on:dragstart={() => onDragStartGruppo(sg.id, gIdx)}
                   on:dragover|preventDefault
                   on:drop|preventDefault={() => onDropGruppo(sg.id, gIdx)}
                   on:contextmenu={e => onGruppoCtxMenu(e, g)}>
                <i class="bi bi-grip-vertical text-muted grip"></i>
                <i class="bi bi-layers text-secondary"></i>
                <button class="btn btn-link p-0 text-dark text-decoration-none fw-semibold"
                        on:click={() => startEditG(sg.id, g, 'nome')}>{g.nome || g.sigla}</button>
                <button class="btn btn-link p-0 text-decoration-none"
                        on:click={() => startEditG(sg.id, g, 'sigla')}>
                  <span class="badge bg-secondary fw-normal">{g.sigla}</span>
                </button>
                <span class="badge bg-primary fw-normal fst-italic text-white" style="font-size:.7rem">flag: {@html flagLabel(g.flag_id ?? g.flag_nome, flagTurno)}</span>
                {#if g.style?.backgroundColor}
                  <span class="badge fw-normal" style="font-size:.65rem;background:{g.style.backgroundColor};color:{g.style.color ?? '#6c757d'};border:1px solid #ccc">sep</span>
                {/if}
                {#if accessoManagerData && accessoManagers.length > 0}
                  <AccessoDropdown
                    managers={accessoManagers}
                    checked={_getBulkChecked('g', g.id)}
                    isOpen={accessoDropdownOpen === 'g_' + g.id}
                    label={accessoLabelBulk('g', g.id, accessoVersion)}
                    disabled={_hasUnsavedTurni('g', g.id)}
                    title={_hasUnsavedTurni('g', g.id) ? 'Salva prima la struttura' : 'Manager accesso per tutti i turni del gruppo'}
                    ontoggleopen={() => { if (!_hasUnsavedTurni('g', g.id)) toggleAccessoDropdown('g_' + g.id); else setMsg('stru', 'Salva prima la struttura: ci sono turni non ancora salvati.', false); }}
                    onchange={s => salvaAccessoBulk('g', g.id, s)}
                  />
                {/if}
                <button class="btn btn-outline-success btn-sm py-0 px-1 ms-2"
                        on:click={() => { activeAddGruppo=null; activeAddTurno = activeAddTurno===`${sg.id}:${g.id}`?null:`${sg.id}:${g.id}`; nuovoTurno={nome:'',tipiQualitativoIds:[]}; }}>
                  <i class="bi bi-plus-lg"></i> Turno
                </button>
                <button class="btn btn-outline-secondary btn-sm py-0 px-1"
                        title="Duplica gruppo con ciclo successivo"
                        on:click={() => duplicaGruppo(sg.id, g)}>
                  <i class="bi bi-copy"></i>
                </button>
                <button class="btn btn-outline-primary btn-sm py-0 px-1" title="Salva struttura"
                        on:click|stopPropagation={salvaPreset}>
                  <i class="bi bi-save"></i>
                </button>
                <DeleteButton ondelete={() => delGruppo(sg.id, g.id)} stopPropagation />
              </div>
            {/if}

            <!-- Turni del gruppo -->
            {#each g.turni as t, tIdx (t.id)}
              {#if editingNode === `t:${sg.id}:${g.id}:${t.id}`}
                <div class="stru-t stru-t-edit stru-editing d-flex align-items-center gap-2 border-bottom flex-wrap">
                  <i class="bi bi-clock text-primary"></i>
                  <input class="form-control form-control-sm" use:autowidth use:focusIf={editFocus==='nome'} placeholder="Nome"
                         bind:value={editingValue.nome} on:keydown={onEditKeydown} />
                  <label class="form-label mb-0 small text-muted">Sigla:</label>
                  <input class="form-control form-control-sm" use:autowidth use:focusIf={editFocus==='sigla'} placeholder="Sigla"
                         bind:value={editingValue.sigla} on:keydown={onEditKeydown} />
                  {#if tipiQualitativo.length}
                    <span class="d-flex align-items-center gap-1 flex-wrap">
                      <label class="form-label mb-0 small text-muted">Qual:</label>
                      {#each tipiQualitativo as tq}
                        <label class="btn btn-sm py-0 px-1 {editingValue.tipi_qualitativi?.includes(tq.id) ? 'btn-success' : 'btn-outline-secondary'}">
                          <input type="checkbox" class="d-none"
                                 checked={editingValue.tipi_qualitativi?.includes(tq.id)}
                                 on:change={() => { editingValue.tipi_qualitativi = toggleQualId(editingValue.tipi_qualitativi || [], tq.id); }} />
                          {tq.nome}
                        </label>
                      {/each}
                    </span>
                  {/if}
                  <span class="d-flex align-items-center gap-1">
                    <label class="form-label mb-0 small text-muted">Solver:</label>
                    <select class="form-select form-select-sm" style="width:120px" bind:value={editingValue.priorita_solver}
                            on:keydown={onEditKeydown}>
                      <option value="indispensabile">Indispens.</option>
                      <option value="automatico">Automatico</option>
                      <option value="manuale">Manuale</option>
                    </select>
                    {#if editingValue.priorita_solver === 'automatico'}
                      <input class="form-control form-control-sm" type="number" min="1" max="100" style="width:55px"
                             bind:value={editingValue.peso_priorita_solver} on:keydown={onEditKeydown} title="Peso solver (1-100)" />
                    {/if}
                  </span>
                  <span class="d-flex align-items-center gap-1">
                    <label class="form-check form-check-inline mb-0" title="Apri turno nei giorni festivi (domeniche)">
                      <input type="checkbox" class="form-check-input" bind:checked={editingValue.apri_festivi} />
                      <span class="form-check-label small">Festivi</span>
                    </label>
                    <label class="form-check form-check-inline mb-0" title="Apri turno nei giorni superfestivi (Natale, Pasqua, ecc.)">
                      <input type="checkbox" class="form-check-input" bind:checked={editingValue.apri_superfestivi} />
                      <span class="form-check-label small">Superfest.</span>
                    </label>
                  </span>
                  <span class="d-flex align-items-center gap-1">
                    <label class="form-check form-check-inline mb-0" title="Turno disattivato (non inseribile da umano né da solver)">
                      <input type="checkbox" class="form-check-input"
                             checked={!!editingValue.is_disabled}
                             on:change={() => {
                               editingValue.is_disabled = editingValue.is_disabled ? 0 : 1;
                               if (!editingValue.is_disabled) editingValue.is_hidden = 0;
                             }} />
                      <span class="form-check-label small">Disatt.</span>
                    </label>
                    <label class="form-check form-check-inline mb-0" title="Turno nascosto (implica disattivato)">
                      <input type="checkbox" class="form-check-input"
                             checked={!!editingValue.is_hidden}
                             on:change={() => {
                               editingValue.is_hidden = editingValue.is_hidden ? 0 : 1;
                               if (editingValue.is_hidden) editingValue.is_disabled = 1;
                             }} />
                      <span class="form-check-label small">Nasc.</span>
                    </label>
                  </span>
                  {#if accessoManagerData && accessoManagers.length > 0}
                    {#if _isDbId(t.id)}
                    <AccessoDropdown
                      managers={accessoManagers}
                      checked={editingValue._accessoChecked || new Set()}
                      isOpen={accessoDropdownOpen === 'turno_' + t.id}
                      label={editingValue._accessoLabel || 'Tutti'}
                      title="Manager che possono gestire questo turno"
                      ontoggleopen={() => toggleAccessoDropdown('turno_' + t.id)}
                      onchange={s => { editingValue._accessoChecked = s; editingValue._accessoLabel = _accessoLabelFromSet(s); editingValue = editingValue; }}
                    />
                    {:else}
                      <button class="btn btn-outline-secondary btn-sm py-0 px-1" type="button" disabled
                              style="font-size:.7rem; min-width:40px; opacity:0.5"
                              title="Salva prima la struttura per gestire l'accesso manager">
                        <i class="bi bi-people-fill me-1"></i>Tutti
                      </button>
                    {/if}
                  {/if}
                  <button class="btn btn-success btn-sm py-0 px-2" on:click={applyEdit}><i class="bi bi-check-lg"></i></button>
                  <button class="btn btn-secondary btn-sm py-0 px-2" on:click={cancelEdit}><i class="bi bi-x-lg"></i></button>
                </div>
              {:else}
                <!-- svelte-ignore a11y-click-events-have-key-events -->
                <div class="stru-t d-flex align-items-center gap-2 border-bottom" style="cursor:pointer"
                     draggable="true"
                     on:dragstart={() => onDragStartTurno(sg.id, g.id, tIdx)}
                     on:dragover|preventDefault
                     on:drop|preventDefault={() => onDropTurno(sg.id, g.id, tIdx)}
                     on:click={e => { if (!e.target.closest('.del-btn') && !e.target.closest('.grip')) startEditT(sg.id, g.id, t, 'nome'); }}
                     >
                  <i class="bi bi-grip-vertical text-muted grip"></i>
                  <span class="fw-semibold">{t.nome || t.sigla}</span>
                  <span class="badge bg-secondary fw-normal">{t.sigla}</span>
                  {#each qualNomi(t.tipi_qualitativi) as qn}
                    <span class="badge bg-warning text-dark fw-normal" style="font-size:.65rem">{qn}</span>
                  {/each}
                  {#if t.priorita_solver === 'indispensabile'}
                    <span class="badge bg-danger fw-normal" style="font-size:.6rem" title="Solver: indispensabile">!</span>
                  {:else if t.priorita_solver === 'manuale'}
                    <span class="badge bg-secondary fw-normal" style="font-size:.6rem" title="Solver: manuale">M</span>
                  {/if}
                  {#if t.apri_festivi}
                    <span class="badge bg-info fw-normal" style="font-size:.6rem" title="Aperto nei festivi (domeniche)">F</span>
                  {/if}
                  {#if t.apri_superfestivi}
                    <span class="badge bg-warning text-dark fw-normal" style="font-size:.6rem" title="Aperto nei superfestivi">SF</span>
                  {/if}
                  {#if t.is_hidden}
                    <span class="badge bg-dark fw-normal" style="font-size:.6rem" title="Turno nascosto (e disattivato)">
                      <i class="bi bi-eye-slash"></i>
                    </span>
                  {:else if t.is_disabled}
                    <span class="badge bg-secondary fw-normal" style="font-size:.6rem" title="Turno disattivato">
                      <i class="bi bi-slash-circle"></i>
                    </span>
                  {/if}
                  {#if accessoManagerData}
                    <span class="badge bg-light text-dark fw-normal" style="font-size:.6rem" title="Manager accesso">
                      <i class="bi bi-people-fill me-1"></i>{accessoLabel('turni', t.id, accessoVersion)}
                    </span>
                  {/if}
                  <button class="btn btn-outline-primary btn-sm py-0 px-1" title="Salva struttura"
                          on:click|stopPropagation={salvaPreset}>
                    <i class="bi bi-save"></i>
                  </button>
                  <DeleteButton ondelete={() => delTurno(sg.id, g.id, t.id)} stopPropagation />
                </div>
              {/if}
            {/each}

            <!-- Form / pulsante + Turno in fondo al gruppo -->
            {#if activeAddTurno === `${sg.id}:${g.id}`}
              <div class="stru-form-t d-flex align-items-center gap-2 border-bottom">
                <i class="bi bi-clock text-primary"></i>
                <input class="form-control form-control-sm" use:autowidth use:focusOnMount placeholder="Nome turno"
                       bind:value={nuovoTurno.nome}
                       on:keydown={e => e.key === 'Enter' && addTurno(sg.id, g.id)} />
                {#if nuovoTurno.nome}
                  <span class="text-muted small font-monospace">→ {turnoSigla(nuovoTurno.nome, g)}</span>
                {/if}
                {#if tipiQualitativo.length}
                  <span class="d-flex align-items-center gap-1 flex-wrap">
                    <label class="form-label mb-0 small text-muted">Qual:</label>
                    {#each tipiQualitativo as tq}
                      <label class="btn btn-sm py-0 px-1 {nuovoTurno.tipiQualitativoIds?.includes(tq.id) ? 'btn-success' : 'btn-outline-secondary'}">
                        <input type="checkbox" class="d-none"
                               checked={nuovoTurno.tipiQualitativoIds?.includes(tq.id)}
                               on:change={() => { nuovoTurno.tipiQualitativoIds = toggleQualId(nuovoTurno.tipiQualitativoIds || [], tq.id); }} />
                        {tq.nome}
                      </label>
                    {/each}
                  </span>
                {/if}
                <button class="btn btn-success btn-sm py-0" on:click={() => addTurno(sg.id, g.id)}>
                  <i class="bi bi-check-lg me-1"></i>Crea
                </button>
                <button class="btn btn-secondary btn-sm py-0" on:click={() => activeAddTurno=null}>
                  <i class="bi bi-x-lg"></i>
                </button>
              </div>
            {:else}
              <div class="stru-t d-flex align-items-center border-bottom">
                <button class="btn btn-outline-success btn-sm py-0 px-1"
                        on:click={() => { activeAddGruppo=null; activeAddTurno=`${sg.id}:${g.id}`; nuovoTurno={nome:'',tipiQualitativoIds:[]}; }}>
                  <i class="bi bi-plus-lg"></i> Turno
                </button>
              </div>
            {/if}

          {/each}

          <!-- Form / pulsante + Gruppo in fondo al sovragruppo -->
          {#if activeAddGruppo === sg.id}
            <div class="stru-form-g d-flex align-items-center gap-2 px-4 py-1 border-bottom">
              <i class="bi bi-layers text-success"></i>
              <input class="form-control form-control-sm" use:autowidth use:focusOnMount placeholder="Nome gruppo"
                     bind:value={nuovoGruppo.nome}
                     on:input={() => { if (autoSigla) nuovoGruppo.sigla = toSigla(nuovoGruppo.nome) + '_' + sg.sigla; }}
                     on:keydown={e => e.key === 'Enter' && addGruppo(sg.id)} />
              <label class="form-label mb-0 small text-muted">Sigla:</label>
              <input class="form-control form-control-sm" use:autowidth placeholder="Sigla"
                     bind:value={nuovoGruppo.sigla}
                     on:keydown={e => e.key === 'Enter' && addGruppo(sg.id)} />
              <label class="form-label mb-0 small text-muted">Fascia</label>
              <select class="form-select form-select-sm" style="width:140px" bind:value={nuovoGruppo.flag_id}>
                <option value={null}>— nessuna fascia —</option>
                {#each fasceDisponibili(sg, null, flagTurno) as f}
                  <option value={f.id}>{f.parent_id ? '└ ' : ''}{f.nome}</option>
                {/each}
              </select>
              <button class="btn btn-success btn-sm py-0" on:click={() => addGruppo(sg.id)}>
                <i class="bi bi-check-lg me-1"></i>Crea
              </button>
              <button class="btn btn-secondary btn-sm py-0" on:click={() => activeAddGruppo=null}>
                <i class="bi bi-x-lg"></i>
              </button>
            </div>
          {:else}
            <div class="stru-g d-flex align-items-center border-bottom">
              <button class="btn btn-outline-success btn-sm py-0 px-1"
                      on:click={() => { activeAddTurno=null; activeAddGruppo=sg.id; nuovoGruppo={nome:'',sigla:'',flag_id:fasceDisponibili(sg, null, flagTurno)[0]?.id ?? null}; }}>
                <i class="bi bi-plus-lg"></i> Gruppo
              </button>
            </div>
          {/if}

        {/each}

        <!-- Aggiungi sovragruppo -->
        {#if showAddSg}
          <div class="stru-add-sg d-flex align-items-center gap-2 px-2 py-2 border-top">
            <i class="bi bi-collection text-primary"></i>
            <input class="form-control form-control-sm" use:autowidth use:focusOnMount
                   placeholder="Nome {$etichettaStruttura.singolare.toLowerCase()}"
                   bind:value={nuovoSg.nome}
                   on:input={() => { if (autoSigla) nuovoSg.sigla = toSigla(nuovoSg.nome); }}
                   on:keydown={e => e.key === 'Enter' && addSg()} />
            <label class="form-label mb-0 small text-muted">Sigla:</label>
            <input class="form-control form-control-sm" use:autowidth placeholder="Sigla"
                   bind:value={nuovoSg.sigla}
                   on:keydown={e => e.key === 'Enter' && addSg()} />
            <label class="form-label mb-0 small text-muted">Ambito:</label>
            <input class="form-control form-control-sm" use:autowidth placeholder="es. Radiologia"
                   bind:value={nuovoSg.ambito}
                   on:keydown={e => e.key === 'Enter' && addSg()} />
            <button class="btn btn-success btn-sm py-0" on:click={addSg}>
              <i class="bi bi-check-lg me-1"></i>Crea
            </button>
            <button class="btn btn-secondary btn-sm py-0" on:click={() => { showAddSg=false; nuovoSg={nome:'',sigla:'',ambito:''}; }}>
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
        {:else}
          <div class="px-2 py-2 border-top">
            <button class="btn btn-outline-primary btn-sm" on:click={() => { showAddSg=true; nuovoSg={nome:'',sigla:'',ambito:''}; }}>
              <i class="bi bi-plus-lg me-1"></i>Aggiungi {$etichettaStruttura.singolare.toLowerCase()}
            </button>
          </div>
        {/if}

        {#if editPreset.struttura.length === 0 && !showAddSg}
          <div class="text-center text-muted small py-4">
            La struttura turni è vuota. Comincia da "Aggiungi
            {$etichettaStruttura.singolare.toLowerCase()}" qui sotto.
          </div>
        {/if}
      </div>

      <!-- Anteprima griglia -->
      {#if showPreview}
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <div class="preview-resize-handle" on:mousedown={onPreviewResizeStart}></div>
        <div class="struttura-preview" style="flex:0 0 {previewWidth}%">
          <div class="d-flex align-items-center gap-2 mb-2">
            <i class="bi bi-eye text-primary"></i>
            <span class="fw-semibold small">Anteprima griglia</span>
          </div>
          <GridPreview struttura={editPreset.struttura} />
        </div>
      {/if}

      </div><!-- /struttura-split -->

      <!-- ── Sezione: Escludi turno per utente ── -->
      <div class="mt-3 border rounded">
        <button class="btn btn-link w-100 text-start d-flex align-items-center gap-2 px-3 py-2"
                on:click={() => showEtSection = !showEtSection}>
          <i class="bi bi-person-dash text-warning"></i>
          <span class="fw-semibold small">Escludi turno per utente</span>
          <span class="badge bg-secondary ms-1">{etPresetData.length}</span>
          <i class="bi bi-chevron-{showEtSection ? 'up' : 'down'} ms-auto small"></i>
        </button>

        {#if showEtSection}
          <div class="px-3 pb-3">
            <p class="text-muted small mb-2">
              Gli utenti configurati qui vengono esclusi dal solver per i turni/gruppi/SG indicati.
              Si applica ai nuovi calendari creati da questo preset e al refresh struttura.
            </p>

            <!-- Form aggiungi -->
            <div class="d-flex gap-1 align-items-end mb-2 flex-wrap">
              <div>
                <label class="form-label small mb-0">Utente</label>
                <select class="form-select form-select-sm" style="min-width:90px"
                        bind:value={etPresetForm.user_id}>
                  <option value={null}>—</option>
                  {#each utenti.filter(u => u.is_active && !u.escluso_turni) as u}
                    <option value={u.id}>{u.sigla}</option>
                  {/each}
                </select>
              </div>
              <div>
                <label class="form-label small mb-0">Livello</label>
                <select class="form-select form-select-sm" style="min-width:110px"
                        bind:value={etPresetForm.tipo}
                        on:change={() => (etPresetForm.target_id = null)}>
                  <option value="turno">Turno</option>
                  <option value="gruppo">Gruppo</option>
                  <option value="sovragruppo">{$etichettaStruttura.singolare}</option>
                </select>
              </div>
              <div class="flex-grow-1">
                <label class="form-label small mb-0">Target</label>
                <select class="form-select form-select-sm" bind:value={etPresetForm.target_id}>
                  <option value={null}>—</option>
                  {#each _etPresetTargets(etPresetForm.tipo) as t}
                    <option value={t.id}>{t.label}</option>
                  {/each}
                </select>
              </div>
              <button class="btn btn-sm btn-outline-primary"
                      on:click={etPresetAggiungi}
                      disabled={!etPresetForm.user_id || !etPresetForm.target_id || etPresetLoading}
                      title="Aggiungi esclusione">
                {#if etPresetLoading}
                  <span class="spinner-border spinner-border-sm"></span>
                {:else}
                  <i class="bi bi-plus-lg"></i>
                {/if}
              </button>
            </div>

            <!-- Lista esclusioni -->
            {#if etPresetData.length === 0}
              <div class="text-muted small fst-italic text-center py-2">
                Nessuna esclusione configurata.
              </div>
            {:else}
              <div class="list-group list-group-flush" style="max-height:300px;overflow-y:auto">
                {#each etPresetData as esc}
                  {@const u = utenti.find(x => x.id === esc.user_id)}
                  {@const figli = (esc.tipo === 'gruppo' || esc.tipo === 'sovragruppo') ? _etPresetFigli(esc) : []}
                  <div class="list-group-item py-1 px-2 small">
                    <div class="d-flex align-items-center gap-2">
                      <span class="badge bg-secondary">{u?.sigla ?? esc.user_id}</span>
                      <span class="badge bg-light text-dark border">{esc.tipo}</span>
                      <span class="text-truncate flex-grow-1">{_etPresetLabel(esc)}</span>
                      <button class="btn btn-sm btn-link text-danger p-0 ms-auto"
                              on:click={() => etPresetRimuovi(esc)}
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
                                     on:change={() => etPresetToggleEccezione(esc, figlio.id)} />
                              {figlio.label}
                            </label>
                          {/each}
                        </div>
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/if}
      </div>

      <!-- ── Sezione: Aspetto griglia ── -->
      <div class="mt-3 border rounded">
        <button class="btn btn-link w-100 text-start d-flex align-items-center gap-2 px-3 py-2"
                on:click={() => showAppSection = !showAppSection}>
          <i class="bi bi-palette text-info"></i>
          <span class="fw-semibold small">Aspetto griglia</span>
          {#if appDirty}
            <span class="badge bg-warning text-dark ms-1 small">modificato</span>
          {/if}
          <i class="bi bi-chevron-{showAppSection ? 'up' : 'down'} ms-auto small"></i>
        </button>

        {#if showAppSection}
          <div class="px-3 pb-3">
            <p class="text-muted small mb-2">
              Colori e bordi applicati alla griglia del calendario (festivi, celle, bordi).
              Si applica ai nuovi calendari creati da questo preset e al refresh struttura.
            </p>

            <AppearanceEditor
              appearance={appearance}
              onchange={a => { appearance = a; appDirty = true; }} />

            <div class="d-flex gap-2 mt-3 align-items-center">
              <button class="btn btn-sm btn-primary" on:click={appSalva} disabled={!appDirty || appLoading}>
                {#if appLoading}
                  <span class="spinner-border spinner-border-sm me-1"></span>
                {/if}
                Salva aspetto
              </button>
              {#if !appDirty}
                <span class="text-muted small">Nessuna modifica.</span>
              {/if}
            </div>
          </div>
        {/if}
      </div>

    {/if}

  {/if}
</div>

<!-- ── CONTEXT MENU FORMATTAZIONE STRUTTURA ──────────────────────── -->
{#if ctxMenuStru}
  <StyleContextMenu
    x={ctxMenuStru.x} y={ctxMenuStru.y}
    tipo={ctxMenuStru.tipo === 'sg' ? 'sg' : 'gruppo'}
    sepStyle={ctxMenuStru.item?.style ?? {}}
    colStyle={ctxMenuStru.tipo === 'sg'
      ? (ctxMenuStru.item?.gruppi?.[0]?.style?.['--columnStyle'] ?? {})
      : (ctxMenuStru.item?.style?.['--columnStyle'] ?? {})}
    borderColor={ctxMenuStru.item?.style?.['--borderColor'] ?? (ctxMenuStru.item?.style?.backgroundColor ?? (ctxMenuStru.tipo === 'sg' ? '#d6d8db' : '#e9ecef'))}
    borderWidth={ctxMenuStru.item?.style?.['--borderWidth'] ?? (ctxMenuStru.tipo === 'sg' ? 5 : 4)}
    repeatName={ctxMenuStru.item?.style?.['--repeatName'] ?? false}
    defaultBg={ctxMenuStru.tipo === 'sg' ? '#d6d8db' : '#e9ecef'}
    defaultFg={ctxMenuStru.tipo === 'sg' ? '#1a1a1a' : '#6c757d'}
    undoCount={styleUndoCount}
    showApplyAll={ctxMenuStru.tipo === 'gruppo'}
    onset={onCtxSetProp}
    onborderset={onCtxBorderSet}
    onapply={applicaCtxStruStyle}
    onclose={closeCtxMenuStru}
    onundo={undoPresetStyle}
    onapplyall={() => applicaATuttiPreset(ctxMenuStru.item)}
  />
{/if}

<style>
  /* Editable rows — click per aprire edit */
  :global(.editable-row) { cursor: pointer; }
  :global(.editable-row:hover) { background-color: #f0f4ff !important; }

  /* Tabelle config — colonne auto-fit e resizable */
  :global(.table-config) { table-layout: auto; width: auto; max-width: 100%; }
  :global(.table-config th) {
    white-space: nowrap;
    overflow: hidden;
    resize: horizontal;
  }
  :global(.table-config td) { white-space: nowrap; }
  :global(.table-config .form-control-sm),
  :global(.table-config .form-select-sm) { min-width: 80px; }

  /* Tabelle config fixed — stessa dimensione in view e edit mode */
  :global(.table-config-fixed) { table-layout: fixed; width: 100%; }
  :global(.table-config-fixed th) { resize: none; overflow: hidden; text-overflow: ellipsis; }
  :global(.table-config-fixed td) { overflow: hidden; text-overflow: ellipsis; }
  :global(.table-config-fixed .form-control-sm),
  :global(.table-config-fixed .form-select-sm) { width: 100%; min-width: 0; box-sizing: border-box; }

  /* Split layout: struttura editor + anteprima griglia */
  .struttura-split {
    display: flex;
    align-items: flex-start;
  }
  .struttura-split > .struttura-list {
    flex: 1 1 0%;
    min-width: 0;
  }
  .struttura-preview {
    min-width: 0;
    position: sticky;
    top: 60px;
    max-height: calc(100vh - 120px);
    overflow: auto;
  }
  .preview-resize-handle {
    flex: 0 0 6px;
    align-self: stretch;
    cursor: col-resize;
    background: transparent;
    position: relative;
    z-index: 5;
  }
  .preview-resize-handle::after {
    content: '';
    position: absolute;
    left: 2px;
    top: 0; bottom: 0;
    width: 2px;
    background: #dee2e6;
    border-radius: 1px;
    transition: background .15s;
  }
  .preview-resize-handle:hover::after,
  .resizing-preview .preview-resize-handle::after {
    background: #0d6efd;
    width: 3px;
    left: 1px;
  }
  .resizing-preview {
    user-select: none;
    cursor: col-resize;
  }

  @media (max-width: 992px) {
    .struttura-split {
      flex-direction: column;
    }
    .preview-resize-handle {
      display: none;
    }
    .struttura-preview {
      position: static;
      max-height: 50vh;
      flex: 1 1 100% !important;
    }
  }

  .struttura-list { background: #fff; }

  .stru-sg      { background: #e9ecef; font-size: .9rem;  min-height: 36px; padding: 0.25rem 0.5rem; }
  .stru-g       { background: #f8f9fa; font-size: .88rem; min-height: 34px; padding: 0.25rem 2rem; }
  .stru-form-g  { background: #d1e7dd; font-size: .85rem; min-height: 34px; padding: 0.25rem 2rem; }
  .stru-t       { background: #fff;    font-size: .85rem; min-height: 32px; padding: 0.2rem 3.5rem; }
  .stru-form-t  { background: #cfe2ff; font-size: .85rem; min-height: 32px; padding: 0.2rem 3.5rem; width: fit-content; min-width: 100px; }
  .stru-t-edit  { width: fit-content; min-width: 100px; }
  .stru-editing { background: #fff3cd !important; }
  .stru-add-sg  { background: #f8f9fa; font-size: .88rem; }

  .grip { cursor: grab; opacity: .5; }
  .grip:active { cursor: grabbing; }

  .stru-g[draggable="true"]:hover,
  .stru-t[draggable="true"]:hover { background: #e8f0fe; }

  .stru-sg[draggable="true"]:hover { background: #dee2e6; }


  .stru-sg[draggable="true"],
  .stru-g[draggable="true"],
  .stru-t[draggable="true"] { cursor: context-menu; }

  /* Dropdown accesso manager */
  .accesso-dropdown {
    position: absolute; top: 100%; left: 0; z-index: 1050;
    background: #fff; border: 1px solid #dee2e6; border-radius: .25rem;
    min-width: 140px; padding: .25rem .5rem; font-size: .75rem;
    max-height: 200px; overflow-y: auto;
  }
  .accesso-item { display: flex; align-items: center; gap: .35rem; white-space: nowrap; padding: 1px 0; cursor: pointer; }
  .accesso-item input[type="checkbox"] { margin: 0; }
</style>
