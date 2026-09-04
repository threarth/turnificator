"""
tests/test_composizione_fasce.py — fasce «solo su richiesta» e composizione.

Due impostazioni della stessa sezione, che il riempimento automatico legge:

- `solo_su_richiesta`: la fascia si mette solo dove il lavoratore l'ha
  chiesta, mai di iniziativa del programma. E' il caso della lunga.
- `flag_composizione`: quali fasce, insieme, soddisfano la richiesta di
  un'altra. Chi chiede la lunga puo' ricevere mattina + pomeriggio, e la
  richiesta e' soddisfatta solo quando le ha tutte e due — finche' ne manca
  una la copertura e' parziale, che non e' un errore.

Questi test passano dal database: usano le fixture di conftest.py, che
puntano l'ambiente a database temporanei prima di importare `app`.
"""

import importlib.util
import os

import pytest

from tests.conftest import _open_sqlcipher

# Il modulo si carica dal file invece che con "from app.services import ...":
# importare il pacchetto `app` in fase di collection fisserebbe la
# configurazione di produzione prima che le fixture puntino l'ambiente ai
# database temporanei. fasce_orarie non ha dipendenze, quindi caricarlo
# isolato e' sicuro. Le parti che vogliono il database importano dentro
# al test, quando l'ambiente e' gia' a posto.
_PERCORSO_MODULO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'app', 'services', 'fasce_orarie.py'
)
_spec = importlib.util.spec_from_file_location('fasce_orarie', _PERCORSO_MODULO)
fo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fo)

COPERTURA_MATCH = fo.COPERTURA_MATCH
COPERTURA_PARZIALE = fo.COPERTURA_PARZIALE
COPERTURA_MISMATCH = fo.COPERTURA_MISMATCH
copertura_richiesta = fo.copertura_richiesta
costruisci_mappa_flag = fo.costruisci_mappa_flag
solo_su_richiesta = fo.solo_su_richiesta


# Gerarchia di prova: i concetti root, le tre fasce diurne e la notte.
# Rispecchia il seed, con gli id fissati per leggibilita'.
ID_DIURNO, ID_NOTTURNO = 1, 2
ID_MATTINA, ID_POMERIGGIO, ID_LUNGA, ID_NOTTE = 10, 11, 12, 13

RIGHE_FLAG = [
    {'id': ID_DIURNO,     'nome': 'diurno',     'parent_id': None, 'solo_su_richiesta': 0},
    {'id': ID_NOTTURNO,   'nome': 'notturno',   'parent_id': None, 'solo_su_richiesta': 0},
    {'id': ID_MATTINA,    'nome': 'mattina',    'parent_id': ID_DIURNO,   'solo_su_richiesta': 0},
    {'id': ID_POMERIGGIO, 'nome': 'pomeriggio', 'parent_id': ID_DIURNO,   'solo_su_richiesta': 0},
    {'id': ID_LUNGA,      'nome': 'lunga',      'parent_id': ID_DIURNO,   'solo_su_richiesta': 1},
    {'id': ID_NOTTE,      'nome': 'notte',      'parent_id': ID_NOTTURNO, 'solo_su_richiesta': 0},
]

# La lunga e' la somma di mattina e pomeriggio.
RIGHE_COMPOSIZIONE = [
    {'flag_id': ID_LUNGA, 'componente_flag_id': ID_MATTINA},
    {'flag_id': ID_LUNGA, 'componente_flag_id': ID_POMERIGGIO},
]


@pytest.fixture
def mappa():
    """La gerarchia di prova, nella forma che il codice interroga."""
    return costruisci_mappa_flag(RIGHE_FLAG, RIGHE_COMPOSIZIONE)


# ---------------------------------------------------------------------------
# Copertura di una richiesta
# ---------------------------------------------------------------------------

def test_la_fascia_chiesta_soddisfa_da_sola(mappa):
    """Chi chiede la lunga e riceve la lunga e' servito."""
    assert copertura_richiesta('lunga', ID_LUNGA, mappa) == COPERTURA_MATCH


def test_la_discendenza_soddisfa_la_richiesta_del_concetto(mappa):
    """Una richiesta sul concetto la soddisfa ogni fascia che ne discende."""
    assert copertura_richiesta('mattina', ID_DIURNO, mappa) == COPERTURA_MATCH


def test_un_pezzo_solo_e_una_copertura_parziale(mappa):
    """Chi ha chiesto la lunga e ha solo la mattina non e' in errore."""
    assert copertura_richiesta('mattina', ID_LUNGA, mappa) == COPERTURA_PARZIALE


def test_tutti_i_pezzi_soddisfano_la_richiesta(mappa):
    """Mattina piu' pomeriggio fanno la lunga: la richiesta e' soddisfatta."""
    copertura = copertura_richiesta('mattina', ID_LUNGA, mappa, ['pomeriggio'])

    assert copertura == COPERTURA_MATCH


def test_una_fascia_estranea_resta_un_mismatch(mappa):
    """La notte non compone la lunga: e' un'altra cosa, anche accanto ai pezzi."""
    copertura = copertura_richiesta('notte', ID_LUNGA, mappa, ['mattina'])

    assert copertura == COPERTURA_MISMATCH


def test_senza_composizione_un_pezzo_e_un_mismatch(mappa):
    """
    Il parziale esiste solo dove una composizione e' stata impostata: e'
    quella a dire che i pezzi contano, non la loro somiglianza.
    """
    senza = costruisci_mappa_flag(RIGHE_FLAG)

    assert copertura_richiesta('mattina', ID_LUNGA, senza) == COPERTURA_MISMATCH


def test_nessuna_richiesta_non_e_mai_un_errore(mappa):
    """Senza fascia richiesta ogni turno va bene."""
    assert copertura_richiesta('notte', None, mappa) == COPERTURA_MATCH


# ---------------------------------------------------------------------------
# Fasce riservate alle richieste
# ---------------------------------------------------------------------------

def test_la_fascia_riservata_si_riconosce(mappa):
    """La lunga e' riservata a chi la chiede."""
    assert solo_su_richiesta(ID_LUNGA, mappa) is True


def test_le_altre_fasce_non_lo_sono(mappa):
    """La mattina il programma la mette di sua iniziativa."""
    assert solo_su_richiesta(ID_MATTINA, mappa) is False


def test_la_riserva_vale_per_discendenza():
    """
    Se il concetto e' riservato alle richieste lo sono anche le sue fasce:
    diversamente basterebbe una fascia figlia per aggirarlo.
    """
    righe = [dict(r) for r in RIGHE_FLAG]
    for r in righe:
        if r['id'] == ID_NOTTURNO:
            r['solo_su_richiesta'] = 1

    assert solo_su_richiesta(ID_NOTTE, costruisci_mappa_flag(righe)) is True


# ---------------------------------------------------------------------------
# API: scrittura della composizione
# ---------------------------------------------------------------------------

def _flag_per_nome(client, token, auth, nome):
    """Restituisce dalla lista API il flag con quel nome, o None."""
    rv = client.get('/api/admin/flag-turno', headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    return next((f for f in rv.get_json()['flags'] if f['nome'] == nome), None)


def test_la_composizione_si_scrive_e_si_rilegge(client, admin_token, auth):
    """Impostare «la lunga e' mattina + pomeriggio» e ritrovarla nella lista."""
    lunga = _flag_per_nome(client, admin_token, auth, 'lunga')
    mattina = _flag_per_nome(client, admin_token, auth, 'mattina')
    pomeriggio = _flag_per_nome(client, admin_token, auth, 'pomeriggio')

    rv = client.put(
        f"/api/admin/flag-turno/{lunga['id']}",
        json={'componenti': [mattina['id'], pomeriggio['id']],
              'solo_su_richiesta': True},
        headers=auth(admin_token)
    )
    assert rv.status_code == 200, rv.get_json()

    aggiornata = _flag_per_nome(client, admin_token, auth, 'lunga')
    assert sorted(aggiornata['componenti']) == sorted([mattina['id'], pomeriggio['id']])
    assert aggiornata['solo_su_richiesta'] == 1


def test_la_composizione_si_riscrive_intera(client, admin_token, auth):
    """L'elenco sostituisce il precedente: non si accumulano componenti."""
    lunga = _flag_per_nome(client, admin_token, auth, 'lunga')
    mattina = _flag_per_nome(client, admin_token, auth, 'mattina')
    pomeriggio = _flag_per_nome(client, admin_token, auth, 'pomeriggio')

    for componenti in ([mattina['id'], pomeriggio['id']], [mattina['id']]):
        rv = client.put(
            f"/api/admin/flag-turno/{lunga['id']}",
            json={'componenti': componenti}, headers=auth(admin_token)
        )
        assert rv.status_code == 200, rv.get_json()

    assert _flag_per_nome(client, admin_token, auth, 'lunga')['componenti'] == [mattina['id']]


def test_una_fascia_non_compone_se_stessa(client, admin_token, auth):
    """Una composizione circolare non e' una richiesta soddisfacibile."""
    lunga = _flag_per_nome(client, admin_token, auth, 'lunga')

    rv = client.put(
        f"/api/admin/flag-turno/{lunga['id']}",
        json={'componenti': [lunga['id']]}, headers=auth(admin_token)
    )
    assert rv.status_code == 400
    assert 'se stessa' in rv.get_json()['errore']


def test_un_componente_inesistente_e_un_errore(client, admin_token, auth):
    """Un id sconosciuto e' un errore del chiamante, non una riga da saltare."""
    lunga = _flag_per_nome(client, admin_token, auth, 'lunga')

    rv = client.put(
        f"/api/admin/flag-turno/{lunga['id']}",
        json={'componenti': [999999]}, headers=auth(admin_token)
    )
    assert rv.status_code == 400
    assert 'non trovata' in rv.get_json()['errore']


def test_una_put_che_non_ne_parla_lascia_la_composizione(client, admin_token, auth):
    """Correggere un orario non cancella la composizione impostata."""
    lunga = _flag_per_nome(client, admin_token, auth, 'lunga')
    mattina = _flag_per_nome(client, admin_token, auth, 'mattina')

    client.put(f"/api/admin/flag-turno/{lunga['id']}",
               json={'componenti': [mattina['id']]}, headers=auth(admin_token))
    rv = client.put(f"/api/admin/flag-turno/{lunga['id']}",
                    json={'orario_inizio': '08:00', 'orario_fine': '20:40'},
                    headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    assert _flag_per_nome(client, admin_token, auth, 'lunga')['componenti'] == [mattina['id']]


def test_la_fascia_nasce_gia_composta(client, admin_token, auth):
    """La composizione si puo' dare alla creazione, non solo dopo."""
    mattina = _flag_per_nome(client, admin_token, auth, 'mattina')

    rv = client.post(
        '/api/admin/flag-turno',
        json={'nome': 'mattina_lunga', 'orario_inizio': '08:00',
              'orario_fine': '17:00', 'componenti': [mattina['id']]},
        headers=auth(admin_token)
    )
    assert rv.status_code == 201, rv.get_json()

    assert _flag_per_nome(client, admin_token, auth, 'mattina_lunga')['componenti'] \
        == [mattina['id']]


# ---------------------------------------------------------------------------
# Snapshot di configurazione
# ---------------------------------------------------------------------------

def _snapshot_di_un_calendario(client, token, auth, mese, anno):
    """Crea un calendario e restituisce lo snapshot che ha congelato."""
    rv = client.post('/api/admin/calendari', json={'mese': mese, 'anno': anno},
                     headers=auth(token))
    assert rv.status_code == 201, rv.get_json()
    cal_id = rv.get_json()['id']

    rv = client.get(f'/api/manager/calendari/{cal_id}/struttura', headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    return rv.get_json()['config_snapshot']


def test_lo_snapshot_porta_riserva_e_composizione(client, admin_token, auth):
    """
    Un calendario chiuso va riletto con la configurazione con cui e' stato
    costruito: se la composizione non entra nello snapshot, il solver la
    rilegge dal vivo e i mesi passati cambiano da soli.
    """
    lunga = _flag_per_nome(client, admin_token, auth, 'lunga')
    mattina = _flag_per_nome(client, admin_token, auth, 'mattina')
    client.put(f"/api/admin/flag-turno/{lunga['id']}",
               json={'componenti': [mattina['id']], 'solo_su_richiesta': True},
               headers=auth(admin_token))

    snap = _snapshot_di_un_calendario(client, admin_token, auth, 5, 2027)

    assert {'flag_id': lunga['id'], 'componente_flag_id': mattina['id']} \
        in snap['flag_composizione']
    voce_lunga = next(f for f in snap['flag_turno'] if f['id'] == lunga['id'])
    assert voce_lunga['solo_su_richiesta'] == 1


def test_la_mappa_dallo_snapshot_conosce_la_composizione(client, admin_token, auth):
    """Chi legge lo snapshot ottiene la stessa risposta di chi legge dal vivo."""
    lunga = _flag_per_nome(client, admin_token, auth, 'lunga')
    mattina = _flag_per_nome(client, admin_token, auth, 'mattina')
    pomeriggio = _flag_per_nome(client, admin_token, auth, 'pomeriggio')
    client.put(f"/api/admin/flag-turno/{lunga['id']}",
               json={'componenti': [mattina['id'], pomeriggio['id']]},
               headers=auth(admin_token))

    snap = _snapshot_di_un_calendario(client, admin_token, auth, 6, 2027)
    mappa_snap = costruisci_mappa_flag(snap['flag_turno'], snap['flag_composizione'])

    assert copertura_richiesta('mattina', lunga['id'], mappa_snap) == COPERTURA_PARZIALE
    assert copertura_richiesta('mattina', lunga['id'], mappa_snap, ['pomeriggio']) \
        == COPERTURA_MATCH


# ---------------------------------------------------------------------------
# La regola che segnala il parziale
# ---------------------------------------------------------------------------

def test_la_regola_del_parziale_esiste_e_non_blocca(app, _test_env):
    """
    Il parziale ha una regola sua, con stile e gravita' configurabili come
    tutte le altre. Non blocca: se bloccasse, il riempimento scarterebbe la
    mattina di chi ha chiesto la lunga e la composizione non si formerebbe.
    """
    from app.services.validatori import TIPO_REGOLA_COMPOSIZIONE_PARZIALE

    db = _open_sqlcipher(_test_env['tenant_path'], _test_env['tenant_key'])
    regola = db.execute(
        "SELECT * FROM regole_conflitto WHERE tipo_regola=?",
        (TIPO_REGOLA_COMPOSIZIONE_PARZIALE,)
    ).fetchone()

    assert regola is not None
    assert regola['blocca_inserimento'] == 0
    assert regola['is_active'] == 1


def test_estendere_i_tipi_regola_e_idempotente(app, _test_env):
    """Rieseguire la migrazione su uno schema gia' esteso non tocca nulla."""
    from app import _estendi_tipi_regola

    db = _open_sqlcipher(_test_env['tenant_path'], _test_env['tenant_key'])
    prima = db.execute("SELECT COUNT(*) AS n FROM regole_conflitto").fetchone()['n']

    _estendi_tipi_regola(db)
    _estendi_tipi_regola(db)

    assert db.execute("SELECT COUNT(*) AS n FROM regole_conflitto").fetchone()['n'] == prima


def test_estendere_i_tipi_regola_conserva_le_regole(app, _test_env):
    """
    Sul vincolo vecchio la tabella si ricostruisce: le regole gia' scritte
    devono ritrovarsi tutte, con gli stessi id.
    """
    from app import _estendi_tipi_regola
    from app.services.validatori import TIPO_REGOLA_COMPOSIZIONE_PARZIALE

    db = _open_sqlcipher(_test_env['tenant_path'], _test_env['tenant_key'])
    attese = {
        (r['id'], r['nome'])
        for r in db.execute("SELECT id, nome FROM regole_conflitto")
    }

    # Riporta la tabella al vincolo di prima, come su un tenant mai migrato.
    db.execute("ALTER TABLE regole_conflitto RENAME TO regole_vecchie")
    db.execute("""
        CREATE TABLE regole_conflitto (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            nome                TEXT    NOT NULL,
            tipo_regola         TEXT    NOT NULL CHECK(tipo_regola IN (
                                    'tipo_vs_tipo',
                                    'desiderata_mismatch',
                                    'desiderata_assenza_mismatch'
                                )),
            flag_a_id           INTEGER REFERENCES flag_turno(id),
            flag_b_id           INTEGER REFERENCES flag_turno(id),
            offset_giorni       INTEGER NOT NULL DEFAULT 0,
            categoria           TEXT    NOT NULL DEFAULT 'consigliata',
            stile               TEXT    NOT NULL DEFAULT '{}',
            blocca_inserimento  INTEGER NOT NULL DEFAULT 0,
            peso_numerico       REAL    NOT NULL DEFAULT 1.0,
            is_active           INTEGER NOT NULL DEFAULT 1
        )
    """)
    db.execute(
        "INSERT INTO regole_conflitto SELECT * FROM regole_vecchie "
        "WHERE tipo_regola != ?", (TIPO_REGOLA_COMPOSIZIONE_PARZIALE,)
    )
    db.execute("DROP TABLE regole_vecchie")
    db.commit()

    _estendi_tipi_regola(db)

    trovate = {
        (r['id'], r['nome'])
        for r in db.execute("SELECT id, nome FROM regole_conflitto")
    }
    assert trovate == {
        (i, n) for i, n in attese
        if n != 'Composizione incompleta'
    }

    # E ora il tipo nuovo entra.
    db.execute(
        "INSERT INTO regole_conflitto (nome, tipo_regola) VALUES ('prova', ?)",
        (TIPO_REGOLA_COMPOSIZIONE_PARZIALE,)
    )
    db.commit()


# ---------------------------------------------------------------------------
# Il riempimento automatico
# ---------------------------------------------------------------------------

def _chiedi(env, cal_id, sigla_utente, giorno, sigla_richiesta):
    """
    Registra la richiesta di un lavoratore per un giorno, come dopo il
    congelamento: nel desiderata originale e nella copia di lavoro.

    Returns:
        int: id del lavoratore che ha chiesto.
    """
    db = _open_sqlcipher(env['tenant_path'], env['tenant_key'])
    user_id = db.execute(
        "SELECT id FROM users WHERE sigla=?", (sigla_utente,)
    ).fetchone()['id']
    tipo_id = db.execute(
        "SELECT id FROM tipi_richiesta WHERE sigla=?", (sigla_richiesta,)
    ).fetchone()['id']

    for tabella in ('desiderata', 'working_desiderata'):
        db.execute(
            f"INSERT INTO {tabella} (calendario_id, user_id, giorno, tipo_richiesta_id) "
            "VALUES (?,?,?,?)",
            (cal_id, user_id, giorno, tipo_id)
        )
    db.execute("UPDATE calendari SET desiderata_congelati=1 WHERE id=?", (cal_id,))
    db.commit()

    return user_id


def _riempi(client, token, auth, cal_id, giorno_da=1, giorno_a=3):
    """Lancia il riempimento automatico e restituisce le assegnazioni fatte."""
    rv = client.post(f'/api/manager/calendari/{cal_id}/solver',
                     json={'giorno_da': giorno_da, 'giorno_a': giorno_a},
                     headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    rv = client.get(f'/api/manager/calendari/{cal_id}/assegnazioni',
                    headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    return [a for a in rv.get_json()['assegnazioni'] if a['user_id'] is not None]


def test_la_fascia_riservata_resta_vuota_senza_richieste(client, admin_token, auth):
    """
    Il turno della mattina, resa riservata, non si riempie da solo: nessuno
    l'ha chiesta, e il programma non ce la mette di sua iniziativa.
    """
    mattina = _flag_per_nome(client, admin_token, auth, 'mattina')
    client.put(f"/api/admin/flag-turno/{mattina['id']}",
               json={'solo_su_richiesta': True}, headers=auth(admin_token))

    rv = client.post('/api/admin/calendari', json={'mese': 7, 'anno': 2027},
                     headers=auth(admin_token))
    assert rv.status_code == 201, rv.get_json()

    assert _riempi(client, admin_token, auth, rv.get_json()['id']) == []


def test_la_fascia_riservata_va_a_chi_l_ha_chiesta(client, admin_token, auth, _test_env):
    """Con la richiesta la cella si riempie, e solo dove la richiesta c'e'."""
    mattina = _flag_per_nome(client, admin_token, auth, 'mattina')
    client.put(f"/api/admin/flag-turno/{mattina['id']}",
               json={'solo_su_richiesta': True}, headers=auth(admin_token))

    rv = client.post('/api/admin/calendari', json={'mese': 8, 'anno': 2027},
                     headers=auth(admin_token))
    assert rv.status_code == 201, rv.get_json()
    cal_id = rv.get_json()['id']

    giorno_chiesto = 2
    basic_id = _chiedi(_test_env, cal_id, 'BSC', giorno_chiesto, 'M')

    assegnate = _riempi(client, admin_token, auth, cal_id)

    assert [(a['giorno'], a['user_id']) for a in assegnate] \
        == [(giorno_chiesto, basic_id)]


# ---------------------------------------------------------------------------
# La composizione in griglia: parziale finche' non e' intera
# ---------------------------------------------------------------------------

def _aggiungi_turno_pomeriggio(env):
    """
    Aggiunge alla struttura di prova un secondo turno, nella fascia
    pomeriggio: senza due fasce non c'e' composizione da comporre.
    """
    db = _open_sqlcipher(env['tenant_path'], env['tenant_key'])
    sg_id = db.execute("SELECT id FROM sovragruppi LIMIT 1").fetchone()['id']
    flag_pom = db.execute(
        "SELECT id FROM flag_turno WHERE nome='pomeriggio'"
    ).fetchone()['id']

    cur = db.execute(
        "INSERT INTO gruppi (sovragruppo_id, sigla, nome, flag_id, ordine) "
        "VALUES (?, 'POM', 'Pomeriggio', ?, 2)",
        (sg_id, flag_pom)
    )
    db.execute(
        "INSERT INTO preset_turni (gruppo_id, sigla, nome, ordine) "
        "VALUES (?, 'AMB_P', 'Ambulatorio pomeriggio', 2)",
        (cur.lastrowid,)
    )
    db.commit()


def _turni_per_fascia(client, token, auth, cal_id):
    """Mappa nome della fascia → id del turno, dalla struttura del calendario."""
    rv = client.get(f'/api/manager/calendari/{cal_id}/struttura', headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    per_fascia = {}
    for sg in rv.get_json()['sovragruppi']:
        for gruppo in sg['gruppi']:
            for turno in gruppo['turni']:
                per_fascia[turno['flag_nome']] = turno['id']

    return per_fascia


def _conflitti_di(client, token, auth, cal_id, turno_id, giorno):
    """I tipi di regola attivati su una cella, come li vede la griglia."""
    rv = client.get(f'/api/manager/calendari/{cal_id}/assegnazioni',
                    headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    import json
    cella = next(a for a in rv.get_json()['assegnazioni']
                 if a['turno_id'] == turno_id and a['giorno'] == giorno)

    return {c.get('tipo_regola') for c in json.loads(cella['conflitti'] or '[]')}


@pytest.fixture
def calendario_composto(client, admin_token, auth, _test_env):
    """
    Una lunga fatta di mattina + pomeriggio, un calendario con entrambi i
    turni, e un lavoratore che ha chiesto la lunga il giorno 2.

    Returns:
        dict: cal_id, turni per fascia, user_id e giorno della richiesta.
    """
    _aggiungi_turno_pomeriggio(_test_env)

    lunga = _flag_per_nome(client, admin_token, auth, 'lunga')
    mattina = _flag_per_nome(client, admin_token, auth, 'mattina')
    pomeriggio = _flag_per_nome(client, admin_token, auth, 'pomeriggio')
    rv = client.put(f"/api/admin/flag-turno/{lunga['id']}",
                    json={'componenti': [mattina['id'], pomeriggio['id']]},
                    headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    rv = client.post('/api/admin/calendari', json={'mese': 10, 'anno': 2027},
                     headers=auth(admin_token))
    assert rv.status_code == 201, rv.get_json()
    cal_id = rv.get_json()['id']

    # Il 5 ottobre 2027 e' un martedi': un giorno feriale, dove i turni
    # sono aperti e il giorno dopo pure.
    giorno = 5
    basic_id = _chiedi(_test_env, cal_id, 'BSC', giorno, 'L')

    return {
        'cal_id': cal_id,
        'turni': _turni_per_fascia(client, admin_token, auth, cal_id),
        'user_id': basic_id,
        'giorno': giorno,
    }


def _assegna(client, token, auth, cal_id, turno_id, giorno, user_id):
    """Mette un lavoratore in una cella e restituisce i conflitti attivati."""
    rv = client.post(f'/api/manager/calendari/{cal_id}/assegnazioni',
                     json={'turno_id': turno_id, 'giorno': giorno, 'user_id': user_id},
                     headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    return {c.get('tipo_regola') for c in rv.get_json()['conflitti']}


def test_mezza_composizione_e_parziale_non_mismatch(client, admin_token, auth,
                                                    calendario_composto):
    """
    Chi ha chiesto la lunga e riceve la mattina non e' in errore: gli manca
    un pezzo, e lo dice la regola sua.
    """
    from app.services.validatori import (
        TIPO_REGOLA_COMPOSIZIONE_PARZIALE, TIPO_REGOLA_DESIDERATA_MISMATCH
    )
    c = calendario_composto

    tipi = _assegna(client, admin_token, auth, c['cal_id'],
                    c['turni']['mattina'], c['giorno'], c['user_id'])

    assert TIPO_REGOLA_COMPOSIZIONE_PARZIALE in tipi
    assert TIPO_REGOLA_DESIDERATA_MISMATCH not in tipi


def test_la_composizione_intera_soddisfa_la_richiesta(client, admin_token, auth,
                                                      calendario_composto):
    """
    Arrivato il pomeriggio, la richiesta di lunga e' soddisfatta: il parziale
    sparisce da entrambe le celle, senza che nessuno le ritocchi.
    """
    from app.services.validatori import TIPO_REGOLA_COMPOSIZIONE_PARZIALE
    c = calendario_composto

    _assegna(client, admin_token, auth, c['cal_id'],
             c['turni']['mattina'], c['giorno'], c['user_id'])
    tipi_pomeriggio = _assegna(client, admin_token, auth, c['cal_id'],
                               c['turni']['pomeriggio'], c['giorno'], c['user_id'])

    assert TIPO_REGOLA_COMPOSIZIONE_PARZIALE not in tipi_pomeriggio

    tipi_mattina = _conflitti_di(client, admin_token, auth, c['cal_id'],
                                 c['turni']['mattina'], c['giorno'])
    assert TIPO_REGOLA_COMPOSIZIONE_PARZIALE not in tipi_mattina


def test_una_fascia_estranea_resta_un_errore(client, admin_token, auth,
                                             calendario_composto):
    """
    La composizione non assolve tutto: un turno che non compone la richiesta
    resta un mismatch, come prima.
    """
    from app.services.validatori import (
        TIPO_REGOLA_COMPOSIZIONE_PARZIALE, TIPO_REGOLA_DESIDERATA_MISMATCH
    )
    c = calendario_composto
    giorno_senza_richiesta = c['giorno'] + 1

    # Il giorno dopo il lavoratore non ha chiesto niente: nessun conflitto.
    tipi = _assegna(client, admin_token, auth, c['cal_id'],
                    c['turni']['mattina'], giorno_senza_richiesta, c['user_id'])
    assert not tipi

    # Lo stesso turno, il giorno della richiesta di lunga, e' un pezzo.
    tipi = _assegna(client, admin_token, auth, c['cal_id'],
                    c['turni']['mattina'], c['giorno'], c['user_id'])
    assert tipi == {TIPO_REGOLA_COMPOSIZIONE_PARZIALE}
    assert TIPO_REGOLA_DESIDERATA_MISMATCH not in tipi
