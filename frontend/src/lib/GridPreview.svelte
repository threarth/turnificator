<script>
  import { etichettaStruttura } from '$lib/etichette.js';
  /** Anteprima griglia turni — read-only, 7 giorni.
   *  Riceve la struttura preset (array di sovragruppi) e la mostra
   *  come tabella stile griglia manager, con stili applicati. */

  export let struttura = [];  // editPreset.struttura (array di SG)

  const NUM_GIORNI = 7;
  const NOMI_GG = ['Lun','Mar','Mer','Gio','Ven','Sab','Dom'];

  // Helper: oggetto style JS → stringa CSS inline
  function toStyleStr(obj) {
    if (!obj || typeof obj !== 'object') return '';
    return Object.entries(obj)
      .filter(([k, v]) => !k.startsWith('--') && typeof v === 'string')
      .map(([k, v]) => `${k.replace(/[A-Z]/g, c => '-' + c.toLowerCase())}:${v}`)
      .join(';');
  }

  // Default separatori (identici al manager)
  const DEFAULT_SEP_STYLE = { backgroundColor: '#e9ecef', color: '#6c757d', fontStyle: 'italic' };
  const DEFAULT_SG_STYLE  = { backgroundColor: '#d6d8db', color: '#1a1a1a', fontWeight: 'bold' };
  const DEFAULT_COL_STYLE = { backgroundColor: '#ffffff', color: '#212529' };

  function effectiveSgStyle(sg) {
    return { ...DEFAULT_SG_STYLE, ...(sg.style ?? {}) };
  }

  function effectiveGruppoStyle(g) {
    return { ...DEFAULT_SEP_STYLE, ...(g.style ?? {}) };
  }

  function effectiveColStyle(g) {
    const colStyle = g.style?.['--columnStyle'] ?? {};
    return { ...DEFAULT_COL_STYLE, ...colStyle };
  }

  function effectiveTurnoStyle(t) {
    if (!t.style || typeof t.style !== 'object') return '';
    return toStyleStr(t.style);
  }

  // Bordi: stringa inline solo se personalizzati, altrimenti vuota (usa CSS default)
  function borderStyle(styleObj, fallbackBg) {
    const hasBorder = styleObj?.['--borderColor'] != null || styleObj?.['--borderWidth'] != null;
    if (!hasBorder) return '';
    const color = styleObj['--borderColor'] ?? styleObj?.backgroundColor ?? fallbackBg ?? '#dee2e6';
    const width = (styleObj['--borderWidth'] ?? 1) + 'px';
    return `border-bottom:${width} solid ${color};`;
  }
  function borderStyleRight(styleObj, fallbackBg) {
    const hasBorder = styleObj?.['--borderColor'] != null || styleObj?.['--borderWidth'] != null;
    if (!hasBorder) return '';
    const color = styleObj['--borderColor'] ?? styleObj?.backgroundColor ?? fallbackBg ?? '#dee2e6';
    const width = (styleObj['--borderWidth'] ?? 1) + 'px';
    return `border-right:${width} solid ${color};`;
  }
</script>

{#if struttura.length === 0}
  <div class="text-muted small text-center py-4">
    Aggiungi {$etichettaStruttura.plurale.toLowerCase()} per vedere l'anteprima griglia.
  </div>
{:else}
  <div class="gp-wrap">
    <table class="gp-table">
      <thead>
        <tr>
          <th class="gp-th-turno">Turno</th>
          {#each Array(NUM_GIORNI) as _, i}
            <th class="gp-th-giorno" class:gp-fest={i >= 5}>
              <div class="fw-bold">{i + 1}</div>
              <div class="gp-day-name">{NOMI_GG[i]}</div>
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each struttura as sg}
          {@const sgStyle = effectiveSgStyle(sg)}
          {@const sgRepeat = sgStyle['--repeatName'] ?? false}
          {@const sgBorder = borderStyle(sg.style, '#d6d8db')}
          <tr>
            {#if sgRepeat}
              <td class="gp-sep-sg gp-sep-empty" style="{sgBorder}{toStyleStr(sgStyle)}"></td>
              <td colspan={NUM_GIORNI} class="gp-sep-sg" style="{sgBorder}{toStyleStr(sgStyle)}">
                <div class="gp-repeat">
                  <span>{sg.nome || sg.sigla}</span>
                  <span>{sg.nome || sg.sigla}</span>
                  <span>{sg.nome || sg.sigla}</span>
                </div>
              </td>
            {:else}
              <td colspan={NUM_GIORNI + 1} class="gp-sep-sg"
                  style="{sgBorder}{toStyleStr(sgStyle)}">
                <i class="bi bi-collection me-1"></i>{sg.nome || sg.sigla}
              </td>
            {/if}
          </tr>

          {#each sg.gruppi as g}
            {@const gStyle = effectiveGruppoStyle(g)}
            {@const repeatName = gStyle['--repeatName'] ?? false}
            {@const gBorder = borderStyle(g.style, '#e9ecef')}
            <tr>
              {#if repeatName}
                <td class="gp-sep-g gp-sep-empty" style="{gBorder}{toStyleStr(gStyle)}"></td>
                <td colspan={NUM_GIORNI} class="gp-sep-g" style="{gBorder}{toStyleStr(gStyle)}">
                  <div class="gp-repeat">
                    <span>{g.nome || g.sigla}</span>
                    <span>{g.nome || g.sigla}</span>
                    <span>{g.nome || g.sigla}</span>
                  </div>
                </td>
              {:else}
                <td colspan={NUM_GIORNI + 1} class="gp-sep-g"
                    style="{gBorder}{toStyleStr(gStyle)}">
                  {g.nome || g.sigla}
                </td>
              {/if}
            </tr>

            {#each g.turni as t}
              {@const tStyle = t.style ?? {}}
              {@const colBase = effectiveColStyle(g)}
              {@const mergedCol = { ...colBase, ...tStyle }}
              <tr>
                <td class="gp-col-turno" style="{borderStyleRight(g.style, '#e9ecef')}{toStyleStr(mergedCol)}">
                  {t.nome || t.sigla}
                </td>
                {#each Array(NUM_GIORNI) as _, i}
                  <td class="gp-cell" class:gp-fest={i >= 5}
                      style={effectiveTurnoStyle(t)}>
                    <span class="gp-dash">—</span>
                  </td>
                {/each}
              </tr>
            {/each}
          {/each}
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .gp-wrap {
    overflow: auto;
    max-height: 100%;
    border: 1px solid #dee2e6;
    border-radius: 4px;
    background: #fff;
  }

  .gp-table {
    border-collapse: separate;
    border-spacing: 0;
    width: 100%;
    font-size: .75rem;
  }

  /* Header */
  .gp-th-turno {
    position: sticky; left: 0; top: 0; z-index: 20;
    background: #0d6efd; color: #fff;
    min-width: 90px; max-width: 90px;
    padding: 4px 6px;
    border-right: 2px solid #dee2e6;
    border-bottom: 2px solid #dee2e6;
    font-weight: 600;
  }

  .gp-th-giorno {
    position: sticky; top: 0; z-index: 15;
    background: #0d6efd; color: #fff;
    min-width: 44px; max-width: 44px;
    text-align: center; padding: 2px 0;
    border-bottom: 2px solid #dee2e6;
    font-size: .68rem;
  }
  .gp-th-giorno.gp-fest { background: #0b5ed7; }

  .gp-day-name { font-size: .55rem; opacity: .8; font-weight: normal; }

  /* Separatori SG / Gruppo */
  .gp-sep-sg {
    padding: 3px 6px;
    font-size: .72rem;
    font-weight: bold;
    border-bottom: 1px solid #ccc;
  }

  .gp-sep-g {
    padding: 1px 12px;
    font-size: .68rem;
    border-bottom: 1px solid #dee2e6;
  }

  .gp-repeat {
    display: flex;
    justify-content: space-around;
    width: 100%;
  }

  /* Colonna turno (prima colonna) */
  .gp-col-turno {
    position: sticky; left: 0; z-index: 10;
    min-width: 90px; max-width: 90px;
    padding: 2px 6px 2px 16px;
    font-weight: 600;
    font-size: .72rem;
    border-right: 2px solid #dee2e6;
    border-bottom: 1px solid #eee;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* Celle griglia */
  .gp-cell {
    min-width: 44px; max-width: 44px;
    height: 26px;
    text-align: center;
    vertical-align: middle;
    border-bottom: 1px solid #eee;
    border-right: 1px solid #f0f0f0;
    padding: 0;
  }
  .gp-cell.gp-fest { background: #fef3cd; }

  .gp-dash {
    color: #ccc;
    font-size: .65rem;
  }
</style>
