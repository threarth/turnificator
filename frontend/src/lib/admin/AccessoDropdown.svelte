<!--
  AccessoDropdown — Dropdown per selezionare manager con accesso a un'entita'.

  Mostra un pulsante con label riassuntiva. Al click apre un dropdown
  con checkbox "Tutti" + checkbox per ogni manager.

  Props:
    - managers     : Array<{id, sigla}> — lista manager disponibili
    - checked      : Set<number> — IDs manager attualmente selezionati
    - isOpen       : boolean — se il dropdown e' aperto
    - label        : string — testo visualizzato sul pulsante
    - disabled     : boolean — disabilita il pulsante (default false)
    - showIcon     : boolean — mostra icona people-fill (default true)
    - title        : string — tooltip pulsante (default '')
    - minWidth     : string — min-width del pulsante (default '40px')
    - ontoggleopen : () => void — callback apertura/chiusura dropdown
    - onchange     : (newChecked: Set<number>) => void — callback quando la selezione cambia
-->
<script>
  let {
    managers,
    checked,
    isOpen = false,
    label = 'Tutti',
    disabled = false,
    showIcon = true,
    title = '',
    minWidth = '40px',
    ontoggleopen,
    onchange,
  } = $props();

  let allChecked = $derived(checked.size >= managers.length);

  function toggleAll() {
    const newSet = allChecked ? new Set() : new Set(managers.map(m => m.id));
    onchange(newSet);
  }

  function toggleManager(managerId) {
    const s = new Set(checked);
    if (s.has(managerId)) s.delete(managerId); else s.add(managerId);
    onchange(s);
  }

  function handleButtonClick(e) {
    e.stopPropagation();
    ontoggleopen();
  }
</script>

<div class="position-relative d-inline-block">
  <button class="btn btn-outline-secondary btn-sm py-0 px-1" type="button" data-accesso-toggle
          style="font-size:.7rem; min-width:{minWidth}"
          {disabled} {title}
          onclick={handleButtonClick}>
    {#if showIcon}<i class="bi bi-people-fill me-1"></i>{/if}{label}
  </button>
  {#if isOpen}
    <div class="accesso-dropdown shadow-sm">
      <label class="accesso-item">
        <input type="checkbox" checked={allChecked} onchange={toggleAll} />
        <strong>Tutti</strong>
      </label>
      <hr class="my-1" />
      {#each managers as m}
        <label class="accesso-item">
          <input type="checkbox" checked={checked.has(m.id)} onchange={() => toggleManager(m.id)} />
          {m.sigla}
        </label>
      {/each}
    </div>
  {/if}
</div>
