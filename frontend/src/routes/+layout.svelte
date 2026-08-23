<script>
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { user, tenant, impersonated, init, logout, exitImpersonation } from '$lib/auth.js';
  import Toast from '$lib/Toast.svelte';
  import CredenzialiProvvisorie from '$lib/CredenzialiProvvisorie.svelte';
  import 'bootstrap/dist/css/bootstrap.min.css';
  import 'bootstrap-icons/font/bootstrap-icons.css';

  // Inizializza subito (prima di qualsiasi onMount dei figli)
  if (browser) init();

  let theme = 'light';

  onMount(async () => {
    await import('bootstrap/dist/js/bootstrap.bundle.min.js');
    theme = localStorage.getItem('theme') ?? 'light';
    applyTheme(theme);
  });

  function applyTheme(t) {
    document.documentElement.setAttribute('data-bs-theme', t);
    document.documentElement.setAttribute('data-theme', t);
  }

  function setTheme(t) {
    theme = t;
    localStorage.setItem('theme', t);
    applyTheme(t);
  }

  // Pagine pubbliche che non richiedono auth
  const PUBLIC_PAGES = ['/login'];

  // Guard: redirect a /login se non autenticato (tranne pagine pubbliche)
  $: if (typeof window !== 'undefined' && !PUBLIC_PAGES.includes($page.url.pathname) && !$user) {
    goto('/login');
  }

  // Naviga alla pagina corretta in base al ruolo dopo il login
  $: if ($user && $page.url.pathname === '/login') {
    const role = $user.role;
    let dest = '/login';
    if (role === 'master_admin') {
      dest = '/master';
    } else {
      dest = { admin: '/admin', manager: '/manager', basic: '/basic' }[role] ?? '/login';
    }
    goto(dest);
  }

  function handleLogout() {
    logout();
    goto('/login');
  }

  function handleExitImpersonation() {
    exitImpersonation();
    goto('/master');
  }

  /** True se siamo in una pagina /master/* */
  $: isMasterPage = $page.url.pathname.startsWith('/master');
</script>

<!-- Banner impersonation (rosso, fisso in alto) -->
{#if $impersonated && $user}
<div class="bg-danger text-white text-center py-2 px-3 d-flex align-items-center justify-content-center gap-2"
     style="position: sticky; top: 0; z-index: 1100;">
  <i class="bi bi-exclamation-triangle-fill"></i>
  <span class="fw-semibold">
    Stai operando come admin di <strong>{$tenant}</strong>
  </span>
  <button class="btn btn-sm btn-outline-light ms-2" on:click={handleExitImpersonation}>
    <i class="bi bi-box-arrow-left me-1"></i>Esci
  </button>
</div>
{/if}

<!-- Avviso credenziali di sviluppo (solo ad accesso effettuato) -->
<CredenzialiProvvisorie />

<!-- Navbar tenant (utenti normali + impersonation) -->
{#if $user && !isMasterPage && $page.url.pathname !== '/login'}
<nav class="navbar navbar-expand-md navbar-dark bg-primary sticky-top shadow-sm">
  <div class="container-fluid">
    <span class="navbar-brand fw-bold">
      <i class="bi bi-calendar3 me-2"></i>Turnificator
      {#if $tenant}
        <small class="opacity-75 ms-1">— {$tenant}</small>
      {/if}
    </span>

    <button class="navbar-toggler" type="button"
            data-bs-toggle="collapse" data-bs-target="#navMenu">
      <span class="navbar-toggler-icon"></span>
    </button>

    <div class="collapse navbar-collapse" id="navMenu">
      <ul class="navbar-nav me-auto">
        {#if $user.role === 'basic'}
          <li class="nav-item">
            <a class="nav-link" class:active={$page.url.pathname === '/basic'} href="/basic">
              <i class="bi bi-pencil-square me-1"></i>I miei desiderata
            </a>
          </li>
        {/if}
        {#if $user.role === 'manager' || $user.role === 'admin'}
          <li class="nav-item">
            <a class="nav-link" class:active={$page.url.pathname === '/manager'} href="/manager">
              <i class="bi bi-table me-1"></i>Turni
            </a>
          </li>
        {/if}
        {#if $user.role === 'manager'}
          <li class="nav-item">
            <a class="nav-link" class:active={$page.url.pathname === '/admin'} href="/admin">
              <i class="bi bi-calendar-check me-1"></i>Gestione
            </a>
          </li>
        {/if}
        {#if $user.role === 'admin'}
          <li class="nav-item">
            <a class="nav-link" class:active={$page.url.pathname === '/admin'} href="/admin">
              <i class="bi bi-gear-fill me-1"></i>Admin
            </a>
          </li>
        {/if}
        <!-- Manuale: visibile a tutti i ruoli; la pagina filtra le sezioni -->
        <li class="nav-item">
          <a class="nav-link" class:active={$page.url.pathname === '/manuale'} href="/manuale">
            <i class="bi bi-book me-1"></i>Manuale
          </a>
        </li>
      </ul>

      <ul class="navbar-nav align-items-center">
        <!-- Theme toggle -->
        <li class="nav-item d-flex align-items-center me-3 gap-1">
          <span class="text-white-50 small">theme:</span>
          <button class="btn btn-sm py-0 px-2 {theme==='light'?'btn-light':'btn-outline-light'}"
                  on:click={() => setTheme('light')}>light</button>
          <span class="text-white-50">|</span>
          <button class="btn btn-sm py-0 px-2 {theme==='dark'?'btn-light':'btn-outline-light'}"
                  on:click={() => setTheme('dark')}>dark</button>
        </li>

        <li class="nav-item dropdown">
          <a class="nav-link dropdown-toggle" href="#" role="button"
             data-bs-toggle="dropdown">
            <i class="bi bi-person-circle me-1"></i>{$user.sigla || $user.username}
            <span class="badge bg-light text-primary ms-1">{$user.role}</span>
          </a>
          <ul class="dropdown-menu dropdown-menu-end">
            <li>
              <button class="dropdown-item text-danger" on:click={handleLogout}>
                <i class="bi bi-box-arrow-right me-2"></i>Logout
              </button>
            </li>
          </ul>
        </li>
      </ul>
    </div>
  </div>
</nav>
{/if}

<!-- Navbar master admin (pagine /master/*) -->
{#if $user && $user.role === 'master_admin' && isMasterPage && !$impersonated}
<nav class="navbar navbar-expand-md navbar-dark bg-dark sticky-top shadow-sm">
  <div class="container-fluid">
    <span class="navbar-brand fw-bold">
      <i class="bi bi-shield-lock me-2"></i>Turnificator
      <small class="opacity-75 ms-1">— Master Admin</small>
    </span>

    <button class="navbar-toggler" type="button"
            data-bs-toggle="collapse" data-bs-target="#navMaster">
      <span class="navbar-toggler-icon"></span>
    </button>

    <div class="collapse navbar-collapse" id="navMaster">
      <ul class="navbar-nav me-auto">
        <li class="nav-item">
          <a class="nav-link" class:active={$page.url.pathname === '/master'} href="/master">
            <i class="bi bi-building me-1"></i>Tenant
          </a>
        </li>
        <li class="nav-item">
          <a class="nav-link" class:active={$page.url.pathname === '/master/templates'} href="/master/templates">
            <i class="bi bi-file-earmark-code me-1"></i>Template
          </a>
        </li>
        <li class="nav-item">
          <a class="nav-link" class:active={$page.url.pathname === '/master/audit'} href="/master/audit">
            <i class="bi bi-journal-text me-1"></i>Audit Log
          </a>
        </li>
        <li class="nav-item">
          <a class="nav-link" class:active={$page.url.pathname === '/master/config'} href="/master/config">
            <i class="bi bi-sliders me-1"></i>Config
          </a>
        </li>
        <li class="nav-item">
          <a class="nav-link" class:active={$page.url.pathname === '/manuale'} href="/manuale">
            <i class="bi bi-book me-1"></i>Manuale
          </a>
        </li>
      </ul>

      <ul class="navbar-nav align-items-center">
        <li class="nav-item d-flex align-items-center me-3 gap-1">
          <span class="text-white-50 small">theme:</span>
          <button class="btn btn-sm py-0 px-2 {theme==='light'?'btn-light':'btn-outline-light'}"
                  on:click={() => setTheme('light')}>light</button>
          <span class="text-white-50">|</span>
          <button class="btn btn-sm py-0 px-2 {theme==='dark'?'btn-light':'btn-outline-light'}"
                  on:click={() => setTheme('dark')}>dark</button>
        </li>

        <li class="nav-item dropdown">
          <a class="nav-link dropdown-toggle" href="#" role="button"
             data-bs-toggle="dropdown">
            <i class="bi bi-person-circle me-1"></i>{$user.username}
            <span class="badge bg-warning text-dark ms-1">master</span>
          </a>
          <ul class="dropdown-menu dropdown-menu-end">
            <li>
              <button class="dropdown-item text-danger" on:click={handleLogout}>
                <i class="bi bi-box-arrow-right me-2"></i>Logout
              </button>
            </li>
          </ul>
        </li>
      </ul>
    </div>
  </div>
</nav>
{/if}

<slot />
<Toast />

<style>
  /* ── Context menu CSS variables (light defaults) ── */
  :global(:root) {
    --ctx-bg: #fff;
    --ctx-fg: #212529;
    --ctx-border: #ccc;
    --ctx-sep: #eee;
    --ctx-bar: #f8f9fa;
    --ctx-hover: #e8f0fe;
    --ctx-muted: #999;
    --ctx-shadow: rgba(0,0,0,.15);
    --ctx-btn-border: #ccc;
    --ctx-tbl-border: #dee2e6;
    --ctx-current: #d1e7dd;
  }
  :global([data-theme="dark"]) {
    --ctx-bg: #1e1e2e;
    --ctx-fg: #cdd6f4;
    --ctx-border: #45475a;
    --ctx-sep: #45475a;
    --ctx-bar: #2d2d44;
    --ctx-hover: #313244;
    --ctx-muted: #7f849c;
    --ctx-shadow: rgba(0,0,0,.4);
    --ctx-btn-border: #585b70;
    --ctx-tbl-border: #45475a;
    --ctx-current: #1a3a2a;
  }

  /* ── Dark mode overrides per classi custom dell'app ── */

  :global([data-theme="dark"] .struttura-list)    { background: #1e1e2e !important; }
  :global([data-theme="dark"] .stru-sg)           { background: #2d2d44 !important; color: #cdd6f4; }
  :global([data-theme="dark"] .stru-g)            { background: #252538 !important; color: #cdd6f4; }
  :global([data-theme="dark"] .stru-t)            { background: #1e1e2e !important; color: #cdd6f4; }
  :global([data-theme="dark"] .stru-form-g)       { background: #1a3a2a !important; }
  :global([data-theme="dark"] .stru-form-t)       { background: #1a2a3e !important; }
  :global([data-theme="dark"] .stru-add-sg)       { background: #252538 !important; }
  :global([data-theme="dark"] .stru-g[draggable="true"]:hover),
  :global([data-theme="dark"] .stru-t[draggable="true"]:hover) { background: #2a2a50 !important; }
  :global([data-theme="dark"] .stru-sg[draggable="true"]:hover){ background: #383858 !important; }

  :global([data-theme="dark"] .text-dark)         { color: #cdd6f4 !important; }
  :global([data-theme="dark"] .btn-link)          { color: #89b4fa !important; }
  :global([data-theme="dark"] .border-bottom)     { border-color: #383858 !important; }
  :global([data-theme="dark"] .border-top)        { border-color: #383858 !important; }

  /* ── Manager: griglia turni (sfondo chiaro per preservare le evidenziature) ── */
  :global([data-theme="dark"] td.col-turno)       { background: #d8e0ff !important; color: #1a1a1a; }
  :global([data-theme="dark"] th.col-turno)       { background: #0d6efd !important; color: #fff; }
  :global([data-theme="dark"] td.cella)           { background: #ffffff; }

  :global([data-theme="dark"] select.cell-sel) {
    background: #ffffff !important;
    color: #1a1a1a;
  }
  :global([data-theme="dark"] select.cell-sel:focus) {
    background: #e8f0fe !important;
    outline: 2px solid #89b4fa;
  }
  :global([data-theme="dark"] select.cell-sel option) {
    background: #ffffff;
    color: #1a1a1a;
  }

  :global([data-theme="dark"] th.col-g)           { background: #ffffff !important; color: #1a1a1a; }
  :global([data-theme="dark"] .gc-super)          { background: #fad7d7 !important; color: #1a1a1a; }
  :global([data-theme="dark"] .gc-fest)           { background: #fef3cd !important; color: #1a1a1a; }

  /* ── Manager: griglia desiderata ── */
  :global([data-theme="dark"] td.des-cell-label)  { background: #1e1e2e !important; color: #cdd6f4; }
  :global([data-theme="dark"] th.des-cell-label)  { background: #0d6efd !important; color: #fff; }

  :global([data-theme="dark"] .des-working)       { background: #0d2b1a !important; color: #a3e4b8; }
  :global([data-theme="dark"] .des-notworking)    { background: #2b2500 !important; color: #f0d060; }

  :global([data-theme="dark"] select.des-sel) {
    background: #252538 !important;
    color: #cdd6f4;
  }
  :global([data-theme="dark"] select.des-sel[data-tipo="lavorativo"]) {
    background: #0d2b1a !important;
    color: #a3e4b8;
  }
  :global([data-theme="dark"] select.des-sel[data-tipo="assenza"]) {
    background: #2b2500 !important;
    color: #f0d060;
  }
  :global([data-theme="dark"] select.des-sel:focus) {
    background: #2a3a5e !important;
    outline: 2px solid #89b4fa;
  }
  :global([data-theme="dark"] select.des-sel option) {
    background: #252538;
    color: #cdd6f4;
  }

  /* ── Prima colonna turno: evidenziata in entrambi i temi ── */
  :global(td.col-turno)                           { background: #eef2ff !important; color: #1a1a1a; }

  /* ── Bordi sottili: light e dark ── */
  :global(.table-bordered > :not(caption) > * > *) {
    border-width: 0.5px;
    border-color: #d0d0d0;
  }

  /* ── Tabelle generali dark ── */
  :global([data-theme="dark"] .table) {
    --bs-table-bg: #1e1e2e;
    --bs-table-border-color: #d8d8d8;
    color: #cdd6f4;
  }
  :global([data-theme="dark"] .table-bordered > :not(caption) > * > *) {
    border-color: #d8d8d8;
    border-width: 0.25px;
  }

  /* ── Toolbar sticky ── */
  :global([data-theme="dark"] .bg-white)          { background: #1e1e2e !important; }
  :global([data-theme="dark"] .bg-light)          { background: #252538 !important; }
  :global([data-theme="dark"] .alert-light)       { background: #252538 !important; border-color: #383858 !important; color: #cdd6f4 !important; }
</style>
