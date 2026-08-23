<!--
  DeleteButton — Pulsante elimina con conferma double-click.

  Primo click: diventa rosso pieno (stato "pending").
  Secondo click: chiama ondelete().
  Click altrove: torna allo stato normale (listener condiviso a livello modulo).

  Props:
    - ondelete        : () => void — callback eliminazione (secondo click)
    - size            : 'sm' | '' — dimensione Bootstrap (default 'sm')
    - btnClass        : stringa classi aggiuntive (default 'btn-outline-danger')
    - stopPropagation : bool — se true, ferma propagazione click (default false)
    - icon            : icona Bootstrap Icons (default 'bi-x-lg')
    - title           : tooltip (default 'Elimina (doppio click)')

  Implementazione: stato pending gestito via DOM (classList + dataset),
  nessun $state/$derived — massima compatibilita' Svelte 4/5 interop.
-->
<script module>
  let _listenerInstalled = false;

  function _installResetListener() {
    if (_listenerInstalled) return;
    _listenerInstalled = true;
    // Click fuori da un del-btn: resetta tutti i pulsanti pending
    document.addEventListener('mousedown', (e) => {
      if (!e.target.closest('.del-btn')) {
        for (const b of document.querySelectorAll('.del-btn.del-pending')) {
          b.classList.remove('del-pending', 'btn-danger');
          b.classList.add(b.dataset.btnclass || 'btn-outline-danger');
        }
      }
    }, true);
  }
</script>

<script>
  import { onMount } from 'svelte';

  /** @type {{ ondelete: () => void, size?: string, btnClass?: string, stopPropagation?: boolean, icon?: string, title?: string }} */
  let {
    ondelete,
    size = 'sm',
    btnClass = 'btn-outline-danger',
    stopPropagation = false,
    icon = 'bi-x-lg',
    title = 'Elimina (doppio click)',
  } = $props();

  let btnEl;

  _installResetListener();

  onMount(() => {
    const btn = btnEl;
    function handleClick(e) {
      if (stopPropagation) e.stopPropagation();

      if (btn.classList.contains('del-pending')) {
        // Secondo click: esegui eliminazione
        btn.classList.remove('del-pending', 'btn-danger');
        btn.classList.add(btnClass);
        ondelete();
      } else {
        // Primo click: resetta altri pending, attiva questo
        for (const b of document.querySelectorAll('.del-btn.del-pending')) {
          if (b !== btn) {
            b.classList.remove('del-pending', 'btn-danger');
            b.classList.add(b.dataset.btnclass || 'btn-outline-danger');
          }
        }
        btn.classList.remove(btnClass);
        btn.classList.add('del-pending', 'btn-danger');
      }
    }

    btn.addEventListener('click', handleClick);
    return () => btn.removeEventListener('click', handleClick);
  });
</script>

<button
  bind:this={btnEl}
  class="del-btn btn {size ? `btn-${size}` : ''} py-0 px-2 {btnClass}"
  data-btnclass={btnClass}
  {title}
>
  <i class="bi {icon}"></i>
</button>
