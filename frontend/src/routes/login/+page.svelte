<script>
  import { onMount } from 'svelte';
  import { login, loginMaster } from '$lib/auth.js';

  let username = '';
  let password = '';
  let errore   = '';
  let loading  = false;

  // Tenant selection
  let tenantSlug   = '';
  let tenantList   = [];
  let dropdownMode = false;
  let loadingTenants = true;
  let masterMode   = false;

  onMount(async () => {
    try {
      const res = await fetch('/api/auth/tenants');
      const data = await res.json();
      dropdownMode   = data.dropdown === true;
      tenantList     = data.tenants || [];
      if (dropdownMode && tenantList.length > 0) {
        tenantSlug = tenantList[0].slug;
      }
    } catch {
      dropdownMode = false;
    }
    loadingTenants = false;
  });

  async function handleSubmit() {
    errore = '';

    if (masterMode) {
      if (!username || !password) {
        errore = 'Inserisci username e password.';
        return;
      }
      loading = true;
      const res = await loginMaster(username, password);
      if (!res.ok) errore = res.errore ?? 'Errore di login.';
      loading = false;
      return;
    }

    if (!tenantSlug) {
      errore = 'Seleziona un\'organizzazione.';
      return;
    }
    if (!username || !password) {
      errore = 'Inserisci username e password.';
      return;
    }
    loading = true;
    const res = await login(username, password, tenantSlug);
    if (!res.ok) errore = res.errore ?? 'Errore di login.';
    loading = false;
  }
</script>

<div class="min-vh-100 d-flex align-items-center justify-content-center bg-light">
  <div class="card shadow" style="width: 400px">
    <div class="card-body p-4">
      <div class="text-center mb-4">
        <i class="bi bi-calendar3 text-primary" style="font-size: 2.5rem"></i>
        <h4 class="mt-2 mb-0 fw-bold">Turnificator</h4>
        <small class="text-muted">
          {masterMode ? 'Accesso Master Admin' : 'Gestione turni'}
        </small>
      </div>

      <form on:submit|preventDefault={handleSubmit}>
        <!-- Tenant selector (solo in modalita' tenant) -->
        {#if !masterMode}
          {#if loadingTenants}
            <div class="mb-3 text-center">
              <span class="spinner-border spinner-border-sm text-muted"></span>
              <small class="text-muted ms-1">Caricamento...</small>
            </div>
          {:else if dropdownMode && tenantList.length > 0}
            <div class="mb-3">
              <label class="form-label fw-semibold" for="tenant">Organizzazione</label>
              <select
                id="tenant"
                class="form-select"
                bind:value={tenantSlug}
              >
                {#each tenantList as t}
                  <option value={t.slug}>{t.nome}</option>
                {/each}
              </select>
            </div>
          {:else}
            <div class="mb-3">
              <label class="form-label fw-semibold" for="tenant">Organizzazione</label>
              <input
                id="tenant"
                class="form-control"
                bind:value={tenantSlug}
                placeholder="slug organizzazione"
              />
            </div>
          {/if}
        {/if}

        <div class="mb-3">
          <label class="form-label fw-semibold" for="username">Username</label>
          <input
            id="username"
            class="form-control"
            bind:value={username}
            autocomplete="username"
            placeholder="nome.utente"
          />
        </div>

        <div class="mb-3">
          <label class="form-label fw-semibold" for="password">Password</label>
          <input
            id="password"
            type="password"
            class="form-control"
            bind:value={password}
            autocomplete="current-password"
          />
        </div>

        {#if errore}
          <div class="alert alert-danger py-2 small">{errore}</div>
        {/if}

        <button type="submit" class="btn btn-primary w-100" disabled={loading}>
          {#if loading}
            <span class="spinner-border spinner-border-sm me-2"></span>
          {/if}
          Accedi
        </button>
      </form>

      <!-- Toggle master mode -->
      <div class="text-center mt-3">
        <button
          class="btn btn-link btn-sm text-muted p-0"
          on:click={() => { masterMode = !masterMode; errore = ''; }}
        >
          {masterMode ? 'Torna al login tenant' : 'Accesso Master Admin'}
        </button>
      </div>
    </div>
  </div>
</div>
