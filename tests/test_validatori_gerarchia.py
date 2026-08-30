"""
tests/test_validatori_gerarchia.py — come le regole di conflitto riconoscono
le fasce.

Una regola punta a un flag; il flag di un turno la soddisfa se coincide o se
ne discende. Cosi' una regola scritta sul concetto `notturno` vale per ogni
fascia notturna, comunque l'utente l'abbia rinominata.

La gerarchia si passa esplicitamente: e' quella congelata nel calendario, non
quella di oggi.
"""

import pytest


# Gerarchia di prova: due concetti, tre fasce.
CONCETTO_NOTTURNO = 3
CONCETTO_DIURNO = 2

MAPPA = {
    CONCETTO_DIURNO:   {'id': CONCETTO_DIURNO,   'nome': 'diurno',   'parent_id': None},
    CONCETTO_NOTTURNO: {'id': CONCETTO_NOTTURNO, 'nome': 'notturno', 'parent_id': None},
    11: {'id': 11, 'nome': 'mattina', 'parent_id': CONCETTO_DIURNO},
    14: {'id': 14, 'nome': 'notte',   'parent_id': CONCETTO_NOTTURNO},
    15: {'id': 15, 'nome': 'notte lunga', 'parent_id': CONCETTO_NOTTURNO},
}


@pytest.fixture
def matcha(app):
    """I due matcher, importati dentro il test per non toccare la config."""
    from app.services.validatori import _flag_matcha, _flag_nome_matcha
    return _flag_matcha, _flag_nome_matcha


def test_una_fascia_soddisfa_il_proprio_concetto(matcha):
    """La regola su 'notturno' vale per la notte e per la notte lunga."""
    _flag_matcha, _ = matcha

    assert _flag_matcha(14, CONCETTO_NOTTURNO, MAPPA)
    assert _flag_matcha(15, CONCETTO_NOTTURNO, MAPPA)


def test_una_fascia_non_soddisfa_un_altro_concetto(matcha):
    """La mattina non e' una notte."""
    _flag_matcha, _ = matcha

    assert not _flag_matcha(11, CONCETTO_NOTTURNO, MAPPA)


def test_il_concetto_soddisfa_se_stesso(matcha):
    """Gli snapshot vecchi agganciano i gruppi direttamente al concetto."""
    _flag_matcha, _ = matcha

    assert _flag_matcha(CONCETTO_NOTTURNO, CONCETTO_NOTTURNO, MAPPA)


def test_la_regola_senza_flag_e_un_jolly(matcha):
    """flag_a_id nullo significa 'qualsiasi', ed e' cosi' che si legge a video."""
    _flag_matcha, _ = matcha

    assert _flag_matcha(11, None, MAPPA)
    assert _flag_matcha(None, None, MAPPA)


def test_un_turno_senza_flag_non_soddisfa_nulla_di_specifico(matcha):
    """Un turno senza fascia non puo' far scattare una regola mirata."""
    _flag_matcha, _ = matcha

    assert not _flag_matcha(None, CONCETTO_NOTTURNO, MAPPA)


def test_il_riconoscimento_per_nome_segue_la_stessa_regola(matcha):
    """Gli snapshot portano il nome della fascia, non il suo id."""
    _, _flag_nome_matcha = matcha

    assert _flag_nome_matcha('notte', CONCETTO_NOTTURNO, MAPPA)
    assert _flag_nome_matcha('notte lunga', CONCETTO_NOTTURNO, MAPPA)
    assert not _flag_nome_matcha('mattina', CONCETTO_NOTTURNO, MAPPA)


def test_un_nome_sconosciuto_non_soddisfa(matcha):
    """Una fascia che non e' nella gerarchia congelata non matcha."""
    _, _flag_nome_matcha = matcha

    assert not _flag_nome_matcha('fascia_mai_vista', CONCETTO_NOTTURNO, MAPPA)
    assert not _flag_nome_matcha(None, CONCETTO_NOTTURNO, MAPPA)


def test_la_gerarchia_e_esplicita_non_globale(matcha):
    """
    Due gerarchie diverse danno risposte diverse nella stessa sessione: e' il
    punto della modifica, perche' ogni calendario ha la sua.
    """
    _flag_matcha, _ = matcha

    altra = {14: {'id': 14, 'nome': 'notte', 'parent_id': CONCETTO_DIURNO}}

    assert _flag_matcha(14, CONCETTO_NOTTURNO, MAPPA)
    assert not _flag_matcha(14, CONCETTO_NOTTURNO, altra)
