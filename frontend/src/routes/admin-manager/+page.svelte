<script>
  import { goto } from '$app/navigation';
  // Redirect permanente: /admin-manager → /admin (la pagina ora gestisce entrambi i ruoli)
  goto('/admin', { replaceState: true });
</script>
