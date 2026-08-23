<script>
    /**
     * Master Admin — Audit log impersonation.
     *
     * Mostra lo storico degli accessi master admin ai tenant
     * con data, tenant, azione eseguita.
     */

    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { masterApi } from '$lib/api.js';
    import { user } from '$lib/auth.js';

    let logs = [];
    let loading = true;
    let errore = '';

    onMount(async () => {
        if (!$user || $user.role !== 'master_admin') {
            goto('/login');
            return;
        }
        loading = true;
        const res = await masterApi.getImpersonationLog();
        if (res.ok === false) {
            errore = res.errore || 'Errore caricamento log.';
        } else {
            logs = res.logs || res || [];
        }
        loading = false;
    });
</script>

<div class="container-fluid py-4">
    <h3 class="mb-4"><i class="bi bi-journal-text me-2"></i>Audit Log Impersonation</h3>

    {#if errore}
        <div class="alert alert-danger">{errore}</div>
    {/if}

    {#if loading}
        <div class="text-center py-5"><span class="spinner-border"></span></div>
    {:else if logs.length === 0}
        <div class="alert alert-info">Nessun accesso registrato.</div>
    {:else}
        <div class="table-responsive">
            <table class="table table-striped align-middle">
                <thead class="table-light">
                    <tr>
                        <th>Data</th>
                        <th>Master User</th>
                        <th>Tenant</th>
                        <th>Azione</th>
                    </tr>
                </thead>
                <tbody>
                    {#each logs as log}
                        <tr>
                            <td><small>{log.created_at || ''}</small></td>
                            <td>{log.master_username || log.master_user_id}</td>
                            <td><code>{log.tenant_slug || log.tenant_id}</code></td>
                            <td>
                                {#if log.azione === 'enter'}
                                    <span class="badge bg-warning text-dark">Entrata</span>
                                {:else if log.azione === 'exit'}
                                    <span class="badge bg-info">Uscita</span>
                                {:else}
                                    <span class="badge bg-secondary">{log.azione}</span>
                                {/if}
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
    {/if}
</div>
