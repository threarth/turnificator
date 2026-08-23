<script>
  /**
   * DesiderataInserimento — componente condiviso per /basic e tab
   * "Inserisci Desiderata" in /manager.
   *
   * Mostra la griglia desiderata completa (tutti gli utenti). L'utente
   * corrente può modificare solo la propria riga/colonna con:
   *   - CellEditor (dropdown tipo richiesta)
   *   - Navigazione tastiera (Arrow/Tab/Enter)
   *   - Multi-selezione (Shift+click, Ctrl+click, Shift+arrow)
   *   - Bulk clear (Del/Backspace su selezione)
   *   - Paste da Excel (TSV, sigle tipo richiesta)
   * Nessun undo/redo (per semplicità e coerenza: la sorgente di verità
   * per i congelati è working_desiderata, non desiderata basic).
   *
   * Orientamento di default: utenti-righe × giorni-colonne.
   * Toggle trasposizione persistito in localStorage['desiderataTrasposta']
   * (stato condiviso con le griglie WD/Originali in /manager).
   *
   * Manager/admin vedono controlli ordinamento (modalita + riordino manuale).
   * La visibilità del tab in /manager è gestita dal parent (escluso_turni=0).
   */

  import { onMount, onDestroy } from 'svelte';
  import { basicApi, adminApi } from '$lib/api.js';
  import { user as userStore } from '$lib/auth.js';
  import CellEditor from '$lib/CellEditor.svelte';
  import { showToast } from '$lib/toast.js';
  import { APPEARANCE_DEFAULT } from '$lib/admin/AppearanceEditor.svelte';
  import {
    connectSocket, joinCalendario, leaveCalendario,
    onDesiderataChanged, onPrivacyChanged, offListener,
  } from '$lib/socket.js';

  // ── Stato calendario e dati ─────────────────────────────────────
  let calendari   = $state([]);
  let calId       = $state(null);
  let calendario  = $state(null);
  let giorni      = $state([]);              // [{giorno, tipo, is_lavorativo, ...}]
  let tipi        = $state([]);              // tipi_richiesta (lavorativo + assenza)
  let utenti      = $state([]);              // utenti ordinati
  let sovragruppi = $state([]);              // sovragruppi ordinati
  let modalita    = $state('alfabetico_intragruppo');
  let meId        = $state(null);
  let meRole      = $state('basic');
  let meOffusca   = $state(0);
  let desMap      = $state({});              // uid → { giorno → { tipo_richiesta_id, req_sigla, req_tipo } }
  let loading     = $state(false);
  let msgErr      = $state('');
  let saveStatus  = $state({});              // giorno → 'saving' | 'ok' | 'err'

  // ── Orientamento griglia (persistito) ──────────────────────────
  let trasposto   = $state(false);
  if (typeof localStorage !== 'undefined') {
    trasposto = localStorage.getItem('desiderataTrasposta') === '1';
  }
  function toggleTrasposto() {
    trasposto = !trasposto;
    try { localStorage.setItem('desiderataTrasposta', trasposto ? '1' : '0'); }
    catch {}
  }

  // ── Riordino manuale (solo privileged) ─────────────────────────
  let riordinoOn  = $state(false);

  // ── Editing/selezione propria riga (Set<giorno>) ───────────────
  let focusedGiorno = $state(null);
  let selectedDays  = $state(new Set());
  let selAnchorDay  = $state(null);
  let selEndDay     = $state(null);

  // ── Costanti ───────────────────────────────────────────────────
  const NOMI_MESI = ['', 'Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
                     'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'];
  const NOMI_GG   = ['Dom','Lun','Mar','Mer','Gio','Ven','Sab'];

  // ── Derivazioni ────────────────────────────────────────────────
  let calCorrente  = $derived(calendari.find(c => c.id === calId));
  let canEdit      = $derived(!calendario?.desiderata_congelati && !$userStore?.escluso_turni);
  let isPrivileged = $derived(meRole === 'manager' || meRole === 'admin');

  let numGiorni = $derived(giorni.length);
  let giorniList = $derived(giorni.map(g => g.giorno));

  // Opzioni CellEditor (dipendono solo da tipi)
  let cellOptions = $derived([
    { value: '', label: '—' },
    ...tipi.filter(t => t.tipo === 'lavorativo').map(t => ({ value: String(t.id), label: t.sigla })),
    ...tipi.filter(t => t.tipo === 'assenza').map(t => ({ value: String(t.id), label: t.sigla })),
  ]);

  // Mappa sg_id → style (snapshot calendario) per colore coerente con griglia turni.
  let sgStyleMap = $derived.by(() => {
    const m = {};
    for (const s of sovragruppi) m[s.id] = s.style ?? {};
    return m;
  });

  // Stile inline per blocco SG (solo backgroundColor + color dallo snapshot).
  function sgBlockStyle(sgId) {
    const s = sgStyleMap[sgId] ?? {};
    const parts = [];
    if (s.backgroundColor) parts.push(`background-color:${s.backgroundColor}`);
    if (s.color)           parts.push(`color:${s.color}`);
    return parts.join(';');
  }

  // Raggruppa utenti consecutivi per sovragruppo (header con rowspan/colspan).
  // NB: la chiave unisce sg_id + posizione del blocco, perche' in modalita
  // 'alfabetico_globale' lo stesso sovragruppo puo' comparire in blocchi
  // non contigui (sg_id ripetuto → duplicate key nell'each Svelte).
  let userGroups = $derived.by(() => {
    const out = [];
    let cur = null;
    for (const u of utenti) {
      const sgKey = u.sovragruppo_id ?? 'null';
      if (cur && cur.sgKey === sgKey) {
        cur.count++; cur.users.push(u);
      } else {
        cur = {
          key: `${sgKey}_${out.length}`,
          sgKey,
          count: 1, users: [u],
          sg_sigla: u.sg_sigla, sg_nome: u.sg_nome,
          sovragruppo_id: u.sovragruppo_id,
        };
        out.push(cur);
      }
    }
    return out;
  });

  // ── Lifecycle ──────────────────────────────────────────────────
  let _joinedCalId = null;

  onMount(async () => {
    const u = $userStore;
    if (u) { meId = u.id; meRole = u.role || 'basic'; }
    const [rc, rt] = await Promise.all([
      basicApi.getCalendari(),
      adminApi.getTipi(),
    ]);
    calendari = rc.calendari ?? [];
    tipi = (rt.tipi ?? []).filter(t => t.tipo === 'lavorativo' || t.tipo === 'assenza');

    // Connessione WS + listeners desiderata/privacy real-time
    connectSocket();
    onDesiderataChanged(_onRemoteDesiderataChanged);
    onPrivacyChanged(_onRemotePrivacyChanged);

    if (calendari.length) await selezionaCalendario(calendari[0].id);

    window.addEventListener('paste', onGlobalPaste);
    window.addEventListener('keydown', onGlobalKeydown);
  });

  onDestroy(() => {
    if (typeof window === 'undefined') return;
    window.removeEventListener('paste', onGlobalPaste);
    window.removeEventListener('keydown', onGlobalKeydown);
    if (_joinedCalId != null) leaveCalendario(_joinedCalId);
    offListener('desiderata_changed', _onRemoteDesiderataChanged);
    offListener('privacy_changed', _onRemotePrivacyChanged);
  });

  /**
   * Aggiorna desMap quando un altro client inserisce/modifica/cancella una
   * desiderata sullo stesso calendario. Ignora eventi generati da se' stesso.
   * Applica il mascheramento privacy in base all'`author_offusca` del payload
   * (inviato dal backend) per mantenere la coerenza con il rendering iniziale:
   *   - viewer basic (non autore):
   *       offusca=2 → nessuna modifica visibile (scarta delta)
   *       offusca=1 + richiesta 'assenza' → sigla sostituita con 'X'
   *   - viewer manager/admin: nessun mascheramento
   *   - autore (se stesso): vede sempre intero
   */
  function _onRemoteDesiderataChanged(evt) {
    if (evt.actor_id && evt.actor_id === meId) return;
    if (evt.source !== 'desiderata') return;  // WD manager non pertinente qui
    const uid = evt.user_id;
    const g = evt.giorno;
    const isSelf = uid === meId;
    const offusca = evt.author_offusca ?? 0;
    const mascheramentoOn = (meRole === 'basic') && !isSelf;

    // offusca=2 sull'altro autore → il basic viewer non deve vedere nulla
    if (mascheramentoOn && offusca === 2) return;

    const nuova = { ...desMap };
    if (!nuova[uid]) nuova[uid] = {};
    else nuova[uid] = { ...nuova[uid] };

    if (evt.entry) {
      let entry = evt.entry;
      // offusca=1 su richiesta di tipo 'assenza' → sostituisci sigla con 'X'
      if (mascheramentoOn && offusca === 1 && entry.req_tipo === 'assenza') {
        entry = { ...entry, req_sigla: 'X' };
      }
      nuova[uid][g] = entry;
    } else {
      delete nuova[uid][g];
    }
    desMap = nuova;
  }

  /**
   * Quando un altro utente cambia il proprio flag offusca, i basic viewer
   * devono rivedere i desiderata di quell'autore col nuovo mascheramento:
   *
   *   - piu' restrittivo (0→1, 0→2, 1→2): locale, si puo' mascherare quello
   *     che abbiamo gia';
   *   - meno restrittivo (2→0/1, 1→0): servono dati che il client non ha
   *     mai ricevuto, quindi si ricarica la griglia dal server (che applica
   *     il nuovo mascheramento lato backend).
   *
   * Per semplicita' e coerenza si ricarica sempre (l'evento e' raro).
   * Manager/admin vedono tutto indipendentemente: aggiorniamo solo
   * utenti[i].offusca per coerenza dei dati, niente re-fetch.
   */
  function _onRemotePrivacyChanged(evt) {
    if (evt.actor_id && evt.actor_id === meId) return;
    const target = utenti.find(u => u.id === evt.user_id);
    if (target) {
      target.offusca = evt.offusca;
      utenti = [...utenti];
    }
    // Applica solo mascheramento locale ai client basic (niente hard refresh).
    // Transizioni verso piu' privacy: nascondiamo/mascheriamo subito.
    // Transizioni verso meno privacy: i dati nascosti non sono recuperabili
    // senza refetch, quindi verranno visti solo al prossimo ricaricamento manuale.
    if (meRole !== 'basic' || evt.user_id === meId) return;
    const uid = evt.user_id;
    const nuova = { ...desMap };
    if (evt.offusca === 2) {
      if (nuova[uid]) delete nuova[uid];
    } else if (evt.offusca === 1) {
      if (nuova[uid]) {
        const userMap = { ...nuova[uid] };
        for (const g in userMap) {
          const e = userMap[g];
          if (e && e.req_tipo === 'assenza') {
            userMap[g] = { ...e, req_sigla: 'X' };
          }
        }
        nuova[uid] = userMap;
      }
    }
    desMap = nuova;
  }

  // ── Caricamento dati ───────────────────────────────────────────
  async function selezionaCalendario(id) {
    // Cambio room WebSocket: lascia il calendario precedente, entra nel nuovo
    if (_joinedCalId != null && _joinedCalId !== id) {
      leaveCalendario(_joinedCalId);
    }
    calId = id;
    _joinedCalId = id;
    joinCalendario(id);

    loading = true;
    msgErr = '';
    clearSelection();
    focusedGiorno = null;
    const r = await basicApi.getDesiderataGlobale(id);
    loading = false;
    if (!r.ok) { msgErr = r.errore || 'Errore caricamento.'; return; }
    calendario  = r.calendario;
    giorni      = r.giorni ?? [];
    utenti      = r.utenti ?? [];
    sovragruppi = r.sovragruppi ?? [];
    modalita    = r.modalita ?? 'alfabetico_intragruppo';
    if (r.me) {
      meId = r.me.id;
      meRole = r.me.role;
      meOffusca = r.me.offusca ?? 0;
    }
    const m = {};
    for (const u of utenti) m[u.id] = {};
    for (const d of r.desiderata) {
      if (!m[d.user_id]) m[d.user_id] = {};
      m[d.user_id][d.giorno] = {
        tipo_richiesta_id: d.tipo_richiesta_id,
        req_sigla: d.req_sigla,
        req_tipo:  d.req_tipo,
      };
    }
    desMap = m;
  }

  // ── Helpers giorno ─────────────────────────────────────────────
  function dayInfo(g) { return giorni.find(x => x.giorno === g) ?? {}; }
  function dayName(g) {
    if (!calendario) return '';
    const d = new Date(calendario.anno, calendario.mese - 1, g);
    return NOMI_GG[d.getDay()];
  }
  function dayClass(g) {
    const t = dayInfo(g).tipo;
    if (t === 'superfestivo') return 'gc-super';
    if (t === 'festivo')      return 'gc-fest';
    return '';
  }

  // Appearance: stessi CSS vars di /manager griglia turni
  let appVals = $derived(calendario?.appearance ?? {});
  let gridCssVars = $derived(
    `--gc-festivi-bg:${appVals.festivi_bg ?? APPEARANCE_DEFAULT.festivi_bg};` +
    `--gc-superfestivi-bg:${appVals.superfestivi_bg ?? APPEARANCE_DEFAULT.superfestivi_bg};`
  );

  // ── Classe cella ───────────────────────────────────────────────
  function cellClass(uid, g) {
    const cls = ['des-cell'];
    const isMe = uid === meId;
    const cell = desMap[uid]?.[g];
    if (isMe) cls.push('cell-me');
    if (cell?.req_tipo === 'lavorativo') cls.push('des-working');
    else if (cell?.req_tipo === 'assenza') cls.push('des-notworking');
    if (isMe && canEdit) {
      const key = g;
      if (selectedDays.has(key)) cls.push('des-selected');
      if (focusedGiorno === g)   cls.push('gc-focused');
    }
    return cls.join(' ');
  }

  // ── Salvataggio singola cella ──────────────────────────────────
  async function salva(giorno, tipo_richiesta_id) {
    if (!canEdit) return;
    saveStatus[giorno] = 'saving';
    let r;
    if (!tipo_richiesta_id) {
      r = await basicApi.delDesiderata(calId, giorno);
    } else {
      r = await basicApi.salvaDesiderata(calId, {
        giorno, tipo_richiesta_id: parseInt(tipo_richiesta_id), note: null,
      });
    }
    saveStatus[giorno] = r.ok ? 'ok' : 'err';
    if (!r.ok) {
      msgErr = r.errore ?? 'Errore nel salvataggio.';
    } else {
      if (!desMap[meId]) desMap[meId] = {};
      if (!tipo_richiesta_id) {
        delete desMap[meId][giorno];
      } else {
        const t = tipi.find(x => x.id === parseInt(tipo_richiesta_id));
        desMap[meId][giorno] = {
          tipo_richiesta_id: parseInt(tipo_richiesta_id),
          req_sigla: t?.sigla ?? '',
          req_tipo:  t?.tipo ?? '',
        };
      }
      desMap = { ...desMap };
    }
    setTimeout(() => { saveStatus[giorno] = ''; }, 1500);
  }

  // ── Selezione (solo propria riga) ──────────────────────────────
  function clearSelection() {
    if (selectedDays.size === 0) return;
    selectedDays = new Set();
    selAnchorDay = null;
    selEndDay = null;
  }

  function toggleDaySelection(g) {
    const next = new Set(selectedDays);
    if (next.has(g)) next.delete(g);
    else next.add(g);
    selectedDays = next;
    selAnchorDay = g;
  }

  function selectDayRange(g) {
    if (selAnchorDay == null) { toggleDaySelection(g); return; }
    const a = Math.min(selAnchorDay, g);
    const b = Math.max(selAnchorDay, g);
    const next = new Set();
    for (let d = a; d <= b; d++) {
      if (giorniList.includes(d)) next.add(d);
    }
    selectedDays = next;
  }

  function extendSelection(dir) {
    if (selAnchorDay == null) return;
    const curEnd = selEndDay ?? selAnchorDay;
    let nextG = curEnd;
    // direzione "in avanti" nella riga: dipende dall'orientamento
    if (trasposto) {
      // giorni su righe: up/down muovono fra giorni; left/right no-op
      if (dir === 'down') nextG = Math.min(nextG + 1, numGiorni);
      else if (dir === 'up') nextG = Math.max(nextG - 1, 1);
      else return;
    } else {
      // giorni su colonne: left/right muovono fra giorni; up/down no-op
      if (dir === 'right') nextG = Math.min(nextG + 1, numGiorni);
      else if (dir === 'left')  nextG = Math.max(nextG - 1, 1);
      else return;
    }
    selEndDay = nextG;
    selectDayRange(nextG);
  }

  // ── Navigazione tastiera (propria riga) ────────────────────────
  function moveFocus(dir) {
    if (focusedGiorno == null) return;
    let nextG = focusedGiorno;
    if (trasposto) {
      // giorni su righe: up/down muovono fra giorni
      if (dir === 'down' || dir === 'tab') nextG = Math.min(nextG + 1, numGiorni);
      else if (dir === 'up' || dir === 'tab-back') nextG = Math.max(nextG - 1, 1);
      else return;
    } else {
      // giorni su colonne: left/right muovono fra giorni; tab muove fra giorni
      if (dir === 'right' || dir === 'tab') nextG = Math.min(nextG + 1, numGiorni);
      else if (dir === 'left' || dir === 'tab-back') nextG = Math.max(nextG - 1, 1);
      else return;
    }
    focusedGiorno = nextG;
    selAnchorDay = nextG;
    selEndDay = null;
    clearSelection();
  }

  function onCellConfirm(g) {
    // Enter conferma → avanza al prossimo giorno nella direzione "riga"
    moveFocus(trasposto ? 'down' : 'right');
  }

  function onCellPointerDown(e, g) {
    if (e.button !== 0) return;
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault(); e.stopPropagation();
      if (document.activeElement?.tagName === 'SELECT') document.activeElement.blur();
      toggleDaySelection(g);
      return;
    }
    if (e.shiftKey) {
      e.preventDefault(); e.stopPropagation();
      if (document.activeElement?.tagName === 'SELECT') document.activeElement.blur();
      selectDayRange(g);
      return;
    }
    if (selectedDays.size > 0) clearSelection();
    if (!e.target.closest('.ce-btn')) {
      focusedGiorno = g;
      selAnchorDay = g;
    }
  }

  // ── Bulk clear su selezione (parallel DELETE) ──────────────────
  async function bulkClearDays() {
    if (!canEdit || selectedDays.size === 0) return;
    const days = Array.from(selectedDays).filter(g => desMap[meId]?.[g]);
    clearSelection();
    if (days.length === 0) return;
    // Marca tutte come "saving"
    for (const g of days) saveStatus[g] = 'saving';
    saveStatus = { ...saveStatus };
    const results = await Promise.all(days.map(g => basicApi.delDesiderata(calId, g)));
    let errs = 0;
    const newMap = { ...desMap };
    if (!newMap[meId]) newMap[meId] = {};
    for (let i = 0; i < days.length; i++) {
      const g = days[i];
      if (results[i].ok) {
        delete newMap[meId][g];
        saveStatus[g] = 'ok';
      } else {
        saveStatus[g] = 'err';
        errs++;
      }
    }
    desMap = newMap;
    saveStatus = { ...saveStatus };
    if (errs > 0) showToast(`${errs} errori durante lo svuotamento.`, true);
    else showToast(`${days.length} cell${days.length === 1 ? 'a svuotata' : 'e svuotate'}`);
    setTimeout(() => {
      for (const g of days) saveStatus[g] = '';
      saveStatus = { ...saveStatus };
    }, 1500);
  }

  // ── Paste da clipboard (solo propria riga, TSV da Excel) ───────
  function onGlobalPaste(e) {
    if (document.activeElement?.tagName === 'INPUT' || document.activeElement?.tagName === 'TEXTAREA') return;
    if (focusedGiorno == null || !canEdit) return;
    const tsv = e.clipboardData?.getData('text/plain') ?? '';
    if (!tsv) return;
    e.preventDefault();
    const cells = _parsePaste(tsv);
    if (cells.length > 0) _eseguiPaste(cells);
  }

  function _parsePaste(tsv) {
    // Accetta una singola riga (TSV) o una singola colonna; applica alla propria riga.
    // Ogni token viene confrontato con la sigla di un tipo; 'X' o '' → vuoto.
    const tokens = [];
    for (const row of tsv.split('\n').map(r => r.replace(/\r$/, '')).filter(r => r !== '')) {
      for (const cell of row.split('\t')) tokens.push(cell.trim());
    }
    const cells = [];
    for (let i = 0; i < tokens.length; i++) {
      const g = focusedGiorno + i;
      if (g > numGiorni) break;
      const t = tokens[i] === '' ? null : tipi.find(t => t.sigla.toLowerCase() === tokens[i].toLowerCase());
      if (tokens[i] !== '' && !t) continue;
      cells.push({ giorno: g, tipo_richiesta_id: t?.id ?? null });
    }
    return cells;
  }

  async function _eseguiPaste(cells) {
    for (const c of cells) saveStatus[c.giorno] = 'saving';
    saveStatus = { ...saveStatus };
    const results = await Promise.all(cells.map(c => {
      if (c.tipo_richiesta_id) {
        return basicApi.salvaDesiderata(calId, { giorno: c.giorno, tipo_richiesta_id: c.tipo_richiesta_id, note: null });
      }
      return basicApi.delDesiderata(calId, c.giorno);
    }));
    const newMap = { ...desMap };
    if (!newMap[meId]) newMap[meId] = {};
    let errs = 0;
    for (let i = 0; i < cells.length; i++) {
      const c = cells[i];
      if (results[i].ok) {
        if (c.tipo_richiesta_id) {
          const t = tipi.find(x => x.id === c.tipo_richiesta_id);
          newMap[meId][c.giorno] = {
            tipo_richiesta_id: c.tipo_richiesta_id,
            req_sigla: t?.sigla ?? '',
            req_tipo:  t?.tipo ?? '',
          };
        } else {
          delete newMap[meId][c.giorno];
        }
        saveStatus[c.giorno] = 'ok';
      } else {
        saveStatus[c.giorno] = 'err';
        errs++;
      }
    }
    desMap = newMap;
    saveStatus = { ...saveStatus };
    if (errs > 0) showToast(`${errs} errori durante il paste.`, true);
    setTimeout(() => {
      for (const c of cells) saveStatus[c.giorno] = '';
      saveStatus = { ...saveStatus };
    }, 1500);
  }

  // ── Keyboard globale (Del/Backspace per bulk clear) ────────────
  function onGlobalKeydown(e) {
    if (document.activeElement?.tagName === 'INPUT' || document.activeElement?.tagName === 'TEXTAREA') return;
    if (!canEdit) return;
    // Del/Backspace su selezione multipla → bulk clear
    if ((e.key === 'Delete' || e.key === 'Backspace') && selectedDays.size > 0) {
      // Evita conflitto con CellEditor singola: se c'è solo la cella focused, lascialo gestire al CellEditor
      if (selectedDays.size === 1 && focusedGiorno != null && selectedDays.has(focusedGiorno)) return;
      e.preventDefault();
      bulkClearDays();
    }
    // Escape: clear selezione
    if (e.key === 'Escape' && selectedDays.size > 0) {
      e.preventDefault();
      clearSelection();
    }
  }

  // ── Privacy / Modalità / Riordino ───────────────────────────────
  async function cambiaPrivacy(nuovoValore) {
    const r = await basicApi.setPrivacy(nuovoValore);
    if (r.ok) meOffusca = nuovoValore;
    else msgErr = r.errore ?? 'Errore salvataggio privacy.';
  }

  async function cambiaModalita(nuovaMod) {
    const r = await adminApi.setModalitaOrdinamentoDesiderata(nuovaMod);
    if (r.ok) { modalita = nuovaMod; await selezionaCalendario(calId); }
    else msgErr = r.errore ?? 'Errore salvataggio modalità.';
  }

  async function spostaUtente(uid, delta) {
    const idx = utenti.findIndex(u => u.id === uid);
    const target = idx + delta;
    if (idx < 0 || target < 0 || target >= utenti.length) return;
    const nuovi = [...utenti];
    const [x] = nuovi.splice(idx, 1);
    nuovi.splice(target, 0, x);
    utenti = nuovi;
    const r = await adminApi.setOrdineUtentiDesiderata(nuovi.map(u => u.id));
    if (!r.ok) { msgErr = r.errore ?? 'Errore salvataggio ordine.'; await selezionaCalendario(calId); }
  }

  async function spostaSovragruppo(sgId, delta) {
    const idx = sovragruppi.findIndex(s => s.id === sgId);
    const target = idx + delta;
    if (idx < 0 || target < 0 || target >= sovragruppi.length) return;
    const nuovi = [...sovragruppi];
    const [x] = nuovi.splice(idx, 1);
    nuovi.splice(target, 0, x);
    sovragruppi = nuovi;
    const r = await adminApi.setOrdineSovragruppiDesiderata(nuovi.map(s => s.id));
    if (!r.ok) msgErr = r.errore ?? 'Errore salvataggio ordine.';
    await selezionaCalendario(calId);
  }

  function tipoLabel(t) { return `${t.sigla} — ${t.descrizione}`; }
</script>

<div class="container-fluid py-3" style={gridCssVars}>
  <!-- Toolbar ─────────────────────────────────────────────────── -->
  <div class="d-flex align-items-center gap-2 mb-3 flex-wrap">
    <h5 class="mb-0 fw-bold">
      <i class="bi bi-pencil-square me-2 text-primary"></i>Desiderata
    </h5>

    {#if calendari.length > 1}
      <select class="form-select form-select-sm w-auto"
              onchange={e => selezionaCalendario(+e.target.value)}>
        {#each calendari as c}
          <option value={c.id}>{NOMI_MESI[c.mese]} {c.anno}</option>
        {/each}
      </select>
    {:else if calCorrente}
      <span class="badge bg-primary fs-6">
        {NOMI_MESI[calCorrente.mese]} {calCorrente.anno}
      </span>
    {/if}

    {#if calCorrente?.deadline_personale || calCorrente?.deadline_globale}
      <span class="badge bg-secondary">
        <i class="bi bi-clock me-1"></i>Deadline:
        {(calCorrente.deadline_personale ?? calCorrente.deadline_globale).slice(0,10)}
      </span>
    {/if}

    {#if calCorrente?.desiderata_congelati}
      <span class="badge bg-danger">
        <i class="bi bi-lock-fill me-1"></i>Congelati — sola lettura
      </span>
    {/if}

    {#if $userStore?.escluso_turni}
      <span class="badge bg-secondary">
        <i class="bi bi-person-slash me-1"></i>Escluso dai turni — sola lettura
      </span>
    {/if}

    <!-- Bulk clear toolbar (solo propria riga) -->
    {#if canEdit && selectedDays.size > 0}
      <button class="btn btn-sm btn-outline-danger" onclick={bulkClearDays}>
        <i class="bi bi-trash me-1"></i>Svuota {selectedDays.size} cell{selectedDays.size === 1 ? 'a' : 'e'}
      </button>
    {/if}

    <!-- Toggle trasposizione -->
    {#if calId}
      <button class="btn btn-sm btn-outline-secondary ms-auto"
              onclick={toggleTrasposto}
              title="Inverti righe e colonne">
        <i class="bi bi-arrow-left-right me-1"></i>{trasposto ? 'Giorni su righe' : 'Giorni su colonne'}
      </button>
    {/if}

    <!-- Privacy (propria riga, visibile a tutti) -->
    {#if calId}
      <div class="d-flex align-items-center gap-2">
        <label class="small mb-0 text-muted" title="Come vedono i colleghi i tuoi desiderata">
          <i class="bi bi-shield-lock me-1"></i>Privacy
        </label>
        <select class="form-select form-select-sm w-auto"
                value={meOffusca}
                onchange={e => cambiaPrivacy(parseInt(e.target.value))}>
          <option value={0}>Nessuna</option>
          <option value={1}>Maschera assenze</option>
          <option value={2}>Nascondi tutto</option>
        </select>
      </div>
    {/if}

    <!-- Ordinamento (manager/admin) -->
    {#if isPrivileged && calId}
      <div class="d-flex align-items-center gap-2">
        <label class="small mb-0 text-muted">Ordine</label>
        <select class="form-select form-select-sm w-auto"
                value={modalita}
                onchange={e => cambiaModalita(e.target.value)}>
          <option value="manuale">Manuale</option>
          <option value="alfabetico_globale">Alfabetico globale</option>
          <option value="alfabetico_intragruppo">Alfabetico intragruppo</option>
        </select>
        {#if modalita === 'manuale'}
          <button class="btn btn-sm {riordinoOn ? 'btn-warning' : 'btn-outline-warning'}"
                  onclick={() => riordinoOn = !riordinoOn}
                  title="Attiva/disattiva modalità riordino">
            <i class="bi bi-arrows-move"></i>
          </button>
        {/if}
      </div>
    {/if}
  </div>

  {#if msgErr}
    <div class="alert alert-danger alert-dismissible py-2">
      {msgErr}
      <button type="button" class="btn-close" onclick={() => msgErr = ''}></button>
    </div>
  {/if}

  {#if loading}
    <div class="text-center py-5"><div class="spinner-border text-primary"></div></div>
  {:else if !calendari.length}
    <div class="alert alert-info">Nessun calendario aperto al momento.</div>
  {:else if !utenti.length}
    <div class="alert alert-warning">Nessun utente attivo nella struttura.</div>
  {:else if !trasposto}
    <!-- ═════════════════════════════════════════════════════════
         ORIENTAMENTO DEFAULT: utenti-righe × giorni-colonne
         ═════════════════════════════════════════════════════════ -->
    <div class="table-responsive des-wrap">
      <table class="table table-bordered table-sm align-middle small desiderata-grid">
        <thead>
          <!-- Header 1: numeri giorno -->
          <tr>
            <th class="des-cell-label" style="min-width:60px">Sigla</th>
            {#each giorni as g (g.giorno)}
              <th class="des-g {dayClass(g.giorno)}">
                <div class="fw-bold">{g.giorno}</div>
                <div class="des-dow">{dayName(g.giorno)}</div>
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each userGroups as ug (ug.key)}
            {@const sgCss = sgBlockStyle(ug.sovragruppo_id)}
            {@const sgRepeat = !!(sgStyleMap[ug.sovragruppo_id]?.['--repeatName'])}
            {@const canReorderSg = isPrivileged && riordinoOn && modalita === 'manuale' && ug.sovragruppo_id != null}
            {#if sgRepeat}
              <tr class="des-sg-row">
                <td class="des-cell-label des-sg-repeat" style={sgCss} colspan={numGiorni + 1}>
                  <div class="sep-repeat">
                    <span>
                      {ug.sg_sigla ?? '—'}
                      {#if canReorderSg}
                        <button class="btn btn-link btn-sm p-0 ms-1" title="Sposta SG su"
                                onclick={() => spostaSovragruppo(ug.sovragruppo_id, -1)}>
                          <i class="bi bi-chevron-up"></i>
                        </button>
                        <button class="btn btn-link btn-sm p-0" title="Sposta SG giù"
                                onclick={() => spostaSovragruppo(ug.sovragruppo_id, 1)}>
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
                  {#if ug.sg_sigla}
                    <span class="sg-label">{ug.sg_sigla}</span>
                    {#if canReorderSg}
                      <div class="d-inline-flex ms-1">
                        <button class="btn btn-link btn-sm p-0 me-1" title="Sposta SG su"
                                onclick={() => spostaSovragruppo(ug.sovragruppo_id, -1)}>
                          <i class="bi bi-chevron-up"></i>
                        </button>
                        <button class="btn btn-link btn-sm p-0" title="Sposta SG giù"
                                onclick={() => spostaSovragruppo(ug.sovragruppo_id, 1)}>
                          <i class="bi bi-chevron-down"></i>
                        </button>
                      </div>
                    {/if}
                  {:else}
                    <span class="text-muted">—</span>
                  {/if}
                </td>
                <td class="des-sg-spacer" style={sgCss} colspan={numGiorni}></td>
              </tr>
            {/if}
            {#each ug.users as u (u.id)}
              {@const isMe = u.id === meId}
              <tr class="des-user-row {isMe ? 'user-me' : ''}">
                <td class="des-cell-label user-sigla {isMe ? 'user-me' : ''}">
                  <span>{u.sigla}</span>
                  {#if isPrivileged && riordinoOn && modalita === 'manuale'}
                    <span class="ms-1">
                      <button class="btn btn-link btn-sm p-0 me-1" title="Sposta su"
                              onclick={() => spostaUtente(u.id, -1)}>
                        <i class="bi bi-chevron-up"></i>
                      </button>
                      <button class="btn btn-link btn-sm p-0" title="Sposta giù"
                              onclick={() => spostaUtente(u.id, 1)}>
                        <i class="bi bi-chevron-down"></i>
                      </button>
                    </span>
                  {/if}
                </td>
                {#each giorni as g (g.giorno)}
                  {@const cell = desMap[u.id]?.[g.giorno]}
                  {@const editable = isMe && canEdit}
                  {@const focused = editable && focusedGiorno === g.giorno}
                  <td class="{cellClass(u.id, g.giorno)} {dayClass(g.giorno)}"
                      onpointerdown={editable ? e => onCellPointerDown(e, g.giorno) : null}>
                    {#if editable}
                      <CellEditor
                        options={cellOptions}
                        value={String(cell?.tipo_richiesta_id ?? '')}
                        focused={focused}
                        onchange={v => salva(g.giorno, v ? +v : null)}
                        onfocusrequest={() => { focusedGiorno = g.giorno; selAnchorDay = g.giorno; }}
                        onkeynavigation={moveFocus}
                        onshiftnavigation={extendSelection}
                        onconfirm={() => onCellConfirm(g.giorno)}
                      />
                      {#if saveStatus[g.giorno] === 'saving'}
                        <span class="save-badge text-secondary"><i class="bi bi-hourglass-split"></i></span>
                      {:else if saveStatus[g.giorno] === 'ok'}
                        <span class="save-badge text-success"><i class="bi bi-check-lg"></i></span>
                      {:else if saveStatus[g.giorno] === 'err'}
                        <span class="save-badge text-danger"><i class="bi bi-x-lg"></i></span>
                      {/if}
                    {:else}
                      <span class="cell-val" title={cell?.note ?? ''}>{cell?.req_sigla ?? ''}</span>
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
    <!-- ═════════════════════════════════════════════════════════
         ORIENTAMENTO TRASPOSTO: giorni-righe × utenti-colonne
         ═════════════════════════════════════════════════════════ -->
    <div class="table-responsive des-wrap">
      <table class="table table-bordered table-sm align-middle small desiderata-grid">
        <thead>
          <!-- Header 1: sovragruppi con colspan -->
          <tr class="sg-row">
            <th class="des-cell-label" style="width:45px"></th>
            <th class="des-cell-label" style="width:45px"></th>
            {#each userGroups as ug (ug.key)}
              <th colspan={ug.count} class="text-center sg-header"
                  style={sgBlockStyle(ug.sovragruppo_id)}
                  title={ug.sg_nome ?? ''}>
                {#if ug.sg_sigla}
                  <span class="sg-label">{ug.sg_sigla}</span>
                  {#if isPrivileged && riordinoOn && modalita === 'manuale' && ug.sovragruppo_id != null}
                    <button class="btn btn-link p-0 ms-1" title="Sposta SG a sinistra"
                            onclick={() => spostaSovragruppo(ug.sovragruppo_id, -1)}>
                      <i class="bi bi-chevron-left"></i>
                    </button>
                    <button class="btn btn-link p-0" title="Sposta SG a destra"
                            onclick={() => spostaSovragruppo(ug.sovragruppo_id, 1)}>
                      <i class="bi bi-chevron-right"></i>
                    </button>
                  {/if}
                {:else}
                  <span class="text-muted small">—</span>
                {/if}
              </th>
            {/each}
          </tr>
          <!-- Header 2: sigla utenti -->
          <tr class="user-row table-primary">
            <th class="text-center des-cell-label">Gg</th>
            <th class="text-center des-cell-label"></th>
            {#each utenti as u (u.id)}
              <th class="text-center user-th {u.id === meId ? 'user-me' : ''}">
                {u.sigla}
                {#if isPrivileged && riordinoOn && modalita === 'manuale'}
                  <div class="d-flex justify-content-center gap-1 mt-1">
                    <button class="btn btn-link p-0" title="Sposta a sinistra"
                            onclick={() => spostaUtente(u.id, -1)}>
                      <i class="bi bi-chevron-left"></i>
                    </button>
                    <button class="btn btn-link p-0" title="Sposta a destra"
                            onclick={() => spostaUtente(u.id, 1)}>
                      <i class="bi bi-chevron-right"></i>
                    </button>
                  </div>
                {/if}
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each giorni as g (g.giorno)}
            {@const dc = dayClass(g.giorno)}
            <tr class={dc}>
              <td class="text-center fw-bold des-cell-label {dc}">{g.giorno}</td>
              <td class="text-center text-muted des-cell-label {dc}">{dayName(g.giorno)}</td>
              {#each utenti as u (u.id)}
                {@const cell = desMap[u.id]?.[g.giorno]}
                {@const isMe = u.id === meId}
                {@const editable = isMe && canEdit}
                {@const focused = editable && focusedGiorno === g.giorno}
                <td class="{cellClass(u.id, g.giorno)} {dc}"
                    onpointerdown={editable ? e => onCellPointerDown(e, g.giorno) : null}>
                  {#if editable}
                    <CellEditor
                      options={cellOptions}
                      value={String(cell?.tipo_richiesta_id ?? '')}
                      focused={focused}
                      onchange={v => salva(g.giorno, v ? +v : null)}
                      onfocusrequest={() => { focusedGiorno = g.giorno; selAnchorDay = g.giorno; }}
                      onkeynavigation={moveFocus}
                      onshiftnavigation={extendSelection}
                      onconfirm={() => onCellConfirm(g.giorno)}
                    />
                    {#if saveStatus[g.giorno] === 'saving'}
                      <span class="save-badge text-secondary"><i class="bi bi-hourglass-split"></i></span>
                    {:else if saveStatus[g.giorno] === 'ok'}
                      <span class="save-badge text-success"><i class="bi bi-check-lg"></i></span>
                    {:else if saveStatus[g.giorno] === 'err'}
                      <span class="save-badge text-danger"><i class="bi bi-x-lg"></i></span>
                    {/if}
                  {:else}
                    <span class="cell-val" title={cell?.note ?? ''}>{cell?.req_sigla ?? ''}</span>
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

<style>
  /* ══════════════════════════════════════════════════════════════
     STILE GRIGLIA DESIDERATA — unificato /basic e /manager WD/Originali
     ══════════════════════════════════════════════════════════════ */
  .desiderata-grid       { border-collapse: separate; border-spacing: 0; }
  .desiderata-grid th,
  .desiderata-grid td    { padding: 2px 4px; vertical-align: middle; }

  /* Celle label (sigla utente, numero giorno) */
  .des-cell-label        { background: #f8f9fa; white-space: nowrap; font-weight: 600; }

  /* Header giorno (trasposto: header SG con colspan, normale: numero giorno) */
  .des-g                 { text-align: center; background: #f8f9fa; }
  .des-dow               { font-size: .58rem; color: #666; }

  /* Riga sovragruppo (orientamento normale) */
  .des-sg-row .sg-label-cell { background: #e9ecef; font-weight: 700; }
  .des-sg-spacer         { background: #e9ecef; }
  .sg-label              { font-weight: bold; }
  /* Riga SG con "ripeti nome" (stile uguale a griglia turni) */
  tr.des-sg-row td.des-sg-repeat {
    background: #e9ecef; font-weight: 700;
    position: sticky; left: 0; z-index: 10;
    padding: 2px 8px !important;
  }
  tr.des-sg-row td.des-sg-repeat .sep-repeat { display: flex; justify-content: space-around; }

  /* Header SG orizzontale (orientamento trasposto) */
  .sg-row th.sg-header   { background: #e9ecef; font-weight: 600; border-bottom: 2px solid #6c757d; }

  /* Header utenti (trasposto) */
  .user-th               { position: relative; }
  .user-th .btn-link     { color: #fff; line-height: 1; font-size: .85rem; }
  .sg-row .btn-link      { color: #0d6efd; line-height: 1; font-size: .85rem; }
  .des-user-row .btn-link { color: #0d6efd; line-height: 1; font-size: .75rem; }

  /* Utente corrente evidenziato in rosa (sigla + riga/colonna) */
  .user-me               { background: #f8d7da !important; }
  .cell-me               { background: rgba(248, 215, 218, .45); }
  .user-sigla.user-me    { background: #f8d7da; }

  /* Celle: lavorativo (verde tenue) e assenza (rosso con bordo) */
  .des-working           { background-color: #d1e7dd; }
  .des-notworking        { outline: 2px solid #dc3545; outline-offset: -2px; background-color: #f8d7da; }

  /* Selezione multipla (solo propria riga) */
  .des-selected          { outline: 2px solid #0d6efd; outline-offset: -2px; background-color: #cfe2ff; }
  .gc-focused            { outline: 2px solid #198754; outline-offset: -2px; }

  /* Tipologia giorno — stessi CSS vars di /manager griglia turni */
  .gc-fest               { background-color: var(--gc-festivi-bg, #fff3cd); }
  .gc-super              { background-color: var(--gc-superfestivi-bg, #f8d7da); }
  td.des-cell.gc-fest    { background-color: color-mix(in srgb, var(--gc-festivi-bg, #fff3cd) 60%, transparent); }
  td.des-cell.gc-super   { background-color: color-mix(in srgb, var(--gc-superfestivi-bg, #f8d7da) 60%, transparent); }

  /* Cella base */
  .des-cell              { position: relative; text-align: center; min-width: 42px; }
  .cell-val              { display: inline-block; min-width: 1em; font-weight: 600; }
  .save-badge            { position: absolute; right: 2px; top: 2px; font-size: .7rem; }

  /* Wrap scrollabile */
  .des-wrap              { max-height: calc(100vh - 130px); overflow: auto; }
</style>
