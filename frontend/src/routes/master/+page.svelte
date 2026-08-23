<script>
    /**
     * Master Admin — Dashboard tenant.
     *
     * Lista tenant con stato, statistiche, azioni (modifica, impersona,
     * reset password admin, disattiva). Form creazione nuovo tenant.
     *
     * Feature: creazione tenant da template, impersonation con redirect.
     */

    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { masterApi } from '$lib/api.js';
    import { user, setImpersonation } from '$lib/auth.js';

    let tenants = [];
    let templates = [];
    let loading = true;
    let errore = '';
    let successo = '';

    // Form nuovo tenant
    let showForm = false;
    let formNome = '';
    let formSlug = '';
    let formTemplateId = '';
    let formAdminUser = 'admin';
    let formLoading = false;
    let formErrore = '';

    // Edit inline
    let editId = null;
    let editNome = '';
    let editVisibile = true;

    // Stats espanse
    let statsId = null;
    let stats = null;
    let statsLoading = false;

    onMount(async () => {
        if (!$user || $user.role !== 'master_admin') {
            goto('/login');
            return;
        }
        await caricaDati();
    });

    async function caricaDati() {
        loading = true;
        errore = '';
        try {
            const [tRes, tmplRes] = await Promise.all([
                masterApi.getTenants(),
                masterApi.getTemplates(),
            ]);
            if (tRes.ok !== false) tenants = tRes.tenants || tRes;
            if (tmplRes.ok !== false) templates = tmplRes.templates || tmplRes;
        } catch (e) {
            errore = 'Errore caricamento dati.';
        }
        loading = false;
    }

    /** Auto-genera slug da nome. */
    function autoSlug(nome) {
        return nome
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-|-$/g, '')
            .substring(0, 50);
    }

    $: if (formNome && !formSlug) {
        formSlug = autoSlug(formNome);
    }

    async function creaTenant() {
        formErrore = '';
        if (!formNome.trim() || !formSlug.trim()) {
            formErrore = 'Nome e slug sono obbligatori.';
            return;
        }
        formLoading = true;
        const body = {
            nome: formNome.trim(),
            slug: formSlug.trim(),
            admin_username: formAdminUser.trim() || 'admin',
        };
        if (formTemplateId) body.template_id = parseInt(formTemplateId);

        const res = await masterApi.createTenant(body);
        formLoading = false;

        if (res.ok === false) {
            formErrore = res.errore || 'Errore creazione tenant.';
            return;
        }

        successo = `Tenant "${formNome}" creato. Password admin: ${res.admin_password || '(vedi log server)'}`;
        formNome = '';
        formSlug = '';
        formTemplateId = '';
        formAdminUser = 'admin';
        showForm = false;
        await caricaDati();
    }

    function iniziaEdit(t) {
        editId = t.id;
        editNome = t.nome;
        editVisibile = t.visibile_login === 1;
    }

    async function salvaEdit(t) {
        const res = await masterApi.updateTenant(t.id, {
            nome: editNome,
            visibile_login: editVisibile ? 1 : 0,
        });
        if (res.ok === false) {
            errore = res.errore || 'Errore modifica.';
        }
        editId = null;
        await caricaDati();
    }

    async function toggleAttivo(t) {
        if (t.is_active) {
            if (!confirm(`Disattivare il tenant "${t.nome}"?`)) return;
            await masterApi.deleteTenant(t.id);
        } else {
            await masterApi.updateTenant(t.id, { is_active: 1 });
        }
        await caricaDati();
    }

    async function resetPassword(t) {
        if (!confirm(`Reset password admin di "${t.nome}"?`)) return;
        const res = await masterApi.resetAdminPwd(t.id);
        if (res.ok === false) {
            errore = res.errore || 'Errore reset.';
        } else {
            successo = `Nuova password admin di "${t.nome}": ${res.new_password || '(vedi log)'}`;
        }
    }

    async function impersona(t) {
        if (!confirm(`Entrare come admin di "${t.nome}"?`)) return;
        const res = await masterApi.impersonate(t.id);
        if (res.ok === false) {
            errore = res.errore || 'Errore impersonation.';
            return;
        }
        setImpersonation({
            token: res.token,
            user: res.user,
            tenant: res.tenant,
        });
        goto('/admin');
    }

    async function mostraStats(t) {
        if (statsId === t.id) { statsId = null; return; }
        statsId = t.id;
        statsLoading = true;
        stats = null;
        const res = await masterApi.getTenantStats(t.id);
        statsLoading = false;
        if (res.ok === false) {
            errore = res.errore || 'Errore statistiche.';
            statsId = null;
        } else {
            stats = res;
        }
    }
</script>

<div class="container-fluid py-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h3 class="mb-0"><i class="bi bi-building me-2"></i>Gestione Tenant</h3>
        <button class="btn btn-primary" on:click={() => { showForm = !showForm; formErrore = ''; }}>
            <i class="bi bi-plus-lg me-1"></i>Nuovo Tenant
        </button>
    </div>

    {#if successo}
        <div class="alert alert-success alert-dismissible">
            {successo}
            <button type="button" class="btn-close" on:click={() => successo = ''}></button>
        </div>
    {/if}
    {#if errore}
        <div class="alert alert-danger alert-dismissible">
            {errore}
            <button type="button" class="btn-close" on:click={() => errore = ''}></button>
        </div>
    {/if}

    <!-- Form creazione -->
    {#if showForm}
        <div class="card mb-4 border-primary">
            <div class="card-header bg-primary text-white fw-semibold">Nuovo Tenant</div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-md-4">
                        <label class="form-label fw-semibold">Nome</label>
                        <input class="form-control" bind:value={formNome}
                               placeholder="Radiologia Torino" />
                    </div>
                    <div class="col-md-3">
                        <label class="form-label fw-semibold">Slug</label>
                        <input class="form-control" bind:value={formSlug}
                               placeholder="radiologia-torino" />
                    </div>
                    <div class="col-md-3">
                        <label class="form-label fw-semibold">Template</label>
                        <select class="form-select" bind:value={formTemplateId}>
                            <option value="">-- Nessuno (schema vuoto) --</option>
                            {#each templates as tmpl}
                                <option value={tmpl.id}>{tmpl.nome}</option>
                            {/each}
                        </select>
                    </div>
                    <div class="col-md-2">
                        <label class="form-label fw-semibold">Admin user</label>
                        <input class="form-control" bind:value={formAdminUser}
                               placeholder="admin" />
                    </div>
                </div>
                {#if formErrore}
                    <div class="alert alert-danger mt-3 py-2 small">{formErrore}</div>
                {/if}
                <div class="mt-3">
                    <button class="btn btn-primary me-2" on:click={creaTenant} disabled={formLoading}>
                        {#if formLoading}
                            <span class="spinner-border spinner-border-sm me-1"></span>
                        {/if}
                        Crea
                    </button>
                    <button class="btn btn-secondary" on:click={() => showForm = false}>Annulla</button>
                </div>
            </div>
        </div>
    {/if}

    <!-- Tabella tenant -->
    {#if loading}
        <div class="text-center py-5">
            <span class="spinner-border"></span>
        </div>
    {:else if tenants.length === 0}
        <div class="alert alert-info">Nessun tenant registrato.</div>
    {:else}
        <div class="table-responsive">
            <table class="table table-hover align-middle">
                <thead class="table-light">
                    <tr>
                        <th>Slug</th>
                        <th>Nome</th>
                        <th class="text-center">Attivo</th>
                        <th class="text-center">Dropdown</th>
                        <th>Creato</th>
                        <th class="text-end">Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    {#each tenants as t (t.id)}
                        <tr class:table-secondary={!t.is_active}>
                            <td><code>{t.slug}</code></td>
                            <td>
                                {#if editId === t.id}
                                    <input class="form-control form-control-sm"
                                           bind:value={editNome} />
                                {:else}
                                    {t.nome}
                                {/if}
                            </td>
                            <td class="text-center">
                                {#if t.is_active}
                                    <span class="badge bg-success">Si</span>
                                {:else}
                                    <span class="badge bg-secondary">No</span>
                                {/if}
                            </td>
                            <td class="text-center">
                                {#if editId === t.id}
                                    <input type="checkbox" class="form-check-input"
                                           bind:checked={editVisibile} />
                                {:else}
                                    {t.visibile_login ? 'Si' : 'No'}
                                {/if}
                            </td>
                            <td><small class="text-muted">{t.created_at || ''}</small></td>
                            <td class="text-end">
                                {#if editId === t.id}
                                    <button class="btn btn-sm btn-success me-1"
                                            on:click={() => salvaEdit(t)}>
                                        <i class="bi bi-check-lg"></i>
                                    </button>
                                    <button class="btn btn-sm btn-secondary"
                                            on:click={() => editId = null}>
                                        <i class="bi bi-x-lg"></i>
                                    </button>
                                {:else}
                                    <div class="btn-group btn-group-sm">
                                        <button class="btn btn-outline-primary"
                                                title="Modifica" on:click={() => iniziaEdit(t)}>
                                            <i class="bi bi-pencil"></i>
                                        </button>
                                        <button class="btn btn-outline-info"
                                                title="Statistiche" on:click={() => mostraStats(t)}>
                                            <i class="bi bi-bar-chart"></i>
                                        </button>
                                        {#if t.is_active}
                                            <button class="btn btn-outline-warning"
                                                    title="Impersona admin" on:click={() => impersona(t)}>
                                                <i class="bi bi-person-badge"></i>
                                            </button>
                                            <button class="btn btn-outline-secondary"
                                                    title="Reset password admin" on:click={() => resetPassword(t)}>
                                                <i class="bi bi-key"></i>
                                            </button>
                                        {/if}
                                        <button class="btn {t.is_active ? 'btn-outline-danger' : 'btn-outline-success'}"
                                                title={t.is_active ? 'Disattiva' : 'Riattiva'}
                                                on:click={() => toggleAttivo(t)}>
                                            <i class="bi {t.is_active ? 'bi-x-circle' : 'bi-check-circle'}"></i>
                                        </button>
                                    </div>
                                {/if}
                            </td>
                        </tr>
                        <!-- Stats row -->
                        {#if statsId === t.id}
                            <tr>
                                <td colspan="6" class="bg-light">
                                    {#if statsLoading}
                                        <span class="spinner-border spinner-border-sm me-1"></span>Caricamento...
                                    {:else if stats}
                                        <div class="d-flex gap-4 py-1 px-2 small">
                                            <span><strong>Utenti:</strong> {stats.utenti ?? '-'}</span>
                                            <span><strong>Calendari:</strong> {stats.calendari ?? '-'}</span>
                                            <span><strong>Preset:</strong> {stats.preset ?? '-'}</span>
                                        </div>
                                    {/if}
                                </td>
                            </tr>
                        {/if}
                    {/each}
                </tbody>
            </table>
        </div>
    {/if}
</div>
