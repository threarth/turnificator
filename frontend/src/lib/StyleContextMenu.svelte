<!--
  StyleContextMenu — Context menu formattazione per sovragruppi e gruppi.

  Componente condiviso tra admin (struttura preset) e manager (griglia turni).
  Gestisce internamente: dragging, tab state, posizionamento intelligente.
  La logica di salvataggio/rollback e' delegata al parent tramite callback.

  Props:
    - x, y              : number — posizione iniziale click
    - tipo              : 'sg' | 'sovragruppo' | 'gruppo' — tipo entita'
    - sepStyle          : object — stile corrente separatore (tab Separatore)
    - colStyle          : object — stile corrente colonna (tab Colonna)
    - borderColor       : string — colore bordo corrente
    - borderWidth       : number — spessore bordo corrente
    - repeatName        : boolean — flag ripeti nome
    - defaultBg         : string — sfondo default per tipo (separatore)
    - defaultFg         : string — testo default per tipo (separatore)
    - defaultBgCol      : string — sfondo default colonna (default '#ffffff')
    - defaultFgCol      : string — testo default colonna (default '#212529')
    - undoCount         : number — numero undo disponibili (0 = nasconde bottone)
    - showApplyAll      : boolean — mostra "Applica a tutti i gruppi" (solo gruppo, default false)

  Callback:
    - onset(prop, value, tab)   — proprietà stile modificata ('separatore' | 'colonna')
    - onborderset(prop, value)  — bordo/repeatName modificato
    - onapply()                 — bottone Applica premuto
    - onclose()                 — chiudi/annulla (click backdrop o X)
    - onundo()                  — bottone Undo premuto
    - onapplyall()              — "Applica a tutti i gruppi" premuto
-->
<script>
  import { etichettaStruttura } from '$lib/etichette.js';
  let {
    x = 0,
    y = 0,
    tipo = 'gruppo',
    sepStyle = {},
    colStyle = {},
    borderColor = '',
    borderWidth = 4,
    repeatName = false,
    defaultBg = '#e9ecef',
    defaultFg = '#6c757d',
    defaultBgCol = '#ffffff',
    defaultFgCol = '#212529',
    undoCount = 0,
    showApplyAll = false,
    onset,
    onborderset,
    onapply,
    onclose,
    onundo,
    onapplyall,
  } = $props();

  let tab = $state('separatore');
  let posX = $state(x);
  let posY = $state(y);
  let dragging = $state(false);

  let isSg = $derived(tipo === 'sg' || tipo === 'sovragruppo');
  let isGruppo = $derived(tipo === 'gruppo');

  // Stile corrente in base al tab
  let styleObj = $derived(tab === 'colonna' ? colStyle : sepStyle);
  let defBg = $derived(tab === 'colonna' ? defaultBgCol : defaultBg);
  let defFg = $derived(tab === 'colonna' ? defaultFgCol : defaultFg);

  // Posizionamento intelligente
  const MENU_W = 240;
  const MENU_H = 400;
  $effect(() => {
    const ww = typeof window !== 'undefined' ? window.innerWidth : 1920;
    const wh = typeof window !== 'undefined' ? window.innerHeight : 1080;
    posX = Math.min(x, ww - MENU_W);
    posY = (y + MENU_H > wh) ? Math.max(0, y - MENU_H - 40) : y;
  });

  function set(prop, value) {
    onset(prop, value, tab);
  }

  function onDragStart(e) {
    dragging = true;
    const startX = e.clientX, startY = e.clientY;
    const origX = posX, origY = posY;
    function onMove(ev) {
      posX = origX + ev.clientX - startX;
      posY = origY + ev.clientY - startY;
    }
    function onUp() {
      dragging = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="scm-backdrop" onclick={onclose} oncontextmenu={e => { e.preventDefault(); onclose(); }}></div>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="scm-menu" style="left:{posX}px;top:{posY}px"
     onmousedown={e => { if (e.target === e.currentTarget) onDragStart(e); }}>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="scm-drag-bar" onmousedown={onDragStart}>
    <span style="font-size:.72rem;color:var(--ctx-muted);font-weight:600">
      {isSg ? `Formato ${$etichettaStruttura.singolare}` : 'Formato Gruppo'}
    </span>
    <button class="scm-close" onclick={onclose}>&times;</button>
  </div>

  <!-- Tabs -->
  {#if isGruppo || isSg}
    <div style="display:flex;border-bottom:1px solid var(--ctx-sep);margin:0 8px">
      <button class="scm-tab" class:active={tab === 'separatore'}
              onclick={() => tab = 'separatore'}>Separatore</button>
      <button class="scm-tab" class:active={tab === 'colonna'}
              onclick={() => tab = 'colonna'}>Colonna{isSg ? ' (tutti i gruppi)' : ''}</button>
    </div>
  {/if}

  <!-- Controlli formato -->
  <div class="scm-item">
    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin:0;width:100%">
      <span style="flex:1">Sfondo</span>
      <input type="color" value={styleObj?.backgroundColor ?? defBg}
             oninput={e => set('backgroundColor', e.currentTarget.value)} />
    </label>
  </div>
  <div class="scm-item">
    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin:0;width:100%">
      <span style="flex:1">Testo</span>
      <input type="color" value={styleObj?.color ?? defFg}
             oninput={e => set('color', e.currentTarget.value)} />
    </label>
  </div>
  <div class="scm-item">
    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin:0;width:100%">
      <span style="flex:1">Font</span>
      <select style="width:110px;font-size:.8rem"
              value={styleObj?.fontFamily ?? ''}
              onchange={e => set('fontFamily', e.currentTarget.value)}>
        <option value="">Default</option>
        <option value="Arial">Arial</option>
        <option value="Calibri">Calibri</option>
        <option value="Verdana">Verdana</option>
        <option value="Georgia">Georgia</option>
        <option value="Courier New">Courier New</option>
      </select>
    </label>
  </div>
  <div class="scm-item">
    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin:0;width:100%">
      <span style="flex:1">Dimensione</span>
      <select style="width:80px;font-size:.8rem"
              value={styleObj?.fontSize ?? ''}
              onchange={e => set('fontSize', e.currentTarget.value)}>
        <option value="">Default</option>
        <option value="0.6rem">XS</option>
        <option value="0.7rem">S</option>
        <option value="0.8rem">M</option>
        <option value="0.9rem">L</option>
        <option value="1rem">XL</option>
        <option value="1.2rem">XXL</option>
      </select>
    </label>
  </div>
  <div class="scm-sep"></div>
  <div class="scm-item" style="gap:4px">
    <span style="flex:1">Stile</span>
    <button class="scm-fmt-btn" class:active={styleObj?.fontWeight === 'bold'}
            onclick={() => set('fontWeight', styleObj?.fontWeight === 'bold' ? 'normal' : 'bold')}
            title="Grassetto"><b>B</b></button>
    <button class="scm-fmt-btn" class:active={styleObj?.fontStyle === 'italic'}
            onclick={() => set('fontStyle', styleObj?.fontStyle === 'italic' ? 'normal' : 'italic')}
            title="Corsivo"><i>I</i></button>
  </div>
  <div class="scm-item" style="gap:4px">
    <span style="flex:1">Allineamento</span>
    <button class="scm-fmt-btn" class:active={styleObj?.textAlign === 'left' || !styleObj?.textAlign}
            onclick={() => set('textAlign', 'left')} title="Sinistra">
      <i class="bi bi-text-left"></i></button>
    <button class="scm-fmt-btn" class:active={styleObj?.textAlign === 'center'}
            onclick={() => set('textAlign', 'center')} title="Centro">
      <i class="bi bi-text-center"></i></button>
    <button class="scm-fmt-btn" class:active={styleObj?.textAlign === 'right'}
            onclick={() => set('textAlign', 'right')} title="Destra">
      <i class="bi bi-text-right"></i></button>
  </div>
  <div class="scm-item" style="gap:4px">
    <span style="flex:1">Maiuscole</span>
    <button class="scm-fmt-btn" class:active={styleObj?.textTransform === 'capitalize'}
            onclick={() => set('textTransform', styleObj?.textTransform === 'capitalize' ? 'none' : 'capitalize')}
            title="Capitalize">Aa</button>
    <button class="scm-fmt-btn" class:active={styleObj?.textTransform === 'uppercase'}
            onclick={() => set('textTransform', styleObj?.textTransform === 'uppercase' ? 'none' : 'uppercase')}
            title="Maiuscolo">AA</button>
    <button class="scm-fmt-btn" class:active={styleObj?.textTransform === 'lowercase'}
            onclick={() => set('textTransform', styleObj?.textTransform === 'lowercase' ? 'none' : 'lowercase')}
            title="Minuscolo">aa</button>
  </div>

  <!-- Bordi e ripeti nome (solo tab separatore) -->
  {#if tab === 'separatore' && (isGruppo || isSg)}
    <div class="scm-sep"></div>
    <div class="scm-item">
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin:0;width:100%">
        <span style="flex:1">Bordo colore</span>
        <input type="color" value={borderColor}
               oninput={e => onborderset('--borderColor', e.currentTarget.value)} />
      </label>
    </div>
    <div class="scm-item">
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin:0;width:100%">
        <span style="flex:1">Bordo spessore</span>
        <select style="width:80px;font-size:.8rem"
                value={borderWidth}
                onchange={e => onborderset('--borderWidth', Number(e.currentTarget.value))}>
          <option value={0}>0 (nessuno)</option>
          <option value={1}>1px</option>
          <option value={2}>2px</option>
          <option value={3}>3px</option>
          <option value={4}>4px</option>
          <option value={5}>5px</option>
          <option value={6}>6px</option>
          <option value={8}>8px</option>
        </select>
      </label>
    </div>
    <div class="scm-sep"></div>
    <div class="scm-item">
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;margin:0;width:100%">
        <span style="flex:1">Ripeti nome</span>
        <input type="checkbox" checked={repeatName}
               onchange={() => onborderset('--repeatName', !repeatName)} />
      </label>
    </div>
  {/if}

  <!-- Applica a tutti -->
  {#if showApplyAll && isGruppo}
    <div class="scm-sep"></div>
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="scm-item" style="cursor:pointer" onclick={onapplyall}>
      <i class="bi bi-clipboard-check"></i> Applica a tutti i gruppi
    </div>
  {/if}

  <!-- Applica / Undo -->
  <div class="scm-sep"></div>
  <div style="display:flex;gap:6px;padding:6px 10px">
    <button class="btn btn-success btn-sm" style="flex:1;font-size:.75rem"
            onclick={onapply}>
      <i class="bi bi-check-lg me-1"></i>Applica
    </button>
    {#if undoCount > 0}
      <button class="btn btn-outline-secondary btn-sm" style="font-size:.75rem"
              onclick={onundo} title="Annulla ultima formattazione">
        <i class="bi bi-arrow-counterclockwise me-1"></i>Undo ({undoCount})
      </button>
    {/if}
  </div>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="scm-drag-bar scm-drag-bottom" onmousedown={onDragStart}>
    <span style="font-size:.6rem;color:var(--ctx-muted)">&#x2817; trascina</span>
  </div>
</div>

<style>
  .scm-backdrop {
    position: fixed; inset: 0; z-index: 999;
  }
  .scm-menu {
    position: fixed; z-index: 1000;
    background: var(--ctx-bg, #fff); border: 4px solid var(--ctx-border, #e9ecef);
    border-radius: 6px; box-shadow: 0 4px 12px var(--ctx-shadow, rgba(0,0,0,.15));
    padding: 0; min-width: 220px; cursor: move;
    color: var(--ctx-fg, #212529);
  }
  .scm-menu > :not(.scm-drag-bar) { cursor: default; }
  .scm-item {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 14px; cursor: pointer; font-size: 0.82rem;
  }
  .scm-item:hover { background: var(--ctx-hover, #f0f0f0); }
  .scm-sep { border-top: 1px solid var(--ctx-sep, #eee); margin: 4px 0; }
  .scm-tab {
    flex: 1; border: none; background: none; padding: 5px 8px;
    font-size: .78rem; cursor: pointer; color: var(--ctx-muted, #888);
    border-bottom: 2px solid transparent;
  }
  .scm-tab.active { color: #0d6efd; border-bottom-color: #0d6efd; font-weight: 600; }
  .scm-tab:hover { color: var(--ctx-fg, #333); }
  .scm-drag-bar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 4px 10px; cursor: move; background: var(--ctx-bar, #f8f9fa);
    border-bottom: 1px solid var(--ctx-sep, #eee); border-radius: 4px 4px 0 0;
    user-select: none;
  }
  .scm-drag-bar.scm-drag-bottom {
    border-bottom: none; border-top: 1px solid var(--ctx-sep, #eee);
    border-radius: 0 0 4px 4px; justify-content: center;
    padding: 2px 10px;
  }
  .scm-close {
    border: none; background: none; font-size: 1.1rem; color: var(--ctx-muted, #999);
    cursor: pointer; padding: 0 4px; line-height: 1;
  }
  .scm-close:hover { color: var(--ctx-fg, #333); }
  .scm-fmt-btn {
    border: 1px solid var(--ctx-btn-border, #ccc); background: var(--ctx-bg, #fff); border-radius: 3px;
    width: 28px; height: 28px; padding: 0; cursor: pointer;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: .78rem; color: var(--ctx-fg, #555);
  }
  .scm-fmt-btn:hover { background: var(--ctx-hover, #e9ecef); }
  .scm-fmt-btn.active { background: #0d6efd; color: #fff; border-color: #0d6efd; }
  .scm-menu select, .scm-menu input[type="checkbox"] {
    background: var(--ctx-bg, #fff); color: var(--ctx-fg, #212529);
    border-color: var(--ctx-btn-border, #ccc);
  }
</style>
