<!--
  CredenzialiProvvisorie — banner di avviso credenziali di sviluppo.

  Compare quando l'account autenticato ha ancora password uguale allo
  username, condizione calcolata dal backend al login e restituita in
  user.credenziali_provvisorie. Sparisce da solo appena la password viene
  cambiata: non c'e' nessun flag da azzerare a mano.

  Volutamente NON mostrato nella pagina di login: annunciare a un visitatore
  non autenticato che la password coincide con lo username equivarrebbe a
  regalargli le credenziali. L'avviso e' quindi visibile solo dopo l'accesso.

  Da montare una sola volta in +layout.svelte.
-->
<script>
    import { user } from '$lib/auth.js';

    // Chiave di sessione: il rinvio vale finche' la scheda resta aperta,
    // cosi' l'avviso si ripresenta al login successivo.
    const CHIAVE_RINVIO = 'credenziali_provvisorie_rinviato';

    const TESTI = {
        titolo: 'Credenziali provvisorie',
        corpo: 'Questo account ha ancora la password uguale al nome utente ' +
               '(impostata dagli script di inizializzazione). Va cambiata ' +
               'prima di qualunque uso reale.',
        rinvia: 'Ricordamelo dopo',
    };

    // Il pannello Admin gestisce solo gli utenti del tenant: per il master
    // admin non esiste ancora una route di cambio password, quindi indicare
    // quel percorso sarebbe un'istruzione sbagliata.
    const DOVE_TENANT = 'La password si cambia dal pannello Admin, nella tabella Utenti.';
    const DOVE_MASTER = 'Per l\'account di piattaforma non esiste ancora una schermata ' +
                        'di cambio password: va aggiornata direttamente sul master DB.';

    const dove = $derived(
        $user?.role === 'master_admin' ? DOVE_MASTER : DOVE_TENANT
    );

    let rinviato = $state(leggiRinvio());

    /** Legge il rinvio salvato, tollerando storage non disponibile. */
    function leggiRinvio() {
        try {
            return sessionStorage.getItem(CHIAVE_RINVIO) === 'true';
        } catch (err) {
            return false;
        }
    }

    /** Nasconde l'avviso per la sessione corrente. */
    function rinvia() {
        rinviato = true;
        try {
            sessionStorage.setItem(CHIAVE_RINVIO, 'true');
        } catch (err) {
            // Storage non disponibile: l'avviso resta nascosto solo in memoria.
        }
    }

    const visibile = $derived(Boolean($user?.credenziali_provvisorie) && !rinviato);
</script>

{#if visibile}
<div class="alert alert-warning border-0 rounded-0 mb-0 py-2 px-3 d-flex align-items-center gap-2"
     style="position: sticky; top: 0; z-index: 1090;"
     role="alert">
    <i class="bi bi-shield-exclamation fs-5 flex-shrink-0"></i>

    <div class="flex-grow-1 small lh-sm">
        <strong>{TESTI.titolo}</strong> — {TESTI.corpo}
        <span class="d-block opacity-75">{dove}</span>
    </div>

    <button class="btn btn-sm btn-outline-dark flex-shrink-0" onclick={rinvia}>
        {TESTI.rinvia}
    </button>
</div>
{/if}
