"""
tests/test_festivita.py — le festivita' come dato del tenant.

Erano tredici date scritte nel codice, uguali per ogni organizzazione: fra
loro i Santi Pietro e Paolo, che e' il patrono di Roma e non di chi sta
altrove. Ora sono ricorrenze in tabella, seminate con quelle nazionali e
modificabili da chi configura.

Una ricorrenza o cade sempre nello stesso giorno dell'anno, o si conta dalla
Pasqua, che si sposta. Le date concrete si ricavano alla creazione di un
calendario, per l'anno di quel calendario.
"""

import importlib.util
import os

import pytest

from tests.conftest import _open_sqlcipher

# Il servizio si carica dal file: importare il pacchetto `app` in fase di
# collection fisserebbe la configurazione prima delle fixture.
_PERCORSO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'app', 'services', 'calendario_giorni.py'
)
_spec = importlib.util.spec_from_file_location('calendario_giorni', _PERCORSO)
cg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cg)


# ---------------------------------------------------------------------------
# Il calcolo delle date
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('anno, atteso', [
    (2024, '2024-03-31'),
    (2025, '2025-04-20'),
    (2026, '2026-04-05'),
    (2027, '2027-03-28'),
])
def test_la_pasqua_cade_dove_deve(anno, atteso):
    """Le date del foglio d'esempio, che le portava anno per anno."""
    assert cg.pasqua(anno).isoformat() == atteso


def test_una_ricorrenza_fissa_cade_ogni_anno_uguale():
    liberazione = {'giorno': 25, 'mese': 4, 'offset_pasqua': None}

    assert cg.data_della_ricorrenza(liberazione, 2026).isoformat() == '2026-04-25'
    assert cg.data_della_ricorrenza(liberazione, 2027).isoformat() == '2027-04-25'


def test_una_ricorrenza_contata_dalla_pasqua_si_sposta():
    pasquetta = {'giorno': None, 'mese': None, 'offset_pasqua': 1}

    assert cg.data_della_ricorrenza(pasquetta, 2026).isoformat() == '2026-04-06'
    assert cg.data_della_ricorrenza(pasquetta, 2027).isoformat() == '2027-03-29'


def test_un_giorno_che_quell_anno_non_esiste_non_cade():
    """Il 29 febbraio di un anno non bisestile non e' un errore: non c'e'."""
    bisestile = {'giorno': 29, 'mese': 2, 'offset_pasqua': None}

    assert cg.data_della_ricorrenza(bisestile, 2026) is None
    assert cg.data_della_ricorrenza(bisestile, 2028) is not None


def test_le_ricorrenze_spente_non_producono_date():
    righe = [
        {'giorno': 25, 'mese': 4, 'offset_pasqua': None, 'tipo': 'superfestivo', 'is_active': 1},
        {'giorno': 29, 'mese': 6, 'offset_pasqua': None, 'tipo': 'superfestivo', 'is_active': 0},
    ]

    assert cg.espandi_festivita(righe, 2026) == {
        'festivi': [], 'superfestivi': ['2026-04-25'],
    }


# ---------------------------------------------------------------------------
# L'elenco di serie
# ---------------------------------------------------------------------------

def test_il_tenant_nasce_con_le_festivita_nazionali(client, admin_token, auth):
    """Il comportamento di prima resta il punto di partenza."""
    rv = client.get('/api/admin/festivita?anno=2026', headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    nomi = {f['nome'] for f in rv.get_json()['festivita']}
    assert 'Natale' in nomi
    assert 'Liberazione' in nomi
    assert 'Pasqua' in nomi


def test_le_date_arrivano_calcolate_per_l_anno_chiesto(client, admin_token, auth):
    """Chi le mostra non deve rifare il conto della Pasqua."""
    festivita = client.get('/api/admin/festivita?anno=2026',
                           headers=auth(admin_token)).get_json()['festivita']

    per_nome = {f['nome']: f['data'] for f in festivita}
    assert per_nome['Pasqua'] == '2026-04-05'
    assert per_nome['Liberazione'] == '2026-04-25'


def test_i_dovuti_di_aprile_2026_tornano_col_foglio(client, admin_token, auth, _test_env):
    """
    Con le festivita' di serie, aprile 2026 fa 24 turni dovuti: e' il numero
    che il foglio d'esempio porta in testa al riepilogo.
    """
    rv = client.post('/api/admin/calendari', json={'mese': 4, 'anno': 2026},
                     headers=auth(admin_token))
    assert rv.status_code == 201, rv.get_json()
    cal_id = rv.get_json()['id']

    db = _open_sqlcipher(_test_env['tenant_path'], _test_env['tenant_key'])
    dovuti = db.execute(
        "SELECT COUNT(*) AS n FROM giorni_calendario "
        "WHERE calendario_id=? AND is_lavorativo=1", (cal_id,)
    ).fetchone()['n']

    assert dovuti == 24


# ---------------------------------------------------------------------------
# Modificarle
# ---------------------------------------------------------------------------

def _festivita_per_nome(client, token, auth, nome, anno=2026):
    rv = client.get(f'/api/admin/festivita?anno={anno}', headers=auth(token))
    return next((f for f in rv.get_json()['festivita'] if f['nome'] == nome), None)


def test_spegnere_il_patrono_lo_toglie_dal_calendario(client, admin_token, auth, _test_env):
    """
    I Santi Pietro e Paolo sono il patrono di Roma: chi sta altrove lo spegne,
    e da quel momento il 29 giugno torna un giorno come gli altri.
    """
    patrono = _festivita_per_nome(client, admin_token, auth, 'Santi Pietro e Paolo')
    assert patrono is not None

    rv = client.put(f"/api/admin/festivita/{patrono['id']}", json={'is_active': 0},
                    headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    rv = client.post('/api/admin/calendari', json={'mese': 6, 'anno': 2027},
                     headers=auth(admin_token))
    assert rv.status_code == 201, rv.get_json()

    db = _open_sqlcipher(_test_env['tenant_path'], _test_env['tenant_key'])
    giorno = db.execute(
        "SELECT tipo, is_lavorativo FROM giorni_calendario "
        "WHERE calendario_id=? AND giorno=29", (rv.get_json()['id'],)
    ).fetchone()

    # Il 29 giugno 2027 e' un martedi': senza il patrono e' lavorativo.
    assert giorno['tipo'] == 'normale'
    assert giorno['is_lavorativo'] == 1


def test_una_festivita_locale_si_aggiunge(client, admin_token, auth, _test_env):
    """Ogni installazione ha il suo santo, e ora puo' dirlo."""
    rv = client.post('/api/admin/festivita',
                     json={'nome': 'San Giovanni', 'giorno': 24, 'mese': 6},
                     headers=auth(admin_token))
    assert rv.status_code == 201, rv.get_json()

    rv = client.post('/api/admin/calendari', json={'mese': 6, 'anno': 2027},
                     headers=auth(admin_token))
    assert rv.status_code == 201, rv.get_json()

    db = _open_sqlcipher(_test_env['tenant_path'], _test_env['tenant_key'])
    giorno = db.execute(
        "SELECT tipo, is_lavorativo FROM giorni_calendario "
        "WHERE calendario_id=? AND giorno=24", (rv.get_json()['id'],)
    ).fetchone()

    assert giorno['tipo'] == 'superfestivo'
    assert giorno['is_lavorativo'] == 0


def test_una_festivita_senza_data_viene_rifiutata(client, admin_token, auth):
    """Senza data fissa ne distanza dalla Pasqua non individua nessun giorno."""
    rv = client.post('/api/admin/festivita', json={'nome': 'Senza data'},
                     headers=auth(admin_token))

    assert rv.status_code == 400
    assert 'giorno e mese' in rv.get_json()['errore']


def test_due_festivita_non_possono_chiamarsi_uguale(client, admin_token, auth):
    rv = client.post('/api/admin/festivita',
                     json={'nome': 'Natale', 'giorno': 25, 'mese': 12},
                     headers=auth(admin_token))

    assert rv.status_code == 409


def test_solo_l_amministratore_le_cambia(client, manager_token, auth):
    """Il manager le vede — gli servono per leggere il calendario — non le tocca."""
    assert client.get('/api/admin/festivita?anno=2026',
                      headers=auth(manager_token)).status_code == 200
    assert client.post('/api/admin/festivita',
                       json={'nome': 'Prova', 'giorno': 1, 'mese': 3},
                       headers=auth(manager_token)).status_code == 403
