"""
tests/test_config_snapshot.py — lo snapshot di configurazione del calendario.

Un calendario congela la configurazione con cui e' stato costruito, cosi'
riaprirlo mesi dopo non lo rilegge con le regole di oggi. Lo snapshot copre
ora l'intera configurazione: fasce, tipologie, tipi richiesta, regole,
vincoli e conteggi.

I test creano un calendario dalle API e guardano cosa e' finito dentro.
"""


def _crea_calendario(client, token, auth, mese=9, anno=2026):
    """Crea un calendario e ne restituisce l'id."""
    rv = client.post('/api/admin/calendari', json={'mese': mese, 'anno': anno},
                     headers=auth(token))
    assert rv.status_code == 201, rv.get_json()

    return rv.get_json()['id']


def _snapshot_del_calendario(client, token, auth, cal_id):
    """Legge lo snapshot come lo vede la pagina manager."""
    rv = client.get(f'/api/manager/calendari/{cal_id}/struttura', headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    return rv.get_json()['config_snapshot']


# ---------------------------------------------------------------------------
# Cosa finisce nello snapshot
# ---------------------------------------------------------------------------

def test_snapshot_copre_tutta_la_configurazione(client, admin_token, auth):
    """Le quattro parti aggiunte ci sono, accanto a quelle di prima."""
    cal_id = _crea_calendario(client, admin_token, auth)
    snap = _snapshot_del_calendario(client, admin_token, auth, cal_id)

    for parte in ('flag_turno', 'vincoli_globali', 'vincoli_solver',
                  'tipi_qualitativo', 'tipi_richiesta', 'regole_conflitto',
                  'conteggi_context'):
        assert parte in snap, f'manca {parte} nello snapshot'


def test_regole_nello_snapshot_sono_una_lista(client, admin_token, auth):
    """Non una stringa JSON: chi le legge non deve doverle deserializzare."""
    cal_id = _crea_calendario(client, admin_token, auth)
    snap = _snapshot_del_calendario(client, admin_token, auth, cal_id)

    assert isinstance(snap['regole_conflitto'], list)
    if snap['regole_conflitto']:
        assert isinstance(snap['regole_conflitto'][0], dict)


def test_tipi_richiesta_congelati_con_i_loro_parametri(client, admin_token, auth):
    """Servono a rileggere un desiderata come era quando fu inserito."""
    cal_id = _crea_calendario(client, admin_token, auth)
    snap = _snapshot_del_calendario(client, admin_token, auth, cal_id)

    assert snap['tipi_richiesta']
    primo = snap['tipi_richiesta'][0]
    for campo in ('id', 'sigla', 'tipo', 'counting_flag', 'flag_id'):
        assert campo in primo


# ---------------------------------------------------------------------------
# I lettori
# ---------------------------------------------------------------------------

def test_lettori_senza_snapshot_restituiscono_vuoto(app):
    """Un calendario senza snapshot non deve far esplodere niente."""
    from app.services.config_snapshot import (
        snap_conteggi_context, snap_regole_conflitto,
        snap_tipi_qualitativo, snap_tipi_richiesta,
    )

    assert snap_regole_conflitto(None) == []
    assert snap_tipi_richiesta(None) == {}
    assert snap_tipi_qualitativo(None) == {}
    assert snap_conteggi_context(None) == []


def test_le_regole_disattivate_restano_fuori(app):
    """Chi legge le regole vuole quelle in vigore, non l'archivio."""
    from app.services.config_snapshot import snap_regole_conflitto

    snap = {'regole_conflitto': [
        {'id': 1, 'nome': 'attiva', 'is_active': 1},
        {'id': 2, 'nome': 'spenta', 'is_active': 0},
    ]}

    assert [r['nome'] for r in snap_regole_conflitto(snap)] == ['attiva']


def test_tipi_richiesta_indicizzati_per_id(app):
    """I chiamanti risolvono un desiderata partendo dal suo tipo_richiesta_id."""
    from app.services.config_snapshot import snap_tipi_richiesta

    snap = {'tipi_richiesta': [{'id': 7, 'sigla': 'F', 'counting_flag': 1}]}
    tipi = snap_tipi_richiesta(snap)

    assert tipi[7]['sigla'] == 'F'
    assert tipi[7]['counting_flag'] == 1
