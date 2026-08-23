<script>
    /**
     * Master Admin — Configurazione globale.
     *
     * Gestione parametri master: dropdown login attivo/disattivo,
     * altre config globali future.
     */

    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { masterApi } from '$lib/api.js';
    import { user } from '$lib/auth.js';

    let config = {};
    let loading = true;
    let saving = false;
    let errore = '';
    let successo = '';

    let dropdownAttivo = true;

    onMount(async () => {
        if (!$user || $user.role !== 'master_admin') {
            goto('/login');
            return;
        }
        loading = true;
        const res = await masterApi.getConfig();
        if (res.ok === false) {
            errore = res.errore || 'Errore caricamento config.';
        } else {
            config = res.config || res || {};
            dropdownAttivo = config.dropdown_login_attivo === '1';
        }
        loading = false;
    });

    // ── Cambio password account di piattaforma ──
    // Lunghezza minima allineata a LUNGHEZZA_MINIMA_PASSWORD in app/auth.py.
    const LUNGHEZZA_MINIMA_PASSWORD = 8;

    let pwdAttuale = '';
    let pwdNuova = '';
    let pwdConferma = '';
    let salvandoPwd = false;
    let errorePwd = '';
    let successoPwd = '';

    /** True se il form password e' compilato in modo coerente. */
    $: pwdValida = pwdAttuale
        && pwdNuova.length >= LUNGHEZZA_MINIMA_PASSWORD
        && pwdNuova === pwdConferma
        && pwdNuova !== $user?.username;

    async function cambiaPassword() {
        errorePwd = '';
        successoPwd = '';

        if (pwdNuova !== pwdConferma) {
            errorePwd = 'La conferma non coincide con la nuova password.';
            return;
        }

        salvandoPwd = true;
        const res = await masterApi.changePassword(pwdAttuale, pwdNuova);
        salvandoPwd = false;

        if (res.ok === false) {
            errorePwd = res.errore || 'Errore durante il cambio password.';
            return;
        }

        successoPwd = "Password aggiornata. Sara' richiesta al prossimo accesso.";
        pwdAttuale = pwdNuova = pwdConferma = '';
    }

    async function salva() {
        saving = true;
        errore = '';
        successo = '';
        const res = await masterApi.setConfig({
            dropdown_login_attivo: dropdownAttivo ? '1' : '0',
        });
        saving = false;
        if (res.ok === false) {
            errore = res.errore || 'Errore salvataggio.';
        } else {
            successo = 'Configurazione salvata.';
        }
    }
</script>

<div class="container py-4" style="max-width: 700px">
    <h3 class="mb-4"><i class="bi bi-sliders me-2"></i>Configurazione Globale</h3>

    {#if errore}
        <div class="alert alert-danger">{errore}</div>
    {/if}
    {#if successo}
        <div class="alert alert-success alert-dismissible">
            {successo}
            <button type="button" class="btn-close" on:click={() => successo = ''}></button>
        </div>
    {/if}

    {#if loading}
        <div class="text-center py-5"><span class="spinner-border"></span></div>
    {:else}
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Login</h5>

                <div class="form-check form-switch mb-3">
                    <input class="form-check-input" type="checkbox" id="dropdownSwitch"
                           bind:checked={dropdownAttivo} />
                    <label class="form-check-label" for="dropdownSwitch">
                        Dropdown tenant nella pagina di login
                    </label>
                </div>
                <p class="text-muted small mb-4">
                    Se attivo, la pagina di login mostra un menu a tendina con i tenant visibili.
                    Se disattivo, l'utente deve inserire manualmente lo slug dell'organizzazione.
                </p>

                <button class="btn btn-primary" on:click={salva} disabled={saving}>
                    {#if saving}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
                    Salva
                </button>
            </div>
        </div>

        <div class="card mt-4">
            <div class="card-body">
                <h5 class="card-title">
                    <i class="bi bi-shield-lock me-2"></i>Password account di piattaforma
                </h5>
                <p class="text-muted small">
                    Cambia la password di <strong>{$user?.username}</strong>, l'account che
                    sta sopra a tutti i tenant. Minimo {LUNGHEZZA_MINIMA_PASSWORD} caratteri,
                    diversa dal nome utente.
                </p>

                {#if errorePwd}
                    <div class="alert alert-danger py-2">{errorePwd}</div>
                {/if}
                {#if successoPwd}
                    <div class="alert alert-success py-2">{successoPwd}</div>
                {/if}

                <div class="mb-2">
                    <label class="form-label small mb-1" for="pwdAttuale">Password attuale</label>
                    <input id="pwdAttuale" class="form-control form-control-sm"
                           type="password" autocomplete="current-password"
                           bind:value={pwdAttuale} />
                </div>
                <div class="mb-2">
                    <label class="form-label small mb-1" for="pwdNuova">Nuova password</label>
                    <input id="pwdNuova" class="form-control form-control-sm"
                           type="password" autocomplete="new-password"
                           bind:value={pwdNuova} />
                </div>
                <div class="mb-3">
                    <label class="form-label small mb-1" for="pwdConferma">Conferma nuova password</label>
                    <input id="pwdConferma" class="form-control form-control-sm"
                           type="password" autocomplete="new-password"
                           bind:value={pwdConferma} />
                    {#if pwdConferma && pwdNuova !== pwdConferma}
                        <div class="form-text text-danger">La conferma non coincide.</div>
                    {/if}
                </div>

                <button class="btn btn-primary" on:click={cambiaPassword}
                        disabled={salvandoPwd || !pwdValida}>
                    {#if salvandoPwd}<span class="spinner-border spinner-border-sm me-1"></span>{/if}
                    Cambia password
                </button>
            </div>
        </div>
    {/if}
</div>
