<script>
    /**
     * Master Admin — Gestione template.
     *
     * CRUD template configurazione: lista, crea da zero,
     * crea da tenant esistente, modifica nome/descrizione, elimina.
     */

    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { masterApi } from '$lib/api.js';
    import { user } from '$lib/auth.js';

    let templates = [];
    let tenants = [];
    let loading = true;
    let errore = '';
    let successo = '';

    // Form nuovo template
    let showForm = false;
    let formNome = '';
    let formDescrizione = '';
    let formLoading = false;
    let formErrore = '';

    // Export da tenant
    let showExport = false;
    let exportTenantId = '';
    let exportLoading = false;

    // Edit inline
    let editId = null;
    let editNome = '';
    let editDescrizione = '';

    onMount(async () => {
        if (!$user || $user.role !== 'master_admin') {
            goto('/login');
            return;
        }
        await caricaDati();
    });

    async function caricaDati() {
        loading = true;
        const [tmplRes, tRes] = await Promise.all([
            masterApi.getTemplates(),
            masterApi.getTenants(),
        ]);
        templates = tmplRes.templates || tmplRes || [];
        tenants = (tRes.tenants || tRes || []).filter(t => t.is_active);
        loading = false;
    }

    async function creaTemplate() {
        formErrore = '';
        if (!formNome.trim()) { formErrore = 'Nome obbligatorio.'; return; }
        formLoading = true;
        const res = await masterApi.createTemplate({
            nome: formNome.trim(),
            descrizione: formDescrizione.trim(),
        });
        formLoading = false;
        if (res.ok === false) { formErrore = res.errore || 'Errore.'; return; }
        successo = `Template "${formNome}" creato.`;
        formNome = '';
        formDescrizione = '';
        showForm = false;
        await caricaDati();
    }

    async function esportaDaTenant() {
        if (!exportTenantId) return;
        exportLoading = true;
        const res = await masterApi.templateFromTenant(parseInt(exportTenantId));
        exportLoading = false;
        if (res.ok === false) {
            errore = res.errore || 'Errore export.';
        } else {
            successo = `Template creato da tenant.`;
            showExport = false;
            exportTenantId = '';
            await caricaDati();
        }
    }

    function iniziaEdit(t) {
        editId = t.id;
        editNome = t.nome;
        editDescrizione = t.descrizione || '';
    }

    async function salvaEdit(t) {
        const res = await masterApi.updateTemplate(t.id, {
            nome: editNome,
            descrizione: editDescrizione,
        });
        if (res.ok === false) errore = res.errore || 'Errore.';
        editId = null;
        await caricaDati();
    }

    async function eliminaTemplate(t) {
        if (!confirm(`Eliminare il template "${t.nome}"?`)) return;
        const res = await masterApi.deleteTemplate(t.id);
        if (res.ok === false) errore = res.errore || 'Errore.';
        await caricaDati();
    }
</script>

<div class="container-fluid py-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h3 class="mb-0"><i class="bi bi-file-earmark-code me-2"></i>Template</h3>
        <div class="d-flex gap-2">
            <button class="btn btn-outline-primary"
                    on:click={() => { showExport = !showExport; showForm = false; }}>
                <i class="bi bi-box-arrow-up me-1"></i>Da Tenant
            </button>
            <button class="btn btn-primary"
                    on:click={() => { showForm = !showForm; showExport = false; formErrore = ''; }}>
                <i class="bi bi-plus-lg me-1"></i>Nuovo
            </button>
        </div>
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

    <!-- Form nuovo template da zero -->
    {#if showForm}
        <div class="card mb-4 border-primary">
            <div class="card-header bg-primary text-white fw-semibold">Nuovo Template</div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-md-4">
                        <label class="form-label fw-semibold">Nome</label>
                        <input class="form-control" bind:value={formNome} placeholder="Radiologia" />
                    </div>
                    <div class="col-md-8">
                        <label class="form-label fw-semibold">Descrizione</label>
                        <input class="form-control" bind:value={formDescrizione}
                               placeholder="Template per reparti di radiologia" />
                    </div>
                </div>
                {#if formErrore}
                    <div class="alert alert-danger mt-3 py-2 small">{formErrore}</div>
                {/if}
                <div class="mt-3">
                    <button class="btn btn-primary me-2" on:click={creaTemplate} disabled={formLoading}>
                        {#if formLoading}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
                        Crea
                    </button>
                    <button class="btn btn-secondary" on:click={() => showForm = false}>Annulla</button>
                </div>
            </div>
        </div>
    {/if}

    <!-- Export da tenant -->
    {#if showExport}
        <div class="card mb-4 border-info">
            <div class="card-header bg-info text-white fw-semibold">Crea Template da Tenant Esistente</div>
            <div class="card-body">
                <div class="row g-3 align-items-end">
                    <div class="col-md-6">
                        <label class="form-label fw-semibold">Tenant sorgente</label>
                        <select class="form-select" bind:value={exportTenantId}>
                            <option value="">-- Seleziona tenant --</option>
                            {#each tenants as t}
                                <option value={t.id}>{t.nome} ({t.slug})</option>
                            {/each}
                        </select>
                    </div>
                    <div class="col-md-6">
                        <button class="btn btn-info me-2" on:click={esportaDaTenant}
                                disabled={exportLoading || !exportTenantId}>
                            {#if exportLoading}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
                            Esporta
                        </button>
                        <button class="btn btn-secondary" on:click={() => showExport = false}>Annulla</button>
                    </div>
                </div>
            </div>
        </div>
    {/if}

    <!-- Tabella template -->
    {#if loading}
        <div class="text-center py-5"><span class="spinner-border"></span></div>
    {:else if templates.length === 0}
        <div class="alert alert-info">Nessun template configurato.</div>
    {:else}
        <div class="table-responsive">
            <table class="table table-hover align-middle">
                <thead class="table-light">
                    <tr>
                        <th>Nome</th>
                        <th>Descrizione</th>
                        <th>File</th>
                        <th>Creato</th>
                        <th class="text-end">Azioni</th>
                    </tr>
                </thead>
                <tbody>
                    {#each templates as t (t.id)}
                        <tr>
                            <td>
                                {#if editId === t.id}
                                    <input class="form-control form-control-sm"
                                           bind:value={editNome} />
                                {:else}
                                    <strong>{t.nome}</strong>
                                {/if}
                            </td>
                            <td>
                                {#if editId === t.id}
                                    <input class="form-control form-control-sm"
                                           bind:value={editDescrizione} />
                                {:else}
                                    <small class="text-muted">{t.descrizione || '-'}</small>
                                {/if}
                            </td>
                            <td><code class="small">{t.db_filename || ''}</code></td>
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
                                        <button class="btn btn-outline-primary" title="Modifica"
                                                on:click={() => iniziaEdit(t)}>
                                            <i class="bi bi-pencil"></i>
                                        </button>
                                        <button class="btn btn-outline-danger" title="Elimina"
                                                on:click={() => eliminaTemplate(t)}>
                                            <i class="bi bi-trash"></i>
                                        </button>
                                    </div>
                                {/if}
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
    {/if}
</div>
