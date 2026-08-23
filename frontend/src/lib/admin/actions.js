/**
 * Utility condivise per i widget admin — azioni Svelte e helper per editing inline.
 *
 * focusOnMount(node)        — action: focus immediato sull'elemento al mount
 * focusIf(node, cond)       — action: focus condizionale al mount
 * createAutoFocus()         — factory che crea un sistema di auto-focus per campo cliccato
 * autowidth(node)           — action: ridimensiona input alla larghezza del contenuto
 * editRowKeydown(saveFn, cancelFn) — ritorna handler keydown: Enter=salva, Escape=annulla
 * startEditFromRow(e, setEdit, autoFocusCtx) — handler click riga: rileva campo e attiva editing
 * clickOutside(node, cb)    — action Svelte: chiama cb quando si clicca fuori dal nodo
 */

/**
 * Action Svelte: mette il focus sull'elemento appena montato.
 * Uso: <input use:focusOnMount />
 */
export function focusOnMount(node) {
  node.focus();
  return {};
}

/**
 * Action Svelte: mette il focus sull'elemento se `condition` e' true.
 * Uso: <input use:focusIf={shouldFocus} />
 */
export function focusIf(node, condition) {
  if (condition) node.focus();
  return {};
}

/**
 * Factory: crea un sistema di auto-focus per editing inline click-to-edit.
 *
 * Quando l'utente clicca su un campo specifico di una riga, il campo corrispondente
 * nell'editing mode riceve il focus automaticamente.
 *
 * Ritorna:
 *   - focusField  : getter/setter per il nome del campo da focalizzare
 *   - autoFocus   : action Svelte — <input use:autoFocus={'nome'} />
 *
 * Esempio:
 *   const { focusField, autoFocus } = createAutoFocus();
 *   // Nel click handler della riga:
 *   focusField.set(td.dataset.field);
 *   // Nel template editing:
 *   <input use:autoFocus={'nome'} />
 */
export function createAutoFocus() {
  let _field = null;

  return {
    focusField: {
      get: () => _field,
      set: (v) => { _field = v; },
    },
    autoFocus(node, field) {
      if (_field === field) {
        node.focus();
        if (node.select) node.select();
        _field = null;
      }
      return {};
    },
  };
}

/**
 * Ritorna un handler keydown per righe in editing inline.
 * - Enter (su non-button) → chiama saveFn
 * - Escape → chiama cancelFn
 *
 * Uso: <tr on:keydown={editRowKeydown(save, cancel)}>
 */
export function editRowKeydown(saveFn, cancelFn) {
  return (e) => {
    if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') saveFn();
    if (e.key === 'Escape') cancelFn();
  };
}

/**
 * Handler click su riga tabella: rileva il campo cliccato (data-field sul <td>)
 * e attiva la modalita' editing.
 *
 * @param {MouseEvent} e — evento click
 * @param {Function} setEdit — callback per attivare editing (es. () => editingId = row.id)
 * @param {object} autoFocusCtx — oggetto ritornato da createAutoFocus()
 */
export function startEditFromRow(e, setEdit, autoFocusCtx) {
  const td = e.target.closest('td');
  const field = td?.dataset?.field || null;
  if (autoFocusCtx) {
    autoFocusCtx.focusField.set(field);
  }
  setEdit();
}

/**
 * Action Svelte: ridimensiona l'input alla larghezza del contenuto (min 100px).
 * Uso: <input use:autowidth />
 */
export function autowidth(node) {
  const MIN = 100;
  function update() {
    node.style.width = MIN + 'px';
    node.style.width = Math.max(MIN, node.scrollWidth) + 'px';
  }
  node.addEventListener('input', update);
  requestAnimationFrame(update);
  return { destroy() { node.removeEventListener('input', update); } };
}

/**
 * Action Svelte: chiama `callback` quando si clicca fuori dall'elemento.
 * Usa mousedown per catturare il click prima del blur.
 *
 * Uso: <div use:clickOutside={() => closeMenu()}>
 */
export function clickOutside(node, callback) {
  function handle(e) {
    if (!node.contains(e.target)) callback();
  }
  document.addEventListener('mousedown', handle, true);
  return {
    destroy() { document.removeEventListener('mousedown', handle, true); },
  };
}
