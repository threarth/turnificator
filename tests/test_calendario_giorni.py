"""
tests/test_calendario_giorni.py — quali giorni del mese sono lavorativi.

Da qui discendono i turni dovuti, e quindi il tetto mensile di ogni
lavoratore. Prima la regola era inchiodata — tutto tranne domenica e
festivita' — e un reparto che chiude il sabato non poteva dirlo.

Convenzione: 0 = lunedì, 6 = domenica.
"""

import datetime

import pytest


LUN, MAR, MER, GIO, VEN, SAB, DOM = range(7)

# Settembre 2026: comincia di martedì, 30 giorni, 4 domeniche.
MESE, ANNO = 9, 2026


@pytest.fixture
def giorni(app):
    from app.services import calendario_giorni
    return calendario_giorni


# ---------------------------------------------------------------------------
# Lettura della configurazione
# ---------------------------------------------------------------------------

def test_senza_impostazione_si_lavora_sei_giorni(giorni):
    """E' il comportamento che il sistema aveva prima: tutto tranne domenica."""
    assert giorni.leggi_giorni_lavorativi({}) == {LUN, MAR, MER, GIO, VEN, SAB}
    assert giorni.leggi_giorni_lavorativi(None) == {LUN, MAR, MER, GIO, VEN, SAB}


def test_un_reparto_puo_chiudere_il_sabato(giorni):
    assert giorni.leggi_giorni_lavorativi(
        {'giorni_lavorativi_settimana': '0,1,2,3,4'}
    ) == {LUN, MAR, MER, GIO, VEN}


def test_un_valore_illeggibile_ricade_sul_default(giorni):
    """Meglio il comportamento noto che un mese senza giorni lavorativi."""
    assert giorni.leggi_giorni_lavorativi({'giorni_lavorativi_settimana': 'boh'}) \
        == {LUN, MAR, MER, GIO, VEN, SAB}
    assert giorni.leggi_giorni_lavorativi({'giorni_lavorativi_settimana': ''}) \
        == {LUN, MAR, MER, GIO, VEN, SAB}


def test_i_numeri_fuori_scala_si_scartano(giorni):
    assert giorni.leggi_giorni_lavorativi(
        {'giorni_lavorativi_settimana': '0,1,9,-3,5'}
    ) == {LUN, MAR, SAB}


def test_i_festivi_non_contano_salvo_dirlo(giorni):
    assert giorni.festivi_sono_lavorativi({}) is False
    assert giorni.festivi_sono_lavorativi({'festivi_lavorativi': '1'}) is True
    assert giorni.festivi_sono_lavorativi({'festivi_lavorativi': '0'}) is False


# ---------------------------------------------------------------------------
# Classificazione del singolo giorno
# ---------------------------------------------------------------------------

def test_la_domenica_e_festiva_e_non_lavorativa(giorni):
    domenica = datetime.date(2026, 9, 6)
    assert domenica.weekday() == DOM

    tipo, lavorativo = giorni.classifica_giorno(
        domenica, {}, {LUN, MAR, MER, GIO, VEN, SAB}, False)
    assert (tipo, lavorativo) == ('festivo', False)


def test_il_sabato_e_lavorativo_solo_se_lo_si_dice(giorni):
    sabato = datetime.date(2026, 9, 5)
    assert sabato.weekday() == SAB

    _, con_sabato = giorni.classifica_giorno(sabato, {}, {SAB}, False)
    _, senza_sabato = giorni.classifica_giorno(sabato, {}, {LUN}, False)
    assert con_sabato is True
    assert senza_sabato is False


def test_una_festivita_infrasettimanale_non_e_lavorativa(giorni):
    natale = datetime.date(2026, 12, 25)
    festivita = {'festivi': ['2026-12-25'], 'superfestivi': []}

    tipo, lavorativo = giorni.classifica_giorno(
        natale, festivita, set(range(7)), False)
    assert (tipo, lavorativo) == ('festivo', False)


def test_chi_conta_i_festivi_li_ha_lavorativi(giorni):
    """Un reparto sempre aperto: il festivo resta festivo ma conta."""
    natale = datetime.date(2026, 12, 25)
    festivita = {'festivi': ['2026-12-25'], 'superfestivi': []}

    tipo, lavorativo = giorni.classifica_giorno(
        natale, festivita, set(range(7)), True)
    assert (tipo, lavorativo) == ('festivo', True)


def test_un_superfestivo_resta_riconoscibile(giorni):
    data = datetime.date(2026, 12, 25)
    tipo, _ = giorni.classifica_giorno(
        data, {'superfestivi': ['2026-12-25']}, set(range(7)), False)
    assert tipo == 'superfestivo'


# ---------------------------------------------------------------------------
# I turni dovuti del mese
# ---------------------------------------------------------------------------

def test_settembre_2026_con_sei_giorni_su_sette(giorni):
    """30 giorni meno 4 domeniche: 26, il conto dell'esempio."""
    dovuti = giorni.conta_turni_dovuti(
        MESE, ANNO, {}, {LUN, MAR, MER, GIO, VEN, SAB}, False)
    assert dovuti == 26


def test_lo_stesso_mese_chiudendo_il_sabato(giorni):
    """Quattro sabati in meno: 22."""
    dovuti = giorni.conta_turni_dovuti(
        MESE, ANNO, {}, {LUN, MAR, MER, GIO, VEN}, False)
    assert dovuti == 22


def test_una_festivita_toglie_un_turno_dovuto(giorni):
    festivita = {'festivi': ['2026-09-08'], 'superfestivi': []}
    lavorativi = {LUN, MAR, MER, GIO, VEN, SAB}

    senza = giorni.conta_turni_dovuti(MESE, ANNO, {}, lavorativi, False)
    con = giorni.conta_turni_dovuti(MESE, ANNO, festivita, lavorativi, False)
    assert con == senza - 1
