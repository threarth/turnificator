/**
 * lib/auth.js — store Svelte per l'autenticazione JWT (multi-tenant).
 *
 * Espone:
 *   user     — { id, username, role, sigla } oppure null
 *   token    — stringa JWT oppure null
 *   tenant   — slug del tenant corrente oppure null
 *   impersonated — true se il master admin sta impersonando un tenant admin
 *   login()  — effettua login tenant e salva in localStorage
 *   loginMaster() — effettua login master admin
 *   logout() — cancella sessione (tenant + master)
 *   exitImpersonation() — esce dalla modalita' impersonation
 *   init()   — ripristina sessione da localStorage al caricamento
 */

import { writable, get } from 'svelte/store';

export const user         = writable(null);
export const token        = writable(null);
export const tenant       = writable(null);
export const impersonated = writable(false);

/** Ripristina la sessione salvata in localStorage. */
export function init() {
    const savedToken  = localStorage.getItem('jwt');
    const savedUser   = localStorage.getItem('user');
    const savedTenant = localStorage.getItem('tenant');
    const savedImpersonated = localStorage.getItem('impersonated');

    if (savedToken && savedUser) {
        token.set(savedToken);
        user.set(JSON.parse(savedUser));
        tenant.set(savedTenant || null);
        impersonated.set(savedImpersonated === 'true');
    }
}

/**
 * Effettua il login tenant.
 * @param {string} username
 * @param {string} password
 * @param {string} tenantSlug — slug del tenant
 * @returns {{ ok: boolean, errore?: string }}
 */
export async function login(username, password, tenantSlug) {
    const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, tenant: tenantSlug }),
    });
    const data = await res.json();

    if (data.ok) {
        token.set(data.token);
        user.set(data.user);
        tenant.set(data.tenant || tenantSlug);
        impersonated.set(false);
        localStorage.setItem('jwt', data.token);
        localStorage.setItem('user', JSON.stringify(data.user));
        localStorage.setItem('tenant', data.tenant || tenantSlug);
        localStorage.removeItem('impersonated');
    }
    return data;
}

/**
 * Effettua il login master admin.
 * @param {string} username
 * @param {string} password
 * @returns {{ ok: boolean, errore?: string }}
 */
export async function loginMaster(username, password) {
    const res = await fetch('/api/master/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    });
    const data = await res.json();

    if (data.ok) {
        token.set(data.token);
        user.set(data.user);
        tenant.set(null);
        impersonated.set(false);
        localStorage.setItem('jwt', data.token);
        localStorage.setItem('user', JSON.stringify(data.user));
        localStorage.removeItem('tenant');
        localStorage.removeItem('impersonated');
    }
    return data;
}

/**
 * Imposta la sessione dopo impersonation (chiamata dal pannello master).
 * @param {{ token: string, user: object, tenant: string }} data
 */
export function setImpersonation(data) {
    // Salva token master per poterci tornare
    const currentToken = get(token);
    const currentUser  = get(user);
    localStorage.setItem('master_jwt', currentToken);
    localStorage.setItem('master_user', JSON.stringify(currentUser));

    token.set(data.token);
    user.set(data.user);
    tenant.set(data.tenant);
    impersonated.set(true);
    localStorage.setItem('jwt', data.token);
    localStorage.setItem('user', JSON.stringify(data.user));
    localStorage.setItem('tenant', data.tenant);
    localStorage.setItem('impersonated', 'true');
}

/** Esce dalla modalita' impersonation, ripristina sessione master. */
export function exitImpersonation() {
    const masterToken = localStorage.getItem('master_jwt');
    const masterUser  = localStorage.getItem('master_user');

    if (masterToken && masterUser) {
        token.set(masterToken);
        user.set(JSON.parse(masterUser));
        tenant.set(null);
        impersonated.set(false);
        localStorage.setItem('jwt', masterToken);
        localStorage.setItem('user', masterUser);
        localStorage.removeItem('tenant');
        localStorage.removeItem('impersonated');
        localStorage.removeItem('master_jwt');
        localStorage.removeItem('master_user');
    } else {
        logout();
    }
}

/** Effettua il logout e cancella la sessione locale. */
export function logout() {
    token.set(null);
    user.set(null);
    tenant.set(null);
    impersonated.set(false);
    localStorage.removeItem('jwt');
    localStorage.removeItem('user');
    localStorage.removeItem('tenant');
    localStorage.removeItem('impersonated');
    localStorage.removeItem('master_jwt');
    localStorage.removeItem('master_user');
}

/** Restituisce il token corrente (helper sincrono). */
export function getToken() {
    return get(token);
}

/** Restituisce il tenant corrente (helper sincrono). */
export function getTenant() {
    return get(tenant);
}

/** Aggiorna il token (sliding session). */
export function refreshToken(newToken) {
    token.set(newToken);
    localStorage.setItem('jwt', newToken);
}
