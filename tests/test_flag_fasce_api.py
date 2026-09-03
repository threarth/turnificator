"""
tests/test_flag_fasce_api.py — API dei flag turno dopo la rimozione di "composto".

Copre i tre punti della modifica:
- il concetto di flag composto e' sparito dallo schema, in modo idempotente;
- gli orari sono scrivibili dall'API e i campi derivati si riallineano subito;
- una fascia oraria non puo' comparire due volte nella stessa struttura.

Questi test passano dal database: usano le fixture di conftest.py, che
puntano l'ambiente a database temporanei prima di importare `app`.
"""

import pytest

from tests.conftest import _open_sqlcipher


# Fascia di riferimento del seed: 08:00-14:20 con 10 minuti di pausa.
FASCIA_MATTINA = 'mattina'


def _flag_per_nome(client, token, auth, nome):
    """Restituisce dalla lista API il flag con quel nome, o None."""
    rv = client.get('/api/admin/flag-turno', headers=auth(token))
    assert rv.status_code == 200, rv.get_json()

    return next(
        (f for f in rv.get_json()['flags'] if f['nome'] == nome),
        None
    )


# ---------------------------------------------------------------------------
# Rimozione del concetto "composto"
# ---------------------------------------------------------------------------

def test_schema_senza_la_colonna_entita(app, _test_env):
    """
    `entita` distingueva i flag semplici dai composti, e diceva che la lunga
    vale due turni: oggi lo dicono gli orari, dove non puo' divergere.
    """
    db = _open_sqlcipher(_test_env['tenant_path'], _test_env['tenant_key'])

    colonne = [r[1] for r in db.execute('PRAGMA table_info(flag_turno)')]
    assert 'entita' not in colonne


def test_la_tabella_composizione_esiste_con_un_altro_scopo(app, _test_env):
    """
    `flag_composizione` e' tornata, ma non dice piu' quanto vale una fascia:
    dice quali fasce insieme soddisfano la richiesta di un'altra. La
    migrazione che tolse `entita` non deve piu' cancellarla.
    """
    db = _open_sqlcipher(_test_env['tenant_path'], _test_env['tenant_key'])

    tabelle = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='flag_composizione'"
    ).fetchall()
    assert tabelle != []


def test_rimozione_colonna_entita_idempotente(app, _test_env):
    """Rieseguire la migrazione su uno schema gia' pulito non solleva nulla."""
    from app import _rimuovi_colonna_entita

    db = _open_sqlcipher(_test_env['tenant_path'], _test_env['tenant_key'])
    _rimuovi_colonna_entita(db)
    _rimuovi_colonna_entita(db)

    colonne = [r[1] for r in db.execute('PRAGMA table_info(flag_turno)')]
    assert 'entita' not in colonne
    assert 'nome' in colonne


def test_lista_flag_non_espone_entita(client, admin_token, auth):
    """
    `entita` non c'e' piu'; `componenti` si', ma dice un'altra cosa: da quali
    fasce e' soddisfatta la richiesta di questa.
    """
    mattina = _flag_per_nome(client, admin_token, auth, FASCIA_MATTINA)

    assert mattina is not None
    assert 'entita' not in mattina
    assert mattina['componenti'] == []


# ---------------------------------------------------------------------------
# Orari scrivibili, derivati ricalcolati
# ---------------------------------------------------------------------------

def test_lista_flag_espone_orari_e_derivati(client, admin_token, auth):
    """Le fasce arrivano al client con orari, pausa e parametri derivati."""
    mattina = _flag_per_nome(client, admin_token, auth, FASCIA_MATTINA)

    assert mattina['orario_inizio'] == '08:00'
    assert mattina['orario_fine'] == '14:20'
    assert mattina['pausa_minuti'] == 10
    assert mattina['durata_netta_minuti'] == 380
    assert mattina['durata_totale_minuti'] == 390
    assert mattina['peso_turno'] == pytest.approx(1.0)


def test_modifica_orari_ricalcola_i_derivati(client, admin_token, auth):
    """Cambiare gli orari riallinea durate, ore e peso senza riavviare."""
    mattina = _flag_per_nome(client, admin_token, auth, FASCIA_MATTINA)

    rv = client.put(
        f"/api/admin/flag-turno/{mattina['id']}",
        json={'orario_inizio': '08:00', 'orario_fine': '15:00', 'pausa_minuti': 20},
        headers=auth(admin_token)
    )
    assert rv.status_code == 200, rv.get_json()

    aggiornata = _flag_per_nome(client, admin_token, auth, FASCIA_MATTINA)
    assert aggiornata['durata_netta_minuti'] == 420
    assert aggiornata['durata_totale_minuti'] == 440
    assert aggiornata['ore_turno'] == pytest.approx(440 / 60)
    assert aggiornata['peso_turno'] == pytest.approx(420 / 380)


def test_orario_senza_minuti_normalizzato(client, admin_token, auth):
    """'8:5' e' un orario valido e viene riscritto nella forma canonica."""
    mattina = _flag_per_nome(client, admin_token, auth, FASCIA_MATTINA)

    rv = client.put(
        f"/api/admin/flag-turno/{mattina['id']}",
        json={'orario_inizio': '8:5', 'orario_fine': '14:20'},
        headers=auth(admin_token)
    )
    assert rv.status_code == 200, rv.get_json()

    assert _flag_per_nome(client, admin_token, auth, FASCIA_MATTINA)['orario_inizio'] == '08:05'


@pytest.mark.parametrize('orari', [
    {'orario_inizio': 'otto', 'orario_fine': '14:20'},
    {'orario_inizio': '08:00', 'orario_fine': '25:00'},
    {'orario_inizio': '08:00', 'orario_fine': '14:99'},
])
def test_orario_malformato_rifiutato(client, admin_token, auth, orari):
    """Un orario non interpretabile e' un errore, non un campo svuotato."""
    mattina = _flag_per_nome(client, admin_token, auth, FASCIA_MATTINA)

    rv = client.put(
        f"/api/admin/flag-turno/{mattina['id']}",
        json=orari, headers=auth(admin_token)
    )
    assert rv.status_code == 400
    assert 'Orario non valido' in rv.get_json()['errore']


def test_un_solo_orario_rifiutato(client, admin_token, auth):
    """Una fascia con solo l'inizio non ha durata: va rifiutata."""
    rv = client.post(
        '/api/admin/flag-turno',
        json={'nome': 'meta_fascia', 'orario_inizio': '08:00'},
        headers=auth(admin_token)
    )
    assert rv.status_code == 400
    assert 'entrambi' in rv.get_json()['errore']


def test_crea_fascia_deriva_i_parametri(client, admin_token, auth):
    """Una fascia nuova nasce gia' con durate, ore e peso calcolati."""
    rv = client.post(
        '/api/admin/flag-turno',
        json={
            'nome': 'sera', 'descrizione': 'Fascia serale',
            'orario_inizio': '16:00', 'orario_fine': '22:20', 'pausa_minuti': 10,
        },
        headers=auth(admin_token)
    )
    assert rv.status_code == 201, rv.get_json()

    sera = _flag_per_nome(client, admin_token, auth, 'sera')
    assert sera['durata_netta_minuti'] == 380
    assert sera['durata_totale_minuti'] == 390
    assert sera['peso_turno'] == pytest.approx(1.0)


def test_pausa_non_dichiarata_prende_il_default(client, admin_token, auth):
    """Una fascia creata senza pausa prende quella di contratto, non zero."""
    rv = client.post(
        '/api/admin/flag-turno',
        json={'nome': 'notturna_breve', 'orario_inizio': '22:00', 'orario_fine': '04:20'},
        headers=auth(admin_token)
    )
    assert rv.status_code == 201, rv.get_json()

    creata = _flag_per_nome(client, admin_token, auth, 'notturna_breve')
    assert creata['pausa_minuti'] == 10
    assert creata['durata_totale_minuti'] == 390


# ---------------------------------------------------------------------------
# Il turno tipo: si modifica, non si elimina
# ---------------------------------------------------------------------------

# Unita' di misura del peso, dichiarata nel seed a 6h20.
NOME_TURNO_TIPO = 'turno_tipo'


def test_turno_tipo_non_si_elimina(client, admin_token, auth):
    """Senza il metro, i pesi di tutte le fasce perderebbero il riferimento."""
    turno_tipo = _flag_per_nome(client, admin_token, auth, NOME_TURNO_TIPO)

    rv = client.delete(f"/api/admin/flag-turno/{turno_tipo['id']}", headers=auth(admin_token))
    assert rv.status_code == 409
    assert 'non si elimina' in rv.get_json()['errore']

    assert _flag_per_nome(client, admin_token, auth, NOME_TURNO_TIPO) is not None


def test_turno_tipo_non_si_rinomina(client, admin_token, auth):
    """Il ricalcolo lo cerca per nome: rinominarlo scollegherebbe i pesi."""
    turno_tipo = _flag_per_nome(client, admin_token, auth, NOME_TURNO_TIPO)

    rv = client.put(f"/api/admin/flag-turno/{turno_tipo['id']}",
                    json={'nome': 'metro'}, headers=auth(admin_token))
    assert rv.status_code == 409
    assert 'non si rinomina' in rv.get_json()['errore']

    assert _flag_per_nome(client, admin_token, auth, NOME_TURNO_TIPO) is not None
    assert _flag_per_nome(client, admin_token, auth, 'metro') is None


def test_turno_tipo_accetta_le_altre_modifiche(client, admin_token, auth):
    """Il blocco riguarda il nome, non l'intera riga."""
    turno_tipo = _flag_per_nome(client, admin_token, auth, NOME_TURNO_TIPO)

    rv = client.put(f"/api/admin/flag-turno/{turno_tipo['id']}",
                    json={'nome': NOME_TURNO_TIPO, 'descrizione': 'Metro dei pesi'},
                    headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    assert _flag_per_nome(client, admin_token, auth, NOME_TURNO_TIPO)['descrizione'] == 'Metro dei pesi'


def test_durata_del_turno_tipo_riscala_tutti_i_pesi(client, admin_token, auth):
    """Cambiare il metro cambia il peso di ogni fascia, senza toccarle."""
    turno_tipo = _flag_per_nome(client, admin_token, auth, NOME_TURNO_TIPO)
    assert _flag_per_nome(client, admin_token, auth, FASCIA_MATTINA)['peso_turno'] == 1.0

    rv = client.put(f"/api/admin/flag-turno/{turno_tipo['id']}",
                    json={'durata_netta_minuti': 420}, headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    assert _flag_per_nome(client, admin_token, auth, NOME_TURNO_TIPO)['durata_netta_minuti'] == 420

    # La mattina non e' cambiata: sono 380 minuti su un metro piu' lungo.
    mattina = _flag_per_nome(client, admin_token, auth, FASCIA_MATTINA)
    assert mattina['durata_netta_minuti'] == 380
    assert mattina['peso_turno'] == pytest.approx(380 / 420)


# ---------------------------------------------------------------------------
# Le assenze non entrano nella struttura turni
# ---------------------------------------------------------------------------

def test_assenza_creata_non_e_in_struttura(client, admin_token, auth):
    """Un'assenza non e' una fascia: la visibilita' richiesta viene ignorata."""
    rv = client.post(
        '/api/admin/flag-turno',
        json={'nome': 'aspettativa', 'tipo': 'assenza', 'mostra_in_struttura': True},
        headers=auth(admin_token)
    )
    assert rv.status_code == 201, rv.get_json()

    assert _flag_per_nome(client, admin_token, auth, 'aspettativa')['mostra_in_struttura'] == 0


def test_riclassificare_come_assenza_toglie_dalla_struttura(client, admin_token, auth):
    """Una fascia che diventa assenza esce dalla struttura turni."""
    mattina = _flag_per_nome(client, admin_token, auth, FASCIA_MATTINA)
    assert mattina['mostra_in_struttura'] == 1

    rv = client.put(
        f"/api/admin/flag-turno/{mattina['id']}",
        json={'tipo': 'assenza'}, headers=auth(admin_token)
    )
    assert rv.status_code == 200, rv.get_json()

    assert _flag_per_nome(client, admin_token, auth, FASCIA_MATTINA)['mostra_in_struttura'] == 0


def test_assenze_default_fuori_dalla_struttura(client, admin_token, auth):
    """Nessuna delle assenze di serie e' agganciabile a un gruppo."""
    rv = client.get('/api/admin/flag-turno', headers=auth(admin_token))
    assenze = [f for f in rv.get_json()['flags'] if f['tipo'] == 'assenza']

    assert assenze
    assert all(f['mostra_in_struttura'] == 0 for f in assenze)


# ---------------------------------------------------------------------------
# Una fascia oraria per struttura
# ---------------------------------------------------------------------------

def _struttura_del_preset_default(client, token, auth):
    """Restituisce (preset_id, struttura) del preset predefinito del tenant."""
    rv = client.get('/api/admin/struttura-presets', headers=auth(token))
    assert rv.status_code == 200, rv.get_json()
    preset_id = rv.get_json()['presets'][0]['id']

    rv = client.get(
        f'/api/admin/struttura-presets/{preset_id}/struttura',
        headers=auth(token)
    )
    assert rv.status_code == 200, rv.get_json()

    return preset_id, rv.get_json()['struttura']


def test_fascia_duplicata_nella_struttura_rifiutata(client, admin_token, auth):
    """Due gruppi sulla stessa fascia nella stessa struttura → 409, non 500."""
    preset_id, struttura = _struttura_del_preset_default(client, admin_token, auth)
    sovragruppo = struttura[0]
    fascia_gia_usata = sovragruppo['gruppi'][0]['flag_id']

    sovragruppo['gruppi'].append({
        'sigla': 'DUP', 'nome': 'Doppione',
        'flag_id': fascia_gia_usata, 'turni': [],
    })

    rv = client.put(
        f'/api/admin/struttura-presets/{preset_id}/struttura',
        json={'struttura': struttura}, headers=auth(admin_token)
    )
    assert rv.status_code == 409, rv.get_json()
    assert 'una volta sola' in rv.get_json()['errore']


def test_fasce_diverse_nella_stessa_struttura_ammesse(client, admin_token, auth):
    """Il vincolo colpisce la fascia ripetuta, non il secondo gruppo in se'."""
    preset_id, struttura = _struttura_del_preset_default(client, admin_token, auth)
    sovragruppo = struttura[0]
    altra_fascia = _flag_per_nome(client, admin_token, auth, 'pomeriggio')

    sovragruppo['gruppi'].append({
        'sigla': 'POM', 'nome': 'Pomeriggio',
        'flag_id': altra_fascia['id'], 'turni': [],
    })

    rv = client.put(
        f'/api/admin/struttura-presets/{preset_id}/struttura',
        json={'struttura': struttura}, headers=auth(admin_token)
    )
    assert rv.status_code == 200, rv.get_json()


# ---------------------------------------------------------------------------
# I tipi richiesta di serie
# ---------------------------------------------------------------------------

def test_i_tipi_richiesta_di_serie_ci_sono(client, admin_token, auth):
    """Un'installazione nuova trova gia' le voci che usano quasi tutti."""
    rv = client.get('/api/admin/tipi-richiesta', headers=auth(admin_token))
    assert rv.status_code == 200

    sigle = {t['sigla'] for t in rv.get_json()['tipi']}
    assert {'M', 'P', 'N', 'CO', 'ROMC'} <= sigle


def test_romc_non_conta_le_ore(client, admin_token, auth):
    """Il recupero del mese corrente e' gia' nelle ore lavorate."""
    rv = client.get('/api/admin/tipi-richiesta', headers=auth(admin_token))
    romc = next(t for t in rv.get_json()['tipi'] if t['sigla'] == 'ROMC')

    assert romc['counting_flag'] == 0


def test_il_ripristino_non_tocca_quelli_presenti(client, admin_token, auth):
    """Un tipo rinominato deve restare com'e', non tornare al nome di serie."""
    rv = client.get('/api/admin/tipi-richiesta', headers=auth(admin_token))
    ferie = next(t for t in rv.get_json()['tipi'] if t['sigla'] == 'CO')

    client.put(f"/api/admin/tipi-richiesta/{ferie['id']}",
               json={**ferie, 'descrizione': 'Ferie contrattuali'},
               headers=auth(admin_token))

    rv = client.post('/api/admin/tipi-richiesta/ripristina-default',
                     headers=auth(admin_token))
    assert rv.status_code == 200
    assert rv.get_json()['inseriti'] == 0

    rv = client.get('/api/admin/tipi-richiesta', headers=auth(admin_token))
    assert next(t for t in rv.get_json()['tipi']
                if t['sigla'] == 'CO')['descrizione'] == 'Ferie contrattuali'
