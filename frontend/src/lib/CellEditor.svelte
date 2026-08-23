<script>
  /**
   * CellEditor — cella con dropdown filtro stile Excel.
   * New feature: navigazione/editing celle griglia e WD.
   *
   * Props:
   *   options            [{value, label, disabled?, style?}]
   *   value              stringa del valore corrente
   *   onchange(v)        valore confermato
   *   focused            questa cella ha il cursore tastiera
   *   readonly
   *   style              inline style per conflitti/colori
   *   onfocusrequest()   pulsante ▾ cliccato → il parent deve spostare focus qui
   *   onkeynavigation(dir) tasto freccia quando dropdown chiuso
   *   onconfirm()        Enter confermato → il parent avanza il cursore
   */

  let {
    options = [],
    value = '',
    onchange,
    focused = false,
    readonly = false,
    style = '',
    onfocusrequest,
    onkeynavigation,
    onshiftnavigation,  // (dir) => void — Shift+Freccia per estendere selezione
    onconfirm,
  } = $props();

  import { onDestroy } from 'svelte';

  let wrapperEl = $state(null);
  let dropdownOpen = $state(false);
  let filterText = $state('');
  let highlightIdx = $state(0);
  let dropPos = $state({ top: 0, left: 0, width: 120 });

  /** Portal container: <ul> appeso a document.body per uscire dal stacking context della tabella. */
  let portalEl = $state(null);

  function ensurePortal() {
    if (!portalEl) {
      portalEl = document.createElement('ul');
      portalEl.className = 'ce-list';
      portalEl.setAttribute('role', 'listbox');
      document.body.appendChild(portalEl);
    }
    return portalEl;
  }

  function removePortal() {
    if (portalEl) {
      portalEl.remove();
      portalEl = null;
    }
  }

  onDestroy(removePortal);

  let currentLabel = $derived(options.find(o => o.value === value)?.label ?? '—');

  let filteredOpts = $derived(
    filterText
      ? options.filter(o => o.label.toLowerCase().startsWith(filterText.toLowerCase()))
      : options
  );

  // Focus DOM sul wrapper quando il parent attiva questa cella
  $effect(() => {
    if (focused && wrapperEl) wrapperEl.focus({ preventScroll: true });
  });

  // Aggiusta indice evidenziato se filteredOpts cambia
  $effect(() => {
    if (highlightIdx >= filteredOpts.length) highlightIdx = Math.max(0, filteredOpts.length - 1);
  });

  function openDropdown() {
    if (readonly) return;
    const rect = wrapperEl?.getBoundingClientRect();
    if (rect) dropPos = { top: rect.bottom + 1, left: rect.left, width: Math.max(rect.width, 110) };
    dropdownOpen = true;
    const idx = filteredOpts.findIndex(o => o.value === value);
    highlightIdx = Math.max(0, idx);
    renderPortal();
  }

  function closeDropdown() {
    dropdownOpen = false;
    filterText = '';
    removePortal();
  }

  /** Renderizza/aggiorna il contenuto del portal <ul> nel body. */
  function renderPortal() {
    const ul = ensurePortal();
    ul.style.cssText = `top:${dropPos.top}px;left:${dropPos.left}px;min-width:${dropPos.width}px`;
    _syncPortalItems(ul);
  }

  /** Sincronizza le <li> nel portal con filteredOpts. */
  function _syncPortalItems(ul) {
    ul.innerHTML = '';
    const opts = filterText
      ? options.filter(o => o.label.toLowerCase().startsWith(filterText.toLowerCase()))
      : options;
    if (opts.length === 0) {
      const li = document.createElement('li');
      li.className = 'ce-opt ce-dis';
      li.textContent = 'Nessun risultato';
      ul.appendChild(li);
      return;
    }
    opts.forEach((opt, idx) => {
      const li = document.createElement('li');
      li.className = `ce-opt ${idx === highlightIdx ? 'ce-hl' : ''} ${opt.disabled ? 'ce-dis' : ''}`;
      if (opt.style) li.style.cssText = opt.style;
      li.textContent = opt.label;
      li.setAttribute('role', 'option');
      li.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        if (!opt.disabled) confirmOption(opt.value);
      });
      ul.appendChild(li);
    });
  }

  // Aggiorna il portal quando filteredOpts o highlightIdx cambiano
  $effect(() => {
    // Dipendenze reattive: filteredOpts, highlightIdx, filterText
    const _deps = [filteredOpts.length, highlightIdx, filterText];
    if (dropdownOpen && portalEl) renderPortal();
  });

  function confirmOption(optValue) {
    closeDropdown();
    if (optValue !== value) onchange?.(optValue);
    onconfirm?.();
  }

  function onWrapperKeyDown(e) {
    if (readonly) return;

    if (!dropdownOpen) {
      if (e.key === 'ArrowDown')  { e.preventDefault(); e.stopPropagation(); e.shiftKey ? onshiftnavigation?.('down')  : onkeynavigation?.('down');  return; }
      if (e.key === 'ArrowUp')    { e.preventDefault(); e.stopPropagation(); e.shiftKey ? onshiftnavigation?.('up')    : onkeynavigation?.('up');    return; }
      if (e.key === 'ArrowRight') { e.preventDefault(); e.stopPropagation(); e.shiftKey ? onshiftnavigation?.('right') : onkeynavigation?.('right'); return; }
      if (e.key === 'ArrowLeft')  { e.preventDefault(); e.stopPropagation(); e.shiftKey ? onshiftnavigation?.('left')  : onkeynavigation?.('left');  return; }
      if (e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); onkeynavigation?.(e.shiftKey ? 'tab-back' : 'tab'); return; }
      if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); openDropdown(); return; }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        if (value !== '') { onchange?.(''); onconfirm?.(); }
        return;
      }
      if (e.key === 'Escape') { e.preventDefault(); return; }
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        filterText = e.key;
        openDropdown();
        return;
      }
    } else {
      if (e.key === 'Escape')    { e.preventDefault(); e.stopPropagation(); closeDropdown(); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); e.stopPropagation(); highlightIdx = Math.min(highlightIdx + 1, filteredOpts.length - 1); return; }
      if (e.key === 'ArrowUp')   { e.preventDefault(); e.stopPropagation(); highlightIdx = Math.max(highlightIdx - 1, 0); return; }
      if (e.key === 'Enter') {
        e.preventDefault();
        const opt = filteredOpts[highlightIdx];
        if (opt && !opt.disabled) confirmOption(opt.value);
        else closeDropdown();
        return;
      }
      if (e.key === 'Tab') {
        e.preventDefault();
        const opt = filteredOpts[highlightIdx];
        if (opt && !opt.disabled) { onchange?.(opt.value); }
        closeDropdown();
        onkeynavigation?.(e.shiftKey ? 'tab-back' : 'tab');
        return;
      }
      if (e.key === 'Backspace') { e.preventDefault(); filterText = filterText.slice(0, -1); highlightIdx = 0; return; }
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        filterText += e.key;
        highlightIdx = 0;
        return;
      }
    }
  }

  function onArrowBtnPointerDown(e) {
    e.preventDefault();
    e.stopPropagation();
    onfocusrequest?.();
    if (dropdownOpen) closeDropdown();
    else openDropdown();
  }

  function onFocusOut(e) {
    if (!wrapperEl?.contains(e.relatedTarget) && !portalEl?.contains(e.relatedTarget)) {
      closeDropdown();
    }
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
  bind:this={wrapperEl}
  class="ce-wrap"
  {style}
  tabindex="-1"
  role="combobox"
  aria-expanded={dropdownOpen}
  onkeydown={onWrapperKeyDown}
  onfocusout={onFocusOut}
>
  <span class="ce-val">{dropdownOpen && filterText ? filterText : currentLabel}</span>
  {#if !readonly}
    <button class="ce-btn" tabindex="-1" aria-label="Apri elenco" onpointerdown={onArrowBtnPointerDown}>▾</button>
  {/if}
</div>

<!-- Il dropdown e' renderizzato come portal in document.body via JS (ensurePortal/renderPortal) -->

<style>
  .ce-wrap {
    position: relative;
    display: flex;
    align-items: center;
    width: 100%;
    height: 100%;
    padding: 0 2px;
    font-size: .8rem;
    outline: none;
    cursor: default;
    user-select: none;
    background: transparent;
    box-sizing: border-box;
  }

  .ce-val {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
    font-size: inherit;
    color: inherit;
  }

  .ce-btn {
    display: none;
    flex-shrink: 0;
    width: 16px;
    height: 16px;
    padding: 0;
    margin-left: 1px;
    border: 1px solid #999;
    background: #f0f0f0;
    color: #333;
    font-size: 10px;
    line-height: 1;
    cursor: pointer;
    border-radius: 2px;
    align-items: center;
    justify-content: center;
  }

  .ce-wrap:hover .ce-btn,
  .ce-wrap:focus-within .ce-btn {
    display: flex;
  }

  /* Portal: stili globali perche' il <ul> e' appeso a document.body */
  :global(.ce-list) {
    position: fixed;
    z-index: 9999;
    background: white;
    border: 1px solid #adb5bd;
    border-radius: 3px;
    box-shadow: 0 3px 8px rgba(0, 0, 0, .2);
    max-height: 200px;
    overflow-y: auto;
    padding: 2px 0;
    margin: 0;
    list-style: none;
  }

  :global(.ce-opt) {
    padding: 2px 8px;
    font-size: .8rem;
    cursor: pointer;
    white-space: nowrap;
  }

  :global(.ce-opt:hover:not(.ce-dis)) { background: #e8f0fe; }
  :global(.ce-hl) { background: #d0e4ff; }
  :global(.ce-dis) { color: #aaa; cursor: default; }
</style>
