<!--
  Toast — contenitore globale messaggi toast (bottom-right).
  Da montare una sola volta in +layout.svelte.
-->
<script>
  import { toasts } from '$lib/toast.js';
</script>

<div style="position:fixed;bottom:1.25rem;right:1.25rem;z-index:99999;display:flex;flex-direction:column;gap:.5rem;pointer-events:none">
  {#each $toasts as t (t.id)}
    <div style="
      min-width:220px;max-width:340px;
      padding:.6rem 1rem;
      border-radius:.4rem;
      font-size:.875rem;
      font-weight:500;
      box-shadow:0 4px 12px rgba(0,0,0,.2);
      color:#fff;
      background:{t.ok ? '#198754' : '#dc3545'};
      display:flex;align-items:center;gap:.5rem
    ">
      <i class="bi {t.ok ? 'bi-check-circle-fill' : 'bi-exclamation-triangle-fill'}"></i>
      {t.message}
    </div>
  {/each}
</div>
