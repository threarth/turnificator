<script>
  /**
   * /basic — pagina inserimento desiderata per utenti con ruolo "basic".
   *
   * Thin wrapper che monta il componente condiviso DesiderataInserimento,
   * usato anche dal tab "Inserisci Desiderata" in /manager per
   * manager/admin non esclusi dai turni.
   */
  import DesiderataInserimento from '$lib/DesiderataInserimento.svelte';
</script>

<DesiderataInserimento />
