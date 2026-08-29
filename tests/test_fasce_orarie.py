"""
tests/test_fasce_orarie.py — parametri orari delle fasce (nuova feature).

Copre la derivazione di durate, ore e peso dagli orari, lo sconfinamento
oltre la mezzanotte e l'appartenenza di una fascia a un concetto root.

Sono test puri: la logica sta in app/services/fasce_orarie.py e non tocca
il database.
"""

import importlib.util
import os

import pytest

# Il modulo si carica dal file invece che con "from app.services import ...":
# importare il pacchetto `app` in fase di collection eseguirebbe app/config.py,
# che legge le variabili d'ambiente nel corpo della classe Config, fissando la
# configurazione di produzione prima che la fixture di sessione in conftest.py
# punti l'ambiente ai database temporanei. fasce_orarie non ha dipendenze,
# quindi caricarlo isolato e' sicuro.
_PERCORSO_MODULO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'app', 'services', 'fasce_orarie.py'
)
_spec = importlib.util.spec_from_file_location('fasce_orarie', _PERCORSO_MODULO)
fo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fo)


# ---------------------------------------------------------------------------
# Fasce default: sono i valori concordati e fanno da tabella di riferimento.
# (nome, inizio, fine, pausa, netta attesa, totale attesa, peso atteso)
# ---------------------------------------------------------------------------

FASCE_ATTESE = [
    ('mattina',    '08:00', '14:20', 10,  380,  390, 1.0),
    ('pomeriggio', '14:00', '20:20', 10,  380,  390, 1.0),
    ('lunga',      '08:00', '20:40', 10,  760,  770, 2.0),
    ('notte',      '20:00', '08:40', 10,  760,  770, 2.0),
    ('guardia',    '00:00', '24:00',  0, 1440, 1440, 1440 / 380),
]

DURATA_TURNO_TIPO = 380  # 6h20


# ---------------------------------------------------------------------------
# Conversione orari
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('orario, minuti', [
    ('00:00', 0),
    ('08:00', 480),
    ('14:20', 860),
    ('24:00', 1440),
])
def test_parse_orario_valido(orario, minuti):
    """Un orario ben formato diventa i minuti dalla mezzanotte."""
    assert fo.parse_orario(orario) == minuti


@pytest.mark.parametrize('orario', [
    '8.00', '08:60', '25:00', '0800', '', 'otto', None, 830,
])
def test_parse_orario_non_valido(orario):
    """Gli orari malformati sollevano un'eccezione tipizzata, non passano."""
    with pytest.raises(fo.FormatoOrarioNonValido):
        fo.parse_orario(orario)


def test_formatta_orario_e_inverso_di_parse():
    """formatta_orario e parse_orario sono l'una l'inversa dell'altra."""
    for orario in ('00:00', '08:00', '14:20', '20:40', '24:00'):
        assert fo.formatta_orario(fo.parse_orario(orario)) == orario


def test_formatta_durata_oltre_le_24_ore():
    """Una durata si legge in ore e minuti anche sopra la giornata."""
    assert fo.formatta_durata(380) == '6h20'
    assert fo.formatta_durata(1440) == '24h00'
    assert fo.formatta_durata(None) == ''


# ---------------------------------------------------------------------------
# Durata netta
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('nome, inizio, fine, pausa, netta, totale, peso', FASCE_ATTESE)
def test_durata_netta_delle_fasce_default(nome, inizio, fine, pausa, netta, totale, peso):
    """Ogni fascia default produce la durata netta concordata."""
    assert fo.calcola_durata_netta(inizio, fine) == netta


def test_durata_netta_sconfina_oltre_mezzanotte():
    """La notte 20:00-08:40 dura 12h40, non un valore negativo."""
    assert fo.calcola_durata_netta('20:00', '08:40') == 760


def test_orari_coincidenti_valgono_ventiquattro_ore():
    """Nessun turno dura zero: orari uguali significano una giornata piena."""
    assert fo.calcola_durata_netta('08:00', '08:00') == fo.MINUTI_PER_GIORNO
    assert fo.calcola_durata_netta('00:00', '00:00') == fo.MINUTI_PER_GIORNO


# ---------------------------------------------------------------------------
# Durata totale, ore e peso
# ---------------------------------------------------------------------------

def test_la_pausa_si_somma_alla_durata_netta():
    """La pausa obbligatoria allunga il turno: 6h20 di lavoro fanno 6h30."""
    assert fo.calcola_durata_totale(380, 10) == 390


def test_durata_totale_senza_netta_resta_ignota():
    """Senza durata netta non si inventa una durata totale."""
    assert fo.calcola_durata_totale(None, 10) is None


def test_ore_turno_sono_la_totale_in_ore_decimali():
    """ore_turno e' la forma letta dal calcolo ore: ore decimali."""
    assert fo.calcola_ore_turno(390) == 6.5
    assert fo.calcola_ore_turno(1440) == 24.0
    assert fo.calcola_ore_turno(None) is None


def test_peso_usa_la_netta_e_non_la_totale():
    """
    Il peso deve venire dalla durata netta: e' la scelta che fa uscire 1 e 2
    tondi. Con le durate totali la notte peserebbe 770/390, cioe' 1.974.
    """
    assert fo.calcola_peso(380, DURATA_TURNO_TIPO) == 1.0
    assert fo.calcola_peso(760, DURATA_TURNO_TIPO) == 2.0
    assert fo.calcola_peso(770, 390) != 2.0


def test_peso_senza_turno_tipo_non_e_calcolabile():
    """Senza unita' di misura il peso resta ignoto invece di valere zero."""
    assert fo.calcola_peso(380, None) is None
    assert fo.calcola_peso(380, 0) is None
    assert fo.calcola_peso(None, DURATA_TURNO_TIPO) is None


# ---------------------------------------------------------------------------
# Ricalcolo completo dei parametri derivati
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('nome, inizio, fine, pausa, netta, totale, peso', FASCE_ATTESE)
def test_ricalcolo_parametri_fasce_default(nome, inizio, fine, pausa, netta, totale, peso):
    """Ogni fascia default deriva durate, ore e peso concordati."""
    derivati = fo.ricalcola_parametri(
        {'orario_inizio': inizio, 'orario_fine': fine, 'pausa_minuti': pausa},
        DURATA_TURNO_TIPO
    )

    assert derivati['durata_netta_minuti'] == netta
    assert derivati['durata_totale_minuti'] == totale
    assert derivati['ore_turno'] == totale / fo.MINUTI_PER_ORA
    assert derivati['peso_turno'] == pytest.approx(peso)


def test_ricalcolo_turno_tipo_senza_orari():
    """
    Il turno tipo non ha orari: la sua durata netta e' scritta direttamente
    e pesa 1 per definizione, essendo l'unita' di misura.
    """
    derivati = fo.ricalcola_parametri(
        {'durata_netta_minuti': DURATA_TURNO_TIPO, 'pausa_minuti': 10},
        DURATA_TURNO_TIPO
    )

    assert derivati['durata_netta_minuti'] == DURATA_TURNO_TIPO
    assert derivati['durata_totale_minuti'] == 390
    assert derivati['peso_turno'] == 1.0


def test_ricalcolo_flag_senza_durata_non_tocca_nulla():
    """
    Un flag assenza, o un concetto root senza orari, non ha parametri
    temporali: il ricalcolo lo lascia stare invece di azzerarne le ore.
    """
    assert fo.ricalcola_parametri({'pausa_minuti': 10}, DURATA_TURNO_TIPO) is None


def test_ricalcolo_propaga_orari_non_validi():
    """Un orario corrotto emerge come errore, non come durata sbagliata."""
    with pytest.raises(fo.FormatoOrarioNonValido):
        fo.ricalcola_parametri(
            {'orario_inizio': '08:00', 'orario_fine': '25:99', 'pausa_minuti': 10},
            DURATA_TURNO_TIPO
        )


# ---------------------------------------------------------------------------
# Gerarchia concetto → fascia
# ---------------------------------------------------------------------------

@pytest.fixture
def mappa_flag():
    """Gerarchia minima: i concetti root con una fascia ciascuno."""
    return fo.costruisci_mappa_flag([
        {'id': 1, 'nome': 'diurno',      'parent_id': None},
        {'id': 2, 'nome': 'notturno',    'parent_id': None},
        {'id': 3, 'nome': 'guardia_24h', 'parent_id': None},
        {'id': 4, 'nome': 'mattina',     'parent_id': 1},
        {'id': 5, 'nome': 'notte',       'parent_id': 2},
        {'id': 6, 'nome': 'seconda_notte', 'parent_id': 2},
        {'id': 7, 'nome': 'ferie',       'parent_id': None},
    ])


def test_fascia_appartiene_al_proprio_concetto(mappa_flag):
    """Una fascia discende dal concetto che la contiene."""
    assert fo.discende_da(5, fo.NOME_ROOT_NOTTURNO, mappa_flag)
    assert fo.discende_da(4, fo.NOME_ROOT_DIURNO, mappa_flag)


def test_fascia_non_appartiene_ad_altri_concetti(mappa_flag):
    """Una fascia diurna non e' una notte."""
    assert not fo.discende_da(4, fo.NOME_ROOT_NOTTURNO, mappa_flag)
    assert not fo.discende_da(7, fo.NOME_ROOT_NOTTURNO, mappa_flag)
    assert not fo.discende_da(None, fo.NOME_ROOT_NOTTURNO, mappa_flag)


def test_il_concetto_root_matcha_se_stesso(mappa_flag):
    """
    I calendari creati prima delle fasce agganciano i gruppi direttamente al
    concetto: i loro snapshot non si riscrivono, quindi 'notturno' deve
    continuare a essere riconosciuto come notte.
    """
    assert fo.discende_da(2, fo.NOME_ROOT_NOTTURNO, mappa_flag)
    assert fo.e_notturna('notturno', mappa_flag)


def test_riconoscimento_per_nome_indipendente_da_come_si_chiama(mappa_flag):
    """
    Il riconoscimento guarda la discendenza, non il nome: una seconda fascia
    notturna chiamata a piacere resta una notte.
    """
    assert fo.e_notturna('notte', mappa_flag)
    assert fo.e_notturna('seconda_notte', mappa_flag)
    assert not fo.e_notturna('mattina', mappa_flag)
    assert not fo.e_notturna(None, mappa_flag)
    assert not fo.e_notturna('inesistente', mappa_flag)


def test_gerarchia_ciclica_non_manda_in_loop():
    """Una gerarchia corrotta si interrompe invece di ciclare all'infinito."""
    ciclica = fo.costruisci_mappa_flag([
        {'id': 1, 'nome': 'a', 'parent_id': 2},
        {'id': 2, 'nome': 'b', 'parent_id': 1},
    ])

    assert fo.catena_antenati(1, ciclica) == {1, 2}
    assert not fo.discende_da(1, fo.NOME_ROOT_NOTTURNO, ciclica)
