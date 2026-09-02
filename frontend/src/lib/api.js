/**
 * lib/api.js — client HTTP per le API Flask.
 *
 * Tutte le funzioni aggiungono automaticamente l'header Authorization
 * con il token JWT dalla sessione corrente.
 */

import { getToken, logout, refreshToken } from './auth.js';
import { goto } from '$app/navigation';

// ---------------------------------------------------------------------------
// Helper base
// ---------------------------------------------------------------------------

async function request(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  const tok = getToken();
  if (tok) headers['Authorization'] = `Bearer ${tok}`;

  const opts = { method, headers };
  if (body !== undefined) opts.body = JSON.stringify(body);

  const res = await fetch(path, opts);

  // Token scaduto o non valido → logout forzato
  if (res.status === 401) {
    logout();
    goto('/login');
    return { ok: false, errore: 'Sessione scaduta.' };
  }

  // Sliding session: il backend rinnova il token se vicino alla scadenza
  const newToken = res.headers.get('X-New-Token');
  if (newToken) refreshToken(newToken);

  // Risposta non-JSON (es. server riavviato, errore 500 pre-handler): tratta come errore sessione
  let data;
  try {
    data = await res.json();
  } catch {
    if (res.status >= 500) {
      logout();
      goto('/login');
      return { ok: false, errore: 'Errore server. Effettua nuovamente il login.' };
    }
    return { ok: false, errore: `Errore ${res.status}` };
  }
  return data;
}

export const api = {
  get:    (path)        => request('GET',    path),
  post:   (path, body)  => request('POST',   path, body),
  put:    (path, body)  => request('PUT',    path, body),
  delete: (path, body)  => request('DELETE', path, body),
};

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export const authApi = {
    me:      () => api.get('/api/auth/me'),
    tenants: () => api.get('/api/auth/tenants'),
};

// ---------------------------------------------------------------------------
// Admin — utenti
// ---------------------------------------------------------------------------

export const adminApi = {
  getUtenti:  ()           => api.get('/api/admin/users'),
  createUser: (dati)       => api.post('/api/admin/users', dati),
  editUtente: (id, dati)   => api.put(`/api/admin/users/${id}`, dati),
  bulkEditUtenti: (user_ids, fields) => api.put('/api/admin/users/bulk', { user_ids, fields }),
  disUtente:  (id)         => api.delete(`/api/admin/users/${id}`),

  // Ordinamento desiderata (manager+admin)
  getOrdinamentoDesiderata:        () => api.get('/api/admin/ordinamento-desiderata'),
  setModalitaOrdinamentoDesiderata: (modalita) => api.put('/api/admin/ordinamento-desiderata/modalita', { modalita }),
  setOrdineSovragruppiDesiderata:   (ordine)   => api.put('/api/admin/ordinamento-desiderata/sovragruppi', { ordine }),
  setOrdineUtentiDesiderata:        (ordine)   => api.put('/api/admin/ordinamento-desiderata/utenti', { ordine }),

  getPresets:  ()          => api.get('/api/admin/struttura-presets'),
  creaPreset:  (dati)      => api.post('/api/admin/struttura-presets', dati),
  editPreset:  (id, dati)  => api.put(`/api/admin/struttura-presets/${id}`, dati),
  delPreset:   (id)        => api.delete(`/api/admin/struttura-presets/${id}`),
  duplicaPreset: (id, dati) => api.post(`/api/admin/struttura-presets/${id}/duplica`, dati),
  setPresetDefault: (id)   => api.put(`/api/admin/struttura-presets/${id}/set-default`),
  toggleTurnoStato: (pid, tid, campo, valore) => api.put(`/api/admin/struttura-presets/${pid}/turni/${tid}/toggle`, { campo, valore }),

  // Struttura preset normalizzata (nuove tabelle sovragruppi/gruppi/preset_turni)
  getStrutturaPreset:   (id)       => api.get(`/api/admin/struttura-presets/${id}/struttura`),
  salvaStrutturaPreset: (id, dati) => api.put(`/api/admin/struttura-presets/${id}/struttura`, dati),

  // Stile preset — salvataggio singolo + undo
  salvaStyleItem: (id, items) => api.put(`/api/admin/struttura-presets/${id}/style-item`, { items }),
  undoStyle:      (id)        => api.post(`/api/admin/struttura-presets/${id}/style-undo`, {}),

  // Appearance preset
  getAppearance:   (pid)       => api.get(`/api/admin/struttura-presets/${pid}/appearance`),
  salvaAppearance: (pid, data) => api.put(`/api/admin/struttura-presets/${pid}/appearance`, { appearance: data }),

  // Esclusioni turno per preset
  getEsclusioni_turno:  (pid)           => api.get(`/api/admin/struttura-presets/${pid}/esclusioni-turno`),
  addEsclTurno:         (pid, dati)     => api.post(`/api/admin/struttura-presets/${pid}/esclusioni-turno`, dati),
  updEsclTurno:         (pid, escId, eccezioni) => api.put(`/api/admin/struttura-presets/${pid}/esclusioni-turno/${escId}`, { eccezioni }),
  delEsclTurno:         (pid, escId)    => api.delete(`/api/admin/struttura-presets/${pid}/esclusioni-turno/${escId}`),

  // Tutti i gruppi (per select nelle regole conflitto)
  getGruppiAll: () => api.get('/api/admin/gruppi'),

  // Flag turno (globali)
  getFlagTurno:     ()           => api.get('/api/admin/flag-turno'),
  creaFlagTurno:    (dati)       => api.post('/api/admin/flag-turno', dati),
  editFlagTurno:    (id, dati)   => api.put(`/api/admin/flag-turno/${id}`, dati),
  delFlagTurno:     (id, opts)   => api.delete(`/api/admin/flag-turno/${id}`, opts),
  ripristinaFlagDefault: ()     => api.post('/api/admin/flag-turno/ripristina-default'),

  // Tipi qualitativo (globali)
  getTipiQualitativo:  ()          => api.get('/api/admin/tipi-qualitativo'),
  creaTipoQualitativo: (dati)       => api.post('/api/admin/tipi-qualitativo', dati),
  editTipoQualitativo: (id, dati)   => api.put(`/api/admin/tipi-qualitativo/${id}`, dati),
  delTipoQualitativo:  (id)         => api.delete(`/api/admin/tipi-qualitativo/${id}`),

  // Regole conflitto (globali)
  getRegoleConflitto: ()           => api.get('/api/admin/regole-conflitto'),
  creaRegola:         (dati)       => api.post('/api/admin/regole-conflitto', dati),
  editRegola:         (id, dati)   => api.put(`/api/admin/regole-conflitto/${id}`, dati),
  delRegola:          (id)         => api.delete(`/api/admin/regole-conflitto/${id}`),

  // Tipi richiesta (globali)
  getTipi:    ()           => api.get('/api/admin/tipi-richiesta'),
  creaTipo:   (dati)       => api.post('/api/admin/tipi-richiesta', dati),
  editTipo:   (id, dati)   => api.put(`/api/admin/tipi-richiesta/${id}`, dati),
  delTipo:    (id)         => api.delete(`/api/admin/tipi-richiesta/${id}`),
  ripristinaTipiDefault: () => api.post('/api/admin/tipi-richiesta/ripristina-default', {}),

  getCalendari:       ()           => api.get('/api/admin/calendari'),
  creaCalendario:     (dati)       => api.post('/api/admin/calendari', dati),
  editCalendario:     (id, dati)   => api.put(`/api/admin/calendari/${id}`, dati),
  statoCalendario:    (id, stato)  => api.post(`/api/admin/calendari/${id}/stato`, { stato }),
  eliminaCalendario:  (id)         => api.delete(`/api/admin/calendari/${id}`),
  riazzeraCalendario: (id)         => api.post(`/api/admin/calendari/${id}/riazzera`, {}),
  ricaricaStruttura:  (id, dati)   => api.post(`/api/admin/calendari/${id}/ricarica-struttura`, dati),
  congelaDesiderata:  (id)         => api.post(`/api/admin/calendari/${id}/congela`, {}),
  scongelaDesiderata: (id)         => api.post(`/api/admin/calendari/${id}/scongela`, {}),
  chiudiEffettivo:    (id)         => api.post(`/api/admin/calendari/${id}/chiudi-effettivo`, {}),
  riapriEffettivo:    (id)         => api.post(`/api/admin/calendari/${id}/riapri-effettivo`, {}),

  getGiorni:     (id)      => api.get(`/api/admin/calendari/${id}/giorni`),
  editGiorni:    (id, gg)  => api.put(`/api/admin/calendari/${id}/giorni`, { giorni: gg }),

  getDeadline:   (id)          => api.get(`/api/admin/calendari/${id}/deadline`),
  setDeadline:   (id, dati)    => api.put(`/api/admin/calendari/${id}/deadline`, dati),

  getConfig:  ()       => api.get('/api/admin/config'),

  // Proposte di configurazione dal master: si leggono, non si subiscono
  getProposta:     ()   => api.get('/api/admin/proposta'),
  accettaProposta: (id) => api.put(`/api/admin/proposta/${id}/accetta`, {}),
  rifiutaProposta: (id) => api.put(`/api/admin/proposta/${id}/rifiuta`, {}),

  setConfig:  (dati)   => api.put('/api/admin/config', dati),

  // Vincoli solver
  getVincoliGlobali: ()           => api.get('/api/admin/vincoli-globali'),
  setVincoliGlobali: (vincoli)    => api.put('/api/admin/vincoli-globali', { vincoli }),
  getVincoliUtente:  (uid)        => api.get(`/api/admin/vincoli-utente/${uid}`),
  setVincoliUtente:  (uid, vincoli) => api.put(`/api/admin/vincoli-utente/${uid}`, { vincoli }),
  delVincoloUtente:  (uid, chiave)  => api.delete(`/api/admin/vincoli-utente/${uid}/${chiave}`),

  // Esclusioni utente (flag-based)
  getEsclusioniUtente:  (uid)            => api.get(`/api/admin/esclusioni-utente/${uid}`),
  setEsclusioniUtente:  (uid, esclusioni) => api.put(`/api/admin/esclusioni-utente/${uid}`, { esclusioni }),
  delEsclusioneUtente:  (uid, eid)       => api.delete(`/api/admin/esclusioni-utente/${uid}/${eid}`),

  // Giorni esclusi (giorno della settimana per utente)
  getGiorniEsclusi:     (uid)            => api.get(`/api/admin/giorni-esclusi/${uid}`),
  setGiorniEsclusi:     (uid, giorni)    => api.put(`/api/admin/giorni-esclusi/${uid}`, { giorni_esclusi: giorni }),

  // Vincoli solver (flag / tipo qualitativo)
  getVincoliSolver:         ()                => api.get('/api/admin/vincoli-solver'),
  setVincoliSolver:         (vincoli)         => api.put('/api/admin/vincoli-solver', { vincoli }),
  delVincoloSolver:         (vid)             => api.delete(`/api/admin/vincoli-solver/${vid}`),
  getVincoliSolverUtente:   (uid)             => api.get(`/api/admin/vincoli-solver-utente/${uid}`),
  setVincoliSolverUtente:   (uid, vincoli)    => api.put(`/api/admin/vincoli-solver-utente/${uid}`, { vincoli }),
  delVincoloSolverUtente:   (uid, vid)        => api.delete(`/api/admin/vincoli-solver-utente/${uid}/${vid}`),

  // Riepilogo utenti solver
  getSolverUtentiRiepilogo: () => api.get('/api/admin/solver-utenti-riepilogo'),

  // Aperture straordinarie (per-calendario)
  getAperture:  (calId)          => api.get(`/api/admin/calendari/${calId}/aperture`),
  salvaAperture: (calId, aperture) => api.put(`/api/admin/calendari/${calId}/aperture`, { aperture }),

  // Accesso manager
  getAccessoManager: ()     => api.get('/api/admin/accesso-manager'),
  setAccessoUtenti:  (data) => api.put('/api/admin/accesso-manager/utenti', data),
  setAccessoTurni:   (data) => api.put('/api/admin/accesso-manager/turni', data),
  pulisciOrfaniAccesso: ()  => api.post('/api/admin/accesso-manager/pulisci-orfani'),

  // Preset ottimizzazione
  getPresetOttimizzazione:  ()          => api.get('/api/admin/preset-ottimizzazione'),
  creaPresetOttimizzazione: (dati)      => api.post('/api/admin/preset-ottimizzazione', dati),
  editPresetOttimizzazione: (id, dati)  => api.put(`/api/admin/preset-ottimizzazione/${id}`, dati),
  delPresetOttimizzazione:  (id)        => api.delete(`/api/admin/preset-ottimizzazione/${id}`),
};

// ---------------------------------------------------------------------------
// Manager
// ---------------------------------------------------------------------------

export const managerApi = {
  getCalendari: () => api.get('/api/manager/calendari'),
  getEffettivo: (id) => api.get(`/api/manager/calendari/${id}/effettivo`),

  getTipi:        ()   => api.get('/api/admin/tipi-richiesta'),
  getDesiderata:  (id) => api.get(`/api/manager/calendari/${id}/desiderata`),

  getStruttura: (id)       => api.get(`/api/manager/calendari/${id}/struttura`),
  getAssegnazioni: (id)    => api.get(`/api/manager/calendari/${id}/assegnazioni`),
  salvaAssegnazione: (id, dati) =>
    api.post(`/api/manager/calendari/${id}/assegnazioni`, dati),
  svuotaAssegnazione: (calId, assId) =>
    api.delete(`/api/manager/calendari/${calId}/assegnazioni/${assId}`),
  svuotaBatch: (calId, celle) =>
    api.post(`/api/manager/calendari/${calId}/svuota-batch`, { celle }),
  salvaBatch: (calId, celle, forza = false) =>
    api.post(`/api/manager/calendari/${calId}/salva-batch`, { celle, forza_inserimento: forza }),
  scambiaAssegnazioni: (calId, dati) =>
    api.post(`/api/manager/calendari/${calId}/scambia`, dati),

  getDisponibili: (id, turnoId, giorno, ignoraNotte = false) =>
    api.get(
      `/api/manager/calendari/${id}/disponibili` +
      `?turno_id=${turnoId}&giorno=${giorno}&ignora_notte=${ignoraNotte}`
    ),

  getWorkingDes: (id)       => api.get(`/api/manager/calendari/${id}/working-desiderata`),
  setWorkingDes: (id, dati) => api.put(`/api/manager/calendari/${id}/working-desiderata`, dati),
  svuotaBatchWd: (id, celle) => api.post(`/api/manager/calendari/${id}/working-desiderata/svuota-batch`, { celle }),
  salvaBatchWd: (id, celle) => api.post(`/api/manager/calendari/${id}/working-desiderata/salva-batch`, { celle }),
  ricaricaWd:    (id)        => api.post(`/api/manager/calendari/${id}/working-desiderata/ricarica`, {}),
  getWdHistory:  (id)        => api.get(`/api/manager/calendari/${id}/wd-history`),
  wdUndo:        (id)        => api.post(`/api/manager/calendari/${id}/wd-undo`, {}),
  wdRedo:        (id)        => api.post(`/api/manager/calendari/${id}/wd-redo`, {}),

  getOre:   (id) => api.get(`/api/manager/calendari/${id}/ore`),
  getHistory: (id) => api.get(`/api/manager/calendari/${id}/history`),
  undo: (id) => api.post(`/api/manager/calendari/${id}/undo`, {}),
  redo: (id) => api.post(`/api/manager/calendari/${id}/redo`, {}),

  setStyleCalendario: (id, style) =>
    api.put(`/api/manager/calendari/${id}/style`, { style }),
  setFormatoGruppo: (id, dati) =>
    api.put(`/api/manager/calendari/${id}/formato-gruppo`, dati),
  setFormatoSovragruppo: (id, dati) =>
    api.put(`/api/manager/calendari/${id}/formato-sovragruppo`, dati),
  setFormatoBatch: (id, items) =>
    api.put(`/api/manager/calendari/${id}/formato-batch`, { items }),

  undoStyle: (id) => api.post(`/api/manager/calendari/${id}/style-undo`, {}),

  getConteggiConfig: () => api.get('/api/manager/conteggi-config'),
  setConteggiConfig: (conteggi) => api.put('/api/manager/conteggi-config', { conteggi }),

  // Esclusioni manuali e celle bloccate
  getEsclusioni: (id) =>
    api.get(`/api/manager/calendari/${id}/esclusioni-manuali`),
  setEsclusioni: (id, esclusioni) =>
    api.put(`/api/manager/calendari/${id}/esclusioni-manuali`, { esclusioni }),
  getCelleBloccate: (id) =>
    api.get(`/api/manager/calendari/${id}/celle-bloccate`),
  setCelleBloccate: (id, celle) =>
    api.put(`/api/manager/calendari/${id}/celle-bloccate`, { celle }),

  // Snapshot per-calendario (regole + config)
  salvaRegoleSnapshot: (id, regole) =>
    api.put(`/api/manager/calendari/${id}/regole-snapshot`, { regole }),
  salvaConfigSnapshot: (id, config) =>
    api.put(`/api/manager/calendari/${id}/config-snapshot`, { config }),
  salvaAppearanceSnapshot: (id, appearance) =>
    api.put(`/api/manager/calendari/${id}/appearance-snapshot`, { appearance }),

  // Solver
  lanciaSolver: (id, opzioni) =>
    api.post(`/api/manager/calendari/${id}/solver`, opzioni),
  getSolverLog: (id) =>
    api.get(`/api/manager/calendari/${id}/solver-log`),

  // Optimizer
  ottimizza: (id, opzioni) =>
    api.post(`/api/manager/calendari/${id}/ottimizza`, opzioni),

  // Aperture straordinarie
  getAperture:  (id)          => api.get(`/api/admin/calendari/${id}/aperture`),
  salvaAperture: (id, aperture) => api.put(`/api/admin/calendari/${id}/aperture`, { aperture }),

  // Posti fissi
  getPostiFissi: (presetId)     => api.get(`/api/manager/posti-fissi/${presetId}`),
  creaPostoFisso: (presetId, d) => api.post(`/api/manager/posti-fissi/${presetId}`, d),
  aggiornaPostoFisso: (id, d)   => api.put(`/api/manager/posti-fissi/item/${id}`, d),
  eliminaPostoFisso: (id)       => api.delete(`/api/manager/posti-fissi/item/${id}`),
  applicaPostiFissi: (calId, d) => api.post(`/api/manager/calendari/${calId}/applica-posti-fissi`, d),
  azzeraAssegnazioni: (calId, d) => api.post(`/api/manager/calendari/${calId}/azzera`, d ?? {}),
};

// ---------------------------------------------------------------------------
// Basic
// ---------------------------------------------------------------------------

export const basicApi = {
  getCalendari:         ()          => api.get('/api/basic/calendari'),
  getDesiderata:        (id)        => api.get(`/api/basic/calendari/${id}/desiderata`),
  salvaDesiderata:      (id, dati)  => api.put(`/api/basic/calendari/${id}/desiderata`, dati),
  delDesiderata:        (id, giorno)=> api.delete(`/api/basic/calendari/${id}/desiderata/${giorno}`),
  getDesiderataGlobale: (id)        => api.get(`/api/basic/calendari/${id}/desiderata-globale`),
  setPrivacy:           (offusca)   => api.put('/api/basic/privacy', { offusca }),
  getPreferenze:        ()          => api.get('/api/basic/preferenze'),
  setPreferenza:        (dati)      => api.put('/api/basic/preferenze', dati),
};

// ---------------------------------------------------------------------------
// Export (fetch autenticato + download blob)
// ---------------------------------------------------------------------------

/**
 * Scarica un file via fetch con header Authorization JWT.
 * Crea un link temporaneo per triggerare il download nel browser.
 */
export async function downloadFile(url, fallbackName = 'export.xlsx') {
  const headers = {};
  const tok = getToken();
  if (tok) headers['Authorization'] = `Bearer ${tok}`;

  const res = await fetch(url, { headers });
  if (res.status === 401) {
    logout();
    goto('/login');
    return { ok: false, errore: 'Sessione scaduta.' };
  }
  if (!res.ok) {
    try {
      const json = await res.json();
      return { ok: false, errore: json.errore || `Errore ${res.status}` };
    } catch {
      return { ok: false, errore: `Errore ${res.status}` };
    }
  }

  const blob = await res.blob();
  // Estrai nome file dal Content-Disposition, se presente
  const cd = res.headers.get('Content-Disposition') || '';
  const match = cd.match(/filename[^;=\n]*=["']?([^"';\n]+)/);
  const filename = match ? match[1] : fallbackName;

  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Master Admin
// ---------------------------------------------------------------------------

export const masterApi = {
    // Auth master
    login: (username, password) =>
        request('POST', '/api/master/auth/login', { username, password }),

    /** Cambia la password dell'account master autenticato. */
    changePassword: (passwordAttuale, passwordNuova) =>
        api.post('/api/master/auth/password', {
            password_attuale: passwordAttuale,
            password_nuova: passwordNuova,
        }),

    // Tenant CRUD
    getTenants:      ()           => api.get('/api/master/tenants'),
    createTenant:    (dati)       => api.post('/api/master/tenants', dati),
    updateTenant:    (id, dati)   => api.put(`/api/master/tenants/${id}`, dati),
    deleteTenant:    (id)         => api.delete(`/api/master/tenants/${id}`),
    getTenantStats:  (id)         => api.get(`/api/master/tenants/${id}/stats`),
    resetAdminPwd:   (id)         => api.post(`/api/master/tenants/${id}/reset-admin`),
    impersonate:     (id)         => api.post(`/api/master/tenants/${id}/impersonate`),

    // Template CRUD
    getTemplates:       ()            => api.get('/api/master/templates'),
    createTemplate:     (dati)        => api.post('/api/master/templates', dati),
    updateTemplate:     (id, dati)    => api.put(`/api/master/templates/${id}`, dati),
    deleteTemplate:     (id)          => api.delete(`/api/master/templates/${id}`),
    templateFromTenant: (tenantId)    => api.post(`/api/master/templates/from-tenant/${tenantId}`),

    // Configurazione globale
    getConfig:  () => api.get('/api/master/config'),
    getConfigurazioneTenant: (id) => api.get(`/api/master/tenants/${id}/configurazione`),
    proponiConfigurazione:   (id, dati) => api.post(`/api/master/tenants/${id}/proposta`, dati),
    setConfig:  (dati) => api.put('/api/master/config', dati),

    // Audit log impersonation
    getImpersonationLog: () => api.get('/api/master/impersonation-log'),
};

// ---------------------------------------------------------------------------
// Export (fetch autenticato + download blob)
// ---------------------------------------------------------------------------

export const exportApi = {
  turni: (id, headerBg = '', headerFg = '') => {
    const params = new URLSearchParams();
    if (headerBg) params.set('header_bg', headerBg.replace('#', ''));
    if (headerFg) params.set('header_fg', headerFg.replace('#', ''));
    const qs = params.toString();
    return downloadFile(
      `/api/export/calendari/${id}/turni${qs ? '?' + qs : ''}`,
      `turni_${id}.xlsx`
    );
  },
  ore:     (id)   => downloadFile(`/api/export/calendari/${id}/ore`, `ore_${id}.xlsx`),
  annuale: (anno, escludi = []) => {
    const base = `/api/export/annuale/${anno}/ore`;
    const url = escludi.length ? `${base}?escludi=${escludi.join(',')}` : base;
    return downloadFile(url, `ore_annuali_${anno}.xlsx`);
  },
};
