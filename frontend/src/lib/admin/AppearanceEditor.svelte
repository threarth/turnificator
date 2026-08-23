<script context="module">
    /** Chiavi e metadati per l'editor appearance. */
    export const APPEARANCE_KEYS = [
        { key: 'festivi_bg',             label: 'Sfondo festivi',              type: 'color'  },
        { key: 'superfestivi_bg',        label: 'Sfondo superfestivi',         type: 'color'  },
        { key: 'prima_riga_bg',          label: 'Sfondo prima riga (turni)',   type: 'color'  },
        { key: 'cella_bordo_colore',     label: 'Colore bordo cella',          type: 'color'  },
        { key: 'cella_bordo_spessore',   label: 'Spessore bordo cella',        type: 'number' },
        { key: 'bordo_esterno_colore',   label: 'Colore bordo esterno',        type: 'color'  },
        { key: 'bordo_esterno_spessore', label: 'Spessore bordo esterno',      type: 'number' },
    ];

    /** Valori di default (allineati con APPEARANCE_DEFAULT in config_snapshot.py). */
    export const APPEARANCE_DEFAULT = {
        festivi_bg:             '#fff3cd',
        superfestivi_bg:        '#f8d7da',
        prima_riga_bg:          '#f8f9fa',
        cella_bordo_colore:     '#dee2e6',
        cella_bordo_spessore:   1,
        bordo_esterno_colore:   '#adb5bd',
        bordo_esterno_spessore: 2,
    };
</script>

<script>
    /**
     * Editor riutilizzabile per l'appearance della griglia.
     * Usato sia nel preset editor (admin) sia nella modale aspetto del manager.
     * Non include pulsante salva — gestito dal componente padre.
     *
     * Props:
     *   appearance  — oggetto corrente dei valori
     *   onchange    — callback(newAppearance) chiamato a ogni modifica
     */
    let { appearance, onchange } = $props();

    function update(key, value) {
        onchange({ ...appearance, [key]: value });
    }

    function resetKey(key) {
        onchange({ ...appearance, [key]: APPEARANCE_DEFAULT[key] });
    }

    function resetAll() {
        onchange({ ...APPEARANCE_DEFAULT });
    }

    function isDirtyKey(key) {
        return String(appearance[key]) !== String(APPEARANCE_DEFAULT[key]);
    }
</script>

<div class="row g-2">
    {#each APPEARANCE_KEYS as ak}
        <div class="col-6">
            <label class="form-label small mb-1">{ak.label}</label>
            <div class="d-flex align-items-center gap-1 flex-wrap">
                {#if ak.type === 'color'}
                    <input type="color"
                           class="form-control form-control-color form-control-sm flex-shrink-0"
                           style="width:34px;height:26px;padding:2px"
                           value={appearance[ak.key] ?? APPEARANCE_DEFAULT[ak.key]}
                           oninput={e => update(ak.key, e.target.value)} />
                    <input type="text"
                           class="form-control form-control-sm font-monospace"
                           style="max-width:82px"
                           value={appearance[ak.key] ?? APPEARANCE_DEFAULT[ak.key]}
                           oninput={e => update(ak.key, e.target.value)} />
                    <div class="flex-shrink-0"
                         style="width:20px;height:20px;border-radius:3px;border:1px solid #ccc;
                                background:{appearance[ak.key] ?? APPEARANCE_DEFAULT[ak.key]}">
                    </div>
                {:else}
                    <input type="number" min="0" max="10"
                           class="form-control form-control-sm"
                           style="max-width:60px"
                           value={appearance[ak.key] ?? APPEARANCE_DEFAULT[ak.key]}
                           oninput={e => update(ak.key, +e.target.value)} />
                    <span class="text-muted small">px</span>
                {/if}

                {#if isDirtyKey(ak.key)}
                    <button class="btn btn-sm btn-link text-secondary p-0 ms-auto"
                            title="Ripristina default"
                            onclick={() => resetKey(ak.key)}>
                        <i class="bi bi-arrow-counterclockwise"></i>
                    </button>
                {/if}
            </div>
        </div>
    {/each}
</div>

<div class="mt-2">
    <button class="btn btn-sm btn-outline-secondary"
            onclick={resetAll}
            title="Ripristina tutti i valori predefiniti">
        <i class="bi bi-arrow-counterclockwise me-1"></i>Reset tutto
    </button>
</div>
