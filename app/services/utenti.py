"""
app/services/utenti.py — i nomi degli account che il sistema crea da se'.

Due livelli, deliberatamente distinti per nome perche' hanno poteri diversi
e vivono in database diversi:

- il **superadmin** sta in `master.db` ed e' il vertice della piattaforma:
  crea i tenant, li disattiva, resetta le password dei loro amministratori;
- gli **amministratori di tenant** sono numerati, e il numero segue il
  tenant: `admin1` amministra il primo, `admin2` il secondo. Ciascuno vede
  solo il proprio, e nessuno vede gli altri.

Il numero non e' decorativo: prima si chiamavano tutti `admin_uo`, e da quel
nome non si capiva di quale organizzazione si stesse parlando.
"""

# L'amministratore di piattaforma, in master_users.
NOME_SUPERADMIN = 'superadmin'

# Gli amministratori di tenant: al prefisso si aggiunge il numero del tenant.
PREFISSO_ADMIN_TENANT = 'admin'

# Sigla con cui l'amministratore compare nelle griglie del suo tenant.
SIGLA_ADMIN = 'ADM'


def nome_admin_tenant(numero):
    """
    Il nome dell'amministratore del tenant numero `numero`.

    Args:
        numero (int): numero del tenant, da 1.

    Returns:
        str: es. 'admin1'.
    """
    return f'{PREFISSO_ADMIN_TENANT}{numero}'
