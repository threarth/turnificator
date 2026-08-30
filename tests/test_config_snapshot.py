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


# ---------------------------------------------------------------------------
# Le ore giustificate restano quelle del momento in cui si e' chiuso
# ---------------------------------------------------------------------------

def _tipo_richiesta_assenza_contabile(client, token, auth):
    """Il primo tipo richiesta che vale come ora giustificata."""
    rv = client.get('/api/admin/tipi-richiesta', headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    return next(
        t for t in rv.get_json()['tipi']
        if t['tipo'] == 'assenza' and t['counting_flag']
    )


def _ore_giustificate(client, token, auth, cal_id):
    """Somma delle ore giustificate di tutti i lavoratori."""
    rv = client.get(f'/api/manager/calendari/{cal_id}/ore', headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    return sum(r['ore_giustificate'] for r in rv.get_json()['ore'])


def test_le_ore_non_cambiano_se_cambia_il_tipo_richiesta(
        client, admin_token, auth, _test_env):
    """
    Un calendario chiuso mesi fa non deve riscriversi le ore perche' oggi
    qualcuno ha tolto la spunta "conta" a un tipo di assenza.
    """
    from tests.conftest import _open_sqlcipher

    cal_id = _crea_calendario(client, admin_token, auth, mese=10)
    tipo = _tipo_richiesta_assenza_contabile(client, admin_token, auth)

    # Un'assenza contabile a calendario gia' creato, cioe' gia' congelato.
    db = _open_sqlcipher(_test_env['tenant_path'], _test_env['tenant_key'])
    uid = db.execute("SELECT id FROM users WHERE username='basic_t'").fetchone()['id']
    db.execute(
        "INSERT INTO working_desiderata (calendario_id, user_id, giorno, tipo_richiesta_id) "
        "VALUES (?,?,?,?)",
        (cal_id, uid, 5, tipo['id'])
    )
    db.commit()

    ore_prima = _ore_giustificate(client, admin_token, auth, cal_id)
    assert ore_prima > 0, 'il caso non prova nulla se non ci sono ore giustificate'

    # La configurazione cambia dopo: il calendario non deve accorgersene.
    rv = client.put(f"/api/admin/tipi-richiesta/{tipo['id']}",
                    json={**tipo, 'counting_flag': 0}, headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    assert _ore_giustificate(client, admin_token, auth, cal_id) == ore_prima
