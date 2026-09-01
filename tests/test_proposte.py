"""
tests/test_proposte.py — proposte di configurazione dal master ai tenant.

Il master non impone: propone il vocabolario e le regole, e l'amministratore
del tenant confronta con quello che ha e decide. Questi test riguardano il
confronto, che è la parte che rende la proposta accettabile invece che una
scommessa.
"""

import pytest


def _proposta(**parti):
    """Una proposta con solo le parti indicate, le altre vuote."""
    from app.services.proposte import PARTI_PROPONIBILI
    base = {chiave: [] for chiave, _, _ in PARTI_PROPONIBILI}
    return {**base, **parti}


def _parte(differenze, chiave):
    """Estrae dal confronto la parte richiesta."""
    return next(p for p in differenze if p['chiave'] == chiave)


# ---------------------------------------------------------------------------
# Cosa si propone
# ---------------------------------------------------------------------------

def test_la_proposta_tiene_solo_le_parti_trasferibili(app):
    """Struttura, persone, vincoli e conteggi restano del posto."""
    from app.services.proposte import estrai_proposta

    proposta = estrai_proposta({
        'flag_turno': [{'nome': 'mattina'}],
        'tipi_qualitativo': [], 'tipi_richiesta': [], 'regole_conflitto': [],
        'vincoli_solver': [{'tipo': 'flag'}],
        'conteggi_context': [{'id': 'notti'}],
    })

    assert set(proposta) == {'flag_turno', 'tipi_qualitativo',
                             'tipi_richiesta', 'regole_conflitto'}


# ---------------------------------------------------------------------------
# Il confronto
# ---------------------------------------------------------------------------

def test_una_fascia_che_il_tenant_non_ha_e_nuova(app):
    from app.services.proposte import confronta

    diff = confronta(
        _proposta(flag_turno=[{'nome': 'sera', 'orario_inizio': '16:00'}]),
        {'flag_turno': [{'nome': 'mattina', 'orario_inizio': '08:00'}]}
    )

    fasce = _parte(diff, 'flag_turno')
    assert [n['nome'] for n in fasce['nuove']] == ['sera']


def test_un_orario_diverso_e_una_modifica_con_prima_e_dopo(app):
    """L'utente deve leggere da cosa a cosa, non solo che qualcosa cambia."""
    from app.services.proposte import confronta

    diff = confronta(
        _proposta(flag_turno=[{'nome': 'mattina', 'orario_inizio': '07:30'}]),
        {'flag_turno': [{'nome': 'mattina', 'orario_inizio': '08:00'}]}
    )

    [modifica] = _parte(diff, 'flag_turno')['modificate']
    assert modifica['nome'] == 'mattina'
    assert modifica['cambi'] == [
        {'campo': 'orario_inizio', 'prima': '08:00', 'dopo': '07:30'}
    ]


def test_i_campi_derivati_non_si_segnalano(app):
    """Peso e durate discendono dagli orari: segnalarli sarebbe rumore."""
    from app.services.proposte import confronta

    diff = confronta(
        _proposta(flag_turno=[{'nome': 'mattina', 'peso_turno': 2.0, 'ore_turno': 12.0}]),
        {'flag_turno': [{'nome': 'mattina', 'peso_turno': 1.0, 'ore_turno': 6.5}]}
    )

    assert _parte(diff, 'flag_turno')['modificate'] == []


def test_cio_che_il_tenant_ha_in_piu_resta_e_si_segnala(app):
    """Accettare non cancella: l'utente deve sapere che quella roba resta."""
    from app.services.proposte import confronta

    diff = confronta(
        _proposta(flag_turno=[{'nome': 'mattina'}]),
        {'flag_turno': [{'nome': 'mattina'}, {'nome': 'guardia_speciale'}]}
    )

    assert _parte(diff, 'flag_turno')['solo_qui'] == ['guardia_speciale']


def test_il_confronto_va_per_nome_non_per_id(app):
    """Due tenant nati da database diversi hanno id diversi per la stessa fascia."""
    from app.services.proposte import confronta

    diff = confronta(
        _proposta(flag_turno=[{'id': 99, 'nome': 'mattina', 'orario_inizio': '08:00'}]),
        {'flag_turno': [{'id': 3, 'nome': 'mattina', 'orario_inizio': '08:00'}]}
    )

    fasce = _parte(diff, 'flag_turno')
    assert fasce['nuove'] == [] and fasce['modificate'] == []


def test_una_proposta_identica_non_ha_effetto(app):
    """Vale la pena dirlo prima, invece di far accettare il nulla."""
    from app.services.proposte import confronta, e_senza_effetto

    attuale = {
        'flag_turno': [{'nome': 'mattina', 'orario_inizio': '08:00'}],
        'tipi_qualitativo': [{'nome': 'TC'}],
        'tipi_richiesta': [], 'regole_conflitto': [],
    }

    assert e_senza_effetto(confronta(_proposta(**attuale), attuale))


def test_una_proposta_che_aggiunge_non_e_senza_effetto(app):
    from app.services.proposte import confronta, e_senza_effetto

    diff = confronta(
        _proposta(tipi_qualitativo=[{'nome': 'RM'}]),
        {'tipi_qualitativo': [{'nome': 'TC'}]}
    )

    assert not e_senza_effetto(diff)


def test_tutte_le_quattro_parti_compaiono_nel_confronto(app):
    """Anche quelle senza differenze: l'utente vede che sono state guardate."""
    from app.services.proposte import confronta

    diff = confronta(_proposta(), {})

    assert [p['chiave'] for p in diff] == [
        'flag_turno', 'tipi_qualitativo', 'tipi_richiesta', 'regole_conflitto'
    ]
    assert [p['etichetta'] for p in diff][0] == 'Fasce orarie e assenze'


# ---------------------------------------------------------------------------
# Accettare una proposta
# ---------------------------------------------------------------------------

@pytest.fixture
def tenant(app):
    """Contesto di richiesta sul tenant di prova, con la sua connessione."""
    with app.test_request_context('/'):
        from flask import g
        from app.db import get_db
        g.tenant_slug = 'testorg'
        yield get_db()


def _flag(db, nome):
    return db.execute(
        "SELECT id, parent_id, orario_inizio, orario_fine FROM flag_turno WHERE nome = ?",
        (nome,)
    ).fetchone()


def test_una_fascia_nuova_viene_creata(tenant):
    from app.services.proposte import applica

    assert _flag(tenant, 'sera') is None

    applica(tenant, _proposta(flag_turno=[
        {'id': 900, 'nome': 'sera', 'orario_inizio': '16:00', 'orario_fine': '22:20',
         'pausa_minuti': 10, 'mostra_in_struttura': 1, 'tipo': 'lavorativo',
         'parent_id': None},
    ]))

    creata = _flag(tenant, 'sera')
    assert creata is not None
    assert (creata['orario_inizio'], creata['orario_fine']) == ('16:00', '22:20')


def test_gli_id_della_proposta_non_arrivano_nel_tenant(tenant):
    """Un id 900 proposto non deve diventare l'id locale."""
    from app.services.proposte import applica

    applica(tenant, _proposta(flag_turno=[
        {'id': 900, 'nome': 'notturna_extra', 'pausa_minuti': 10,
         'mostra_in_struttura': 1, 'tipo': 'lavorativo', 'parent_id': None},
    ]))

    assert _flag(tenant, 'notturna_extra')['id'] != 900


def test_la_discendenza_si_traduce_per_nome(tenant):
    """
    Una fascia proposta come figlia di 'notturno' deve agganciarsi al
    'notturno' del tenant, che ha un id tutto suo.
    """
    from app.services.proposte import applica

    id_notturno_locale = _flag(tenant, 'notturno')['id']

    applica(tenant, _proposta(flag_turno=[
        # Nella proposta 'notturno' ha id 77; qui ne ha un altro.
        {'id': 77, 'nome': 'notturno', 'parent_id': None,
         'pausa_minuti': 10, 'mostra_in_struttura': 0, 'tipo': 'lavorativo'},
        {'id': 78, 'nome': 'notte_lunga', 'parent_id': 77,
         'orario_inizio': '20:00', 'orario_fine': '10:00',
         'pausa_minuti': 10, 'mostra_in_struttura': 1, 'tipo': 'lavorativo'},
    ]))

    assert _flag(tenant, 'notte_lunga')['parent_id'] == id_notturno_locale


def test_cio_che_il_tenant_ha_in_piu_sopravvive(tenant):
    """Accettare allinea, non azzera."""
    from app.services.proposte import applica

    prima = {r[0] for r in tenant.execute("SELECT nome FROM flag_turno")}

    applica(tenant, _proposta(flag_turno=[
        {'id': 1, 'nome': 'mattina', 'orario_inizio': '07:30', 'orario_fine': '13:50',
         'pausa_minuti': 10, 'mostra_in_struttura': 1, 'tipo': 'lavorativo',
         'parent_id': None},
    ]))

    dopo = {r[0] for r in tenant.execute("SELECT nome FROM flag_turno")}
    assert prima <= dopo
    assert _flag(tenant, 'mattina')['orario_inizio'] == '07:30'


# ---------------------------------------------------------------------------
# Il giro completo: il master propone, il tenant decide
# ---------------------------------------------------------------------------

def _configurazione_del_tenant(client, master_token, auth, tenant_id=1):
    """Legge dal master il vocabolario di un tenant."""
    rv = client.get(f'/api/master/tenants/{tenant_id}/configurazione',
                    headers=auth(master_token))
    assert rv.status_code == 200, rv.get_json()
    return rv.get_json()['configurazione']


def test_senza_proposte_il_tenant_non_vede_nulla(client, admin_token, auth):
    rv = client.get('/api/admin/proposta', headers=auth(admin_token))
    assert rv.status_code == 200
    assert rv.get_json()['proposta'] is None


def test_il_master_propone_e_il_tenant_vede_il_confronto(
        client, master_token, admin_token, auth):
    """Il percorso che conta: proporre non applica, mostra."""
    parti = _configurazione_del_tenant(client, master_token, auth)
    parti['flag_turno'].append({
        'id': 9001, 'nome': 'sera', 'parent_id': None, 'descrizione': 'Fascia serale',
        'orario_inizio': '16:00', 'orario_fine': '22:20', 'pausa_minuti': 10,
        'mostra_in_struttura': 1, 'tipo': 'lavorativo',
        'ore_primo_giorno': None, 'ore_ultimo_giorno': None,
    })

    rv = client.post('/api/master/tenants/1/proposta',
                     json={'nome': 'Radiologia tipo', 'configurazione': parti,
                           'note': 'Allineamento fasce'},
                     headers=auth(master_token))
    assert rv.status_code == 201, rv.get_json()

    rv = client.get('/api/admin/proposta', headers=auth(admin_token))
    proposta = rv.get_json()['proposta']

    assert proposta['nome'] == 'Radiologia tipo'
    assert proposta['note'] == 'Allineamento fasce'
    assert not proposta['senza_effetto']

    fasce = next(p for p in proposta['differenze'] if p['chiave'] == 'flag_turno')
    assert [n['nome'] for n in fasce['nuove']] == ['sera']

    # Proporre non applica: la fascia non c'e' ancora.
    rv = client.get('/api/admin/flag-turno', headers=auth(admin_token))
    assert not [f for f in rv.get_json()['flags'] if f['nome'] == 'sera']


def test_accettare_applica_e_chiude_la_proposta(
        client, master_token, admin_token, auth):
    parti = _configurazione_del_tenant(client, master_token, auth)
    parti['flag_turno'].append({
        'id': 9002, 'nome': 'sera_lunga', 'parent_id': None, 'descrizione': '',
        'orario_inizio': '14:00', 'orario_fine': '02:00', 'pausa_minuti': 10,
        'mostra_in_struttura': 1, 'tipo': 'lavorativo',
        'ore_primo_giorno': None, 'ore_ultimo_giorno': None,
    })
    client.post('/api/master/tenants/1/proposta',
                json={'nome': 'Con sera lunga', 'configurazione': parti},
                headers=auth(master_token))

    pid = client.get('/api/admin/proposta', headers=auth(admin_token)).get_json()['proposta']['id']
    rv = client.put(f'/api/admin/proposta/{pid}/accetta', headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    flags = client.get('/api/admin/flag-turno', headers=auth(admin_token)).get_json()['flags']
    creata = next(f for f in flags if f['nome'] == 'sera_lunga')
    # Il ricalcolo e' scattato: le durate discendono dagli orari arrivati.
    assert creata['durata_netta_minuti'] == 720

    assert client.get('/api/admin/proposta', headers=auth(admin_token)).get_json()['proposta'] is None


def test_rifiutare_lascia_tutto_com_era(client, master_token, admin_token, auth):
    parti = _configurazione_del_tenant(client, master_token, auth)
    parti['flag_turno'].append({
        'id': 9003, 'nome': 'mai_creata', 'parent_id': None, 'descrizione': '',
        'orario_inizio': '10:00', 'orario_fine': '16:00', 'pausa_minuti': 10,
        'mostra_in_struttura': 1, 'tipo': 'lavorativo',
        'ore_primo_giorno': None, 'ore_ultimo_giorno': None,
    })
    client.post('/api/master/tenants/1/proposta',
                json={'nome': 'Da rifiutare', 'configurazione': parti},
                headers=auth(master_token))

    pid = client.get('/api/admin/proposta', headers=auth(admin_token)).get_json()['proposta']['id']
    rv = client.put(f'/api/admin/proposta/{pid}/rifiuta', headers=auth(admin_token))
    assert rv.status_code == 200, rv.get_json()

    flags = client.get('/api/admin/flag-turno', headers=auth(admin_token)).get_json()['flags']
    assert not [f for f in flags if f['nome'] == 'mai_creata']
    assert client.get('/api/admin/proposta', headers=auth(admin_token)).get_json()['proposta'] is None


def test_una_seconda_proposta_supera_la_prima(client, master_token, admin_token, auth):
    """Due in attesa metterebbero l'admin a scegliere fra cose non richieste."""
    parti = _configurazione_del_tenant(client, master_token, auth)

    client.post('/api/master/tenants/1/proposta',
                json={'nome': 'Prima', 'configurazione': parti}, headers=auth(master_token))
    client.post('/api/master/tenants/1/proposta',
                json={'nome': 'Seconda', 'configurazione': parti}, headers=auth(master_token))

    proposta = client.get('/api/admin/proposta', headers=auth(admin_token)).get_json()['proposta']
    assert proposta['nome'] == 'Seconda'


def test_una_proposta_identica_lo_dichiara(client, master_token, admin_token, auth):
    """Meglio dirlo prima che far accettare il nulla."""
    parti = _configurazione_del_tenant(client, master_token, auth)

    client.post('/api/master/tenants/1/proposta',
                json={'nome': 'Uguale', 'configurazione': parti}, headers=auth(master_token))

    proposta = client.get('/api/admin/proposta', headers=auth(admin_token)).get_json()['proposta']
    assert proposta['senza_effetto'] is True
