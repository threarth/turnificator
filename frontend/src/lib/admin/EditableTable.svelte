<!--
  EditableTable — Tabella generica con editing inline click-to-edit.

  Gestisce automaticamente:
  - Click su riga → entra in edit mode con autofocus sul campo cliccato
  - Enter → salva
  - ESC → annulla
  - Click-outside → annulla
  - Delete button con conferma double-click

  Props:
    - items           : Array<object> — array dati con campo `id` (o idKey)
    - columns         : Array<ColumnDef> — definizioni colonne (vedi sotto)
    - idKey           : string — nome campo ID (default 'id')
    - fontSize        : string — font-size tabella (default '.85rem')
    - emptyText       : string — testo quando items vuoto (default '')
    - rowClass        : (item) => string — classi aggiuntive per riga view (opzionale)
    - prepareEdit     : (item) => object — trasforma item prima dell'editing (opzionale)
    - onsave          : (editObj) => void — callback salva
    - ondelete        : (item) => void — callback elimina
    - ontoggle        : (item, key, value) => void — callback toggle diretto (checkbox senza edit)

  ColumnDef:
    - key        : string — nome campo nell'oggetto
    - label      : string — intestazione colonna
    - type       : 'text'|'number'|'select'|'checkbox'|'badge' (default 'text')
    - width      : string — CSS width (es. '80px', '100px')
    - viewClass  : string — classi CSS per <td> in view mode
    - format     : (value, item) => string — formattazione valore in view mode
    - formatHtml : (value, item) => string — HTML per view mode (usa {@html})
    - options    : Array<{value, label}> | (item) => Array<{value,label}> — per select
    - step       : number — per input number
    - min        : number — per input number
    - directToggle : boolean — checkbox toggle diretto in view mode (no edit)
    - badgeClass : (value, item) => string — classi badge per type='badge'
    - hidden     : boolean — nasconde la colonna
-->
<script>
  import DeleteButton from './DeleteButton.svelte';
  import { createAutoFocus, editRowKeydown } from './actions.js';

  let {
    items = [],
    columns = [],
    idKey = 'id',
    fontSize = '.85rem',
    emptyText = '',
    rowClass = null,
    prepareEdit = null,
    onsave,
    ondelete,
    ontoggle = null,
  } = $props();

  // Stato editing interno
  let editingItem = $state(null);  // oggetto in editing (copia)
  const { focusField, autoFocus } = createAutoFocus();

  // Colonne visibili
  let visibleCols = $derived(columns.filter(c => !c.hidden));

  function startEdit(e, item) {
    const td = e.target.closest('td');
    focusField.set(td?.dataset?.field || null);
    editingItem = prepareEdit ? prepareEdit(item) : { ...item };
  }

  function save() {
    if (editingItem) onsave(editingItem);
    editingItem = null;
  }

  function cancel() {
    editingItem = null;
  }

  function handleKeydown(e) {
    if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') save();
    if (e.key === 'Escape') cancel();
  }

  // Click-outside: se il click non e' su una riga editing/editable, chiudi
  function handleWindowMousedown(e) {
    if (editingItem && !e.target.closest('.table-warning') && !e.target.closest('.editable-row')) {
      cancel();
    }
  }

  function handleToggle(item, col, value) {
    if (ontoggle) ontoggle(item, col.key, value);
  }

  function getOptions(col, item) {
    return typeof col.options === 'function' ? col.options(item) : (col.options ?? []);
  }

  function formatView(col, item) {
    const v = item[col.key];
    if (col.format) return col.format(v, item);
    if (col.type === 'checkbox') return v ? '✓' : '—';
    if (col.type === 'select' && col.options) {
      const opts = getOptions(col, item);
      const opt = opts.find(o => o.value === v || String(o.value) === String(v));
      return opt?.label ?? (v ?? '—');
    }
    return v ?? '—';
  }

  // Esponi metodo per forzare chiusura editing dall'esterno (utile per click-outside globale)
  export function closeEdit() { editingItem = null; }
</script>

<svelte:window onmousedown={handleWindowMousedown} />

<table class="table table-sm table-hover table-config table-config-fixed mb-0" style="font-size:{fontSize}">
  <thead>
    <tr>
      {#each visibleCols as col}
        <th style={col.width ? `width:${col.width}` : ''}>{col.label}</th>
      {/each}
      <th style="width:60px"></th>
    </tr>
  </thead>
  <tbody>
  {#if items.length === 0 && emptyText}
    <tr><td colspan={visibleCols.length + 1} class="text-muted small text-center py-3">{emptyText}</td></tr>
  {/if}
  {#each items as item, idx (item[idKey] ?? idx)}
    {#if editingItem && (editingItem[idKey] ?? editingItem._idx) === (item[idKey] ?? idx)}
      <!-- Riga in editing -->
      <tr class="table-warning" onkeydown={handleKeydown}>
        {#each visibleCols as col}
          <td>
            {#if col.type === 'checkbox'}
              <input type="checkbox" bind:checked={editingItem[col.key]}
                     use:autoFocus={col.key} />
            {:else if col.type === 'select'}
              <select class="form-select form-select-sm"
                      style={col.width ? `width:${col.width}` : ''}
                      bind:value={editingItem[col.key]}
                      use:autoFocus={col.key}>
                {#each getOptions(col, editingItem) as opt}
                  <option value={opt.value}>{opt.label}</option>
                {/each}
              </select>
            {:else if col.type === 'number'}
              <input class="form-control form-control-sm"
                     type="number"
                     step={col.step ?? 1}
                     min={col.min ?? undefined}
                     style={col.width ? `width:${col.width}` : ''}
                     bind:value={editingItem[col.key]}
                     use:autoFocus={col.key} />
            {:else}
              <input class="form-control form-control-sm"
                     style={col.width ? `min-width:${col.width}` : ''}
                     bind:value={editingItem[col.key]}
                     use:autoFocus={col.key} />
            {/if}
          </td>
        {/each}
        <td style="white-space:nowrap">
          <button class="btn btn-success btn-sm py-0" onclick={save}><i class="bi bi-check-lg"></i></button>
          <button class="btn btn-secondary btn-sm py-0" onclick={cancel}><i class="bi bi-x"></i></button>
        </td>
      </tr>
    {:else}
      <!-- Riga in view mode -->
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <tr class="editable-row {rowClass ? rowClass(item) : ''}" style="cursor:pointer"
          onclick={e => startEdit(e, item)}>
        {#each visibleCols as col}
          {#if col.directToggle && col.type === 'checkbox'}
            <td onclick={e => e.stopPropagation()}>
              <input type="checkbox" checked={!!item[col.key]}
                     onchange={e => handleToggle(item, col, e.target.checked)} />
            </td>
          {:else if col.formatHtml}
            <td class={col.viewClass ?? ''} data-field={col.key}>{@html col.formatHtml(item[col.key], item)}</td>
          {:else if col.type === 'badge'}
            <td data-field={col.key}>
              <span class="badge {col.badgeClass ? col.badgeClass(item[col.key], item) : 'bg-secondary'}">{formatView(col, item)}</span>
            </td>
          {:else}
            <td class={col.viewClass ?? ''} data-field={col.key}>{formatView(col, item)}</td>
          {/if}
        {/each}
        <td style="white-space:nowrap" onclick={e => e.stopPropagation()}>
          {#if ondelete}
            <DeleteButton ondelete={() => ondelete(item)} stopPropagation />
          {/if}
        </td>
      </tr>
    {/if}
  {/each}
  </tbody>
</table>
