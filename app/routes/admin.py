"""
app/routes/admin.py — route riservate al ruolo Admin.

Endpoint:
    Utenti:
        GET    /api/admin/users                    → lista utenti
        POST   /api/admin/users                    → crea utente
        PUT    /api/admin/users/<id>               → modifica utente
        DELETE /api/admin/users/<id>               → disabilita utente

    Modello Excel (la struttura letta da un foglio di calcolo):
        GET    /api/admin/modello              → se c'e' un modello caricato
        POST   /api/admin/modello/analizza     → cosa contiene, senza scrivere
        POST   /api/admin/modello/applica      → crea struttura, tipologie, persone

    Festivita' (ricorrenze che rendono festivo un giorno):
        GET    /api/admin/festivita?anno=      → ricorrenze con le date dell'anno
        POST   /api/admin/festivita            → aggiunge una ricorrenza
        PUT    /api/admin/festivita/<id>       → modifica o spegne
        DELETE /api/admin/festivita/<id>       → elimina

    Flag turno (globali, con gerarchia parent e ore/peso):
        GET    /api/admin/flag-turno               → lista flag
        POST   /api/admin/flag-turno               → crea flag
        PUT    /api/admin/flag-turno/<id>          → modifica flag
        DELETE /api/admin/flag-turno/<id>          → elimina flag

    Tipi qualitativo (criterio qualitativo — attività: TC, RM, ambulatorio, reparto...):
        GET    /api/admin/tipi-qualitativo             → lista tipi qualitativo
        POST   /api/admin/tipi-qualitativo             → crea tipo qualitativo
        PUT    /api/admin/tipi-qualitativo/<id>        → modifica tipo qualitativo
        DELETE /api/admin/tipi-qualitativo/<id>        → disabilita tipo qualitativo

    Struttura preset normalizzata:
        GET    /api/admin/struttura-presets/<id>/struttura → struttura completa dal DB
        PUT    /api/admin/struttura-presets/<id>/struttura → sincronizza struttura nel DB
        PUT    /api/admin/struttura-presets/<id>/set-default → imposta preset predefinito
        PUT    /api/admin/struttura-presets/<id>/turni/<tid>/toggle → toggle disable/hide turno
        PUT    /api/admin/struttura-presets/<id>/style-item → salva stile singolo item + history
        POST   /api/admin/struttura-presets/<id>/style-undo → annulla ultima formattazione

    Tutti i gruppi:
        GET    /api/admin/gruppi                   → tutti i gruppi di tutti i preset

    Regole conflitto (globali):
        GET    /api/admin/regole-conflitto         → lista regole
        POST   /api/admin/regole-conflitto         → crea regola
        PUT    /api/admin/regole-conflitto/<id>    → modifica regola
        DELETE /api/admin/regole-conflitto/<id>    → disabilita regola

    Tipi richiesta (globali):
        GET    /api/admin/tipi-richiesta           → lista tipi richiesta
        POST   /api/admin/tipi-richiesta           → crea tipo
        PUT    /api/admin/tipi-richiesta/<id>      → modifica tipo
        DELETE /api/admin/tipi-richiesta/<id>      → elimina tipo

    Calendari:
        GET    /api/admin/calendari                → lista calendari
        POST   /api/admin/calendari                → crea calendario
        PUT    /api/admin/calendari/<id>           → modifica calendario
        DELETE /api/admin/calendari/<id>            → elimina calendario definitivamente
        POST   /api/admin/calendari/<id>/riazzera  → riazzera assegnazioni e history
        POST   /api/admin/calendari/<id>/congela   → congela desiderata (resetta WD)
        POST   /api/admin/calendari/<id>/scongela  → scongela desiderata
        POST   /api/admin/calendari/<id>/stato     → cambia stato

    Giorni calendario:
        GET    /api/admin/calendari/<id>/giorni    → giorni del calendario
        PUT    /api/admin/calendari/<id>/giorni    → aggiorna giorni

    Deadline utenti:
        GET    /api/admin/calendari/<id>/deadline  → deadline per utente
        PUT    /api/admin/calendari/<id>/deadline  → imposta/aggiorna deadline

    Config:
        GET    /api/admin/config                   → parametri di sistema
        PUT    /api/admin/config                   → aggiorna parametri
"""

import io
import json
import secrets
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app

from app.auth import require_role, get_current_user, hash_password
from app.db import query_one, query_all, execute_write, get_db
from app.services.calendario_state import ottieni_calendario_aperto
from app.services.calendario_giorni import (
    TIPO_FESTIVO, TIPO_SUPERFESTIVO,
    classifica_giorno, data_della_ricorrenza, espandi_festivita,
    leggi_giorni_lavorativi
)
from app.services.config_snapshot import crea_config_snapshot
from app.services.proposte import (
    applica as applica_proposta, confronta, e_senza_effetto
)
from app.services.fasce_orarie import (
    NOME_TURNO_TIPO, PAUSA_DEFAULT_MINUTI,
    FormatoOrarioNonValido, parse_orario, ricalcola_tutte
)
from app.services.modello_struttura import leggi_struttura, rinomina_strutture
from app.services.validatori import TIPI_REGOLA

bp = Blueprint('admin', __name__, url_prefix='/api/admin')


# =============================================================================
# FLAG TURNO (globali, con gerarchia parent e parametri ore/peso)
# =============================================================================

# Colonne della fascia oraria restituite al client. Durata, ore e peso sono
# derivati: compaiono in lettura ma li riscrive ricalcola_tutte().
COLONNE_FLAG = (
    "f.id, f.nome, f.parent_id, f.descrizione, "
    "f.orario_inizio, f.orario_fine, f.pausa_minuti, "
    "f.durata_netta_minuti, f.durata_totale_minuti, "
    "f.peso_turno, f.ore_turno, f.ore_primo_giorno, f.ore_ultimo_giorno, "
    "f.mostra_in_struttura, f.solo_su_richiesta, f.tipo"
)

# Valori ammessi dalla colonna flag_turno.tipo.
TIPO_FLAG_ASSENZA = 'assenza'
TIPO_FLAG_DEFAULT = 'lavorativo'
TIPI_FLAG = (TIPO_FLAG_DEFAULT, TIPO_FLAG_ASSENZA)


def _normalizza_orario(valore):
    """
    Porta un orario in ingresso alla forma canonica 'HH:MM', oppure a None.

    La stringa vuota e' un modo legittimo per cancellare l'orario di una
    fascia: la si distingue da un orario malformato, che invece e' un errore.

    Args:
        valore (str|None): orario come arriva dal client.

    Returns:
        str|None: orario canonico, o None se il campo va svuotato.

    Raises:
        FormatoOrarioNonValido: la stringa non e' un orario valido.
    """
    if valore is None:
        return None

    testo = str(valore).strip()
    if not testo:
        return None

    minuti = parse_orario(testo)
    ore, resto = divmod(minuti, 60)

    return f'{ore:02d}:{resto:02d}'


def _leggi_campi_orario(dati, correnti=None):
    """
    Estrae orari e pausa dal payload, con i valori correnti come default.

    Args:
        dati (dict): payload della richiesta.
        correnti (dict|None): riga flag_turno esistente, sulla PUT.

    Returns:
        tuple: (dict con orario_inizio/orario_fine/pausa_minuti, errore|None).
    """
    correnti = correnti or {}

    try:
        campi = {
            'orario_inizio': _normalizza_orario(
                dati.get('orario_inizio', correnti.get('orario_inizio'))
            ),
            'orario_fine': _normalizza_orario(
                dati.get('orario_fine', correnti.get('orario_fine'))
            ),
        }
    except FormatoOrarioNonValido as e:
        return {}, f'Orario non valido: {e}'

    # Su una fascia nuova la pausa non dichiarata e' quella di contratto,
    # non zero: una fascia senza pausa e' una scelta da esprimere.
    pausa = dati.get('pausa_minuti', correnti.get('pausa_minuti'))
    if pausa is None or pausa == '':
        pausa = PAUSA_DEFAULT_MINUTI
    try:
        campi['pausa_minuti'] = max(0, int(pausa))
    except (TypeError, ValueError):
        return {}, 'Pausa non valida: attesi minuti interi.'

    if bool(campi['orario_inizio']) != bool(campi['orario_fine']):
        return {}, 'Servono entrambi gli orari, oppure nessuno dei due.'

    return campi, None


def _normalizza_tipo(valore, default=TIPO_FLAG_DEFAULT):
    """Riporta il tipo flag a un valore ammesso, senza fallire."""
    return valore if valore in TIPI_FLAG else default


def _visibilita_in_struttura(dati, tipo, corrente=1):
    """
    Decide se il flag compare fra le fasce agganciabili ai gruppi.

    Un'assenza non e' una fascia oraria e non entra mai nella struttura
    turni: non e' una scelta dell'utente, e il vincolo vale anche quando un
    flag lavorativo viene riclassificato come assenza.

    Args:
        dati (dict): payload della richiesta.
        tipo (str): tipo del flag, gia' normalizzato.
        corrente (int): valore attuale, usato come default sulla PUT.

    Returns:
        int: 0 oppure 1.
    """
    if tipo == TIPO_FLAG_ASSENZA:
        return 0

    richiesto = dati.get('mostra_in_struttura')
    if richiesto is None:
        return int(bool(corrente))

    return int(bool(richiesto))


def _scrivi_composizione(flag_id, componenti):
    """
    Riscrive da quali fasce e' soddisfatta la richiesta di questa.

    Sostituisce l'elenco intero: la composizione e' una lista, non un insieme
    di righe da aggiungere una per volta. Una fascia non compone se stessa, e
    un id sconosciuto e' un errore del chiamante, non una riga da ignorare.

    Args:
        flag_id (int): la fascia composta, es. la lunga.
        componenti (list|None): id delle fasce che la compongono; None lascia
                                la composizione com'e', [] la svuota.

    Returns:
        str|None: messaggio d'errore, None se la scrittura e' andata.
    """
    if componenti is None:
        return None

    try:
        ids = [int(c) for c in componenti]
    except (TypeError, ValueError):
        return 'Composizione non valida: attesi id di fasce.'

    ids = sorted(set(ids))

    if flag_id in ids:
        return 'Una fascia non puo\' comporre se stessa.'

    for cid in ids:
        if not query_one("SELECT id FROM flag_turno WHERE id=?", (cid,)):
            return f'Fascia {cid} non trovata: non puo\' comporre.'

    # Cancellazione e reinserimento sono la stessa scrittura: a meta' strada
    # la fascia risulterebbe composta da niente.
    db = get_db()
    try:
        db.execute("DELETE FROM flag_composizione WHERE flag_id=?", (flag_id,))
        db.executemany(
            "INSERT INTO flag_composizione (flag_id, componente_flag_id) "
            "VALUES (?,?)",
            [(flag_id, cid) for cid in ids]
        )
        db.commit()
    except Exception as e:
        db.rollback()
        current_app.logger.warning(
            'Scrittura della composizione della fascia %s fallita: %s', flag_id, e
        )
        return 'Composizione non salvata.'

    return None


@bp.route('/flag-turno', methods=['GET'])
@require_role('admin', 'manager')
def lista_flag_turno():
    """Restituisce tutti i flag globali con parent, orari e parametri derivati."""
    flag = query_all(
        f"SELECT {COLONNE_FLAG}, p.nome AS parent_nome "
        "FROM flag_turno f "
        "LEFT JOIN flag_turno p ON f.parent_id = p.id "
        "ORDER BY f.parent_id NULLS FIRST, f.id",
        ()
    )

    # Da cosa e' soddisfatta la richiesta di una fascia: chi chiede la lunga
    # puo' ricevere mattina + pomeriggio.
    composizione = {}
    for r in query_all(
        "SELECT flag_id, componente_flag_id FROM flag_composizione", ()
    ):
        composizione.setdefault(r['flag_id'], []).append(r['componente_flag_id'])

    for f in flag:
        f['componenti'] = composizione.get(f['id'], [])

    return jsonify({'ok': True, 'flags': flag}), 200


@bp.route('/flag-turno', methods=['POST'])
@require_role('admin')
def crea_flag_turno():
    """Crea un flag globale. Durata, ore e peso restano derivati dagli orari."""
    dati = request.get_json(silent=True) or {}
    nome = (dati.get('nome') or '').strip().lower()
    parent_id = dati.get('parent_id')
    descrizione = (dati.get('descrizione') or '').strip()

    if not nome:
        return jsonify({'ok': False, 'errore': 'Nome obbligatorio.'}), 400

    esistente = query_one("SELECT id FROM flag_turno WHERE nome=?", (nome,))
    if esistente:
        return jsonify({'ok': False, 'errore': f'Flag "{nome}" già esistente.'}), 409

    if parent_id:
        parent = query_one("SELECT id FROM flag_turno WHERE id=?", (parent_id,))
        if not parent:
            return jsonify({'ok': False, 'errore': 'Flag parent non trovato.'}), 404

    orari, errore = _leggi_campi_orario(dati)
    if errore:
        return jsonify({'ok': False, 'errore': errore}), 400

    tipo = _normalizza_tipo(dati.get('tipo'))

    cur = execute_write(
        "INSERT INTO flag_turno (nome, parent_id, descrizione, "
        "orario_inizio, orario_fine, pausa_minuti, durata_netta_minuti, "
        "peso_turno, ore_turno, ore_primo_giorno, ore_ultimo_giorno, "
        "mostra_in_struttura, solo_su_richiesta, tipo) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (nome, parent_id, descrizione or None,
         orari['orario_inizio'], orari['orario_fine'], orari['pausa_minuti'],
         dati.get('durata_netta_minuti'),
         dati.get('peso_turno'), dati.get('ore_turno'),
         dati.get('ore_primo_giorno'), dati.get('ore_ultimo_giorno'),
         _visibilita_in_struttura(dati, tipo),
         int(bool(dati.get('solo_su_richiesta', False))), tipo)
    )

    errore = _scrivi_composizione(cur.lastrowid, dati.get('componenti'))
    if errore:
        return jsonify({'ok': False, 'errore': errore}), 400

    ricalcola_tutte(get_db())

    return jsonify({'ok': True, 'id': cur.lastrowid}), 201


@bp.route('/flag-turno/<int:fid>', methods=['PUT'])
@require_role('admin')
def modifica_flag_turno(fid):
    """Modifica un flag globale (nome, parent, orari, pausa, ore manuali)."""
    f = query_one("SELECT * FROM flag_turno WHERE id=?", (fid,))
    if not f:
        return jsonify({'ok': False, 'errore': 'Flag non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    tipo = _normalizza_tipo(dati.get('tipo'), f.get('tipo', TIPO_FLAG_DEFAULT))
    mostra = _visibilita_in_struttura(dati, tipo, f.get('mostra_in_struttura', 1))

    nuovo_nome = (dati.get('nome') or '').strip().lower() or f['nome']
    if nuovo_nome != f['nome']:
        # Il ricalcolo dei pesi cerca il turno tipo per nome: rinominarlo
        # toglierebbe il riferimento a ogni fascia, senza dirlo.
        if f['nome'] == NOME_TURNO_TIPO:
            return jsonify({
                'ok': False,
                'errore': 'Il turno tipo non si rinomina: serve solo a misurare '
                          'il peso degli altri turni. Puoi cambiarne la durata.'
            }), 409

        dup = query_one("SELECT id FROM flag_turno WHERE nome=? AND id!=?", (nuovo_nome, fid))
        if dup:
            return jsonify({'ok': False, 'errore': f'Nome "{nuovo_nome}" già in uso.'}), 409

    orari, errore = _leggi_campi_orario(dati, f)
    if errore:
        return jsonify({'ok': False, 'errore': errore}), 400

    execute_write(
        "UPDATE flag_turno SET nome=?, descrizione=?, parent_id=?, "
        "orario_inizio=?, orario_fine=?, pausa_minuti=?, durata_netta_minuti=?, "
        "peso_turno=?, ore_turno=?, ore_primo_giorno=?, ore_ultimo_giorno=?, "
        "mostra_in_struttura=?, solo_su_richiesta=?, tipo=? WHERE id=?",
        (
            nuovo_nome,
            dati.get('descrizione', f['descrizione']),
            dati.get('parent_id', f['parent_id']),
            orari['orario_inizio'], orari['orario_fine'], orari['pausa_minuti'],
            dati.get('durata_netta_minuti', f.get('durata_netta_minuti')),
            dati.get('peso_turno', f.get('peso_turno')),
            dati.get('ore_turno', f.get('ore_turno')),
            dati.get('ore_primo_giorno', f.get('ore_primo_giorno')),
            dati.get('ore_ultimo_giorno', f.get('ore_ultimo_giorno')),
            mostra,
            int(bool(dati.get('solo_su_richiesta', f.get('solo_su_richiesta', 0)))),
            tipo, fid
        )
    )

    errore = _scrivi_composizione(fid, dati.get('componenti'))
    if errore:
        return jsonify({'ok': False, 'errore': errore}), 400

    if nuovo_nome != f['nome']:
        _propaga_rinomina_flag(fid, f['nome'], nuovo_nome)

    # Gli orari possono essere cambiati: i campi derivati vanno riallineati
    # subito, o resterebbero stantii fino al riavvio successivo.
    ricalcola_tutte(get_db())

    return jsonify({'ok': True, 'messaggio': 'Flag aggiornato.'}), 200


def _propaga_rinomina_flag(fid, vecchio_nome, nuovo_nome):
    """
    Riporta la rinomina di un flag su tutte le dipendenze testuali.

    Il nome del flag e' duplicato negli snapshot dei calendari e nella
    configurazione dei conteggi, che lo memorizzano come stringa: senza
    questa propagazione una rinomina spezzerebbe entrambi.

    Args:
        fid (int): id del flag rinominato.
        vecchio_nome (str): nome precedente.
        nuovo_nome (str): nome nuovo.
    """
    execute_write(
        "UPDATE calendario_turni SET flag_nome=? WHERE flag_id=?",
        (nuovo_nome, fid)
    )

    cfg = query_one("SELECT valore FROM config WHERE chiave='conteggi_context'")
    if not (cfg and cfg['valore']):
        return

    try:
        conteggi = json.loads(cfg['valore'])
    except (json.JSONDecodeError, TypeError):
        return

    modificati = False
    for c in conteggi:
        if c.get('flag_nome') == vecchio_nome:
            c['flag_nome'] = nuovo_nome
            modificati = True

    if modificati:
        execute_write(
            "UPDATE config SET valore=? WHERE chiave='conteggi_context'",
            (json.dumps(conteggi),)
        )


@bp.route('/flag-turno/<int:fid>', methods=['DELETE'])
@require_role('admin')
def elimina_flag_turno(fid):
    """
    Elimina un flag. Con cascade=true elimina anche i figli (se non hanno
    dipendenze).

    Il turno tipo fa eccezione: e' l'unita' di misura da cui si deriva il peso
    di ogni fascia, quindi si puo' modificare nella durata ma non togliere.
    Senza di lui i pesi perderebbero il riferimento.
    """
    da_eliminare = query_one("SELECT nome FROM flag_turno WHERE id=?", (fid,))
    if da_eliminare and da_eliminare['nome'] == NOME_TURNO_TIPO:
        return jsonify({
            'ok': False,
            'errore': 'Il turno tipo non si elimina: è l\'unità di misura da '
                      'cui si ricava il peso di ogni fascia. Puoi cambiarne '
                      'la durata.'
        }), 409

    dati = request.get_json(silent=True) or {}
    cascade = dati.get('cascade', False)

    # Raccogli tutti gli id da eliminare
    figli = query_all("SELECT id, nome FROM flag_turno WHERE parent_id=?", (fid,))
    ids_da_eliminare = [fid] + ([f['id'] for f in figli] if cascade else [])

    # Se ha figli e cascade non richiesto, blocca
    if figli and not cascade:
        return jsonify({
            'ok': False,
            'errore': 'Flag ha figli. Eliminare con i figli?',
            'ha_figli': True,
            'dipendenze': [f['nome'] for f in figli]
        }), 409

    # Controlla dipendenze su tutti gli id da eliminare
    dettagli = []
    for check_id in ids_da_eliminare:
        flag_nome = query_one("SELECT nome FROM flag_turno WHERE id=?", (check_id,))
        label = flag_nome['nome'] if flag_nome else str(check_id)
        g_dip = query_all(
            "SELECT g.sigla AS gruppo_sigla, sp.nome AS preset_nome "
            "FROM gruppi g "
            "JOIN sovragruppi sg ON g.sovragruppo_id = sg.id "
            "JOIN struttura_presets sp ON sg.preset_id = sp.id "
            "WHERE g.flag_id = ?",
            (check_id,)
        )
        tr_dip = query_all("SELECT sigla FROM tipi_richiesta WHERE flag_id=?", (check_id,))
        rc_dip = query_all(
            "SELECT nome FROM regole_conflitto WHERE flag_a_id=? OR flag_b_id=?",
            (check_id, check_id)
        )
        for g in g_dip:
            dettagli.append(f'{label}: gruppo "{g["gruppo_sigla"]}" in "{g["preset_nome"]}"')
        for t in tr_dip:
            dettagli.append(f'{label}: tipo richiesta "{t["sigla"]}"')
        for r in rc_dip:
            dettagli.append(f'{label}: regola "{r["nome"]}"')

    if dettagli:
        return jsonify({
            'ok': False,
            'errore': 'Impossibile eliminare: flag in uso.',
            'dipendenze': dettagli
        }), 409

    # Elimina figli prima, poi parent
    if cascade:
        execute_write("DELETE FROM flag_turno WHERE parent_id=?", (fid,))
    execute_write("DELETE FROM flag_turno WHERE id=?", (fid,))
    return jsonify({'ok': True, 'messaggio': 'Flag eliminato.'}), 200


@bp.route('/flag-turno/ripristina-default', methods=['POST'])
@require_role('admin')
def ripristina_flag_default():
    """Reinserisce i flag default senza toccare quelli già esistenti."""
    from app import CONCETTI_ROOT, _inserisci_flag_default

    db = get_db()
    _inserisci_flag_default(db)

    # I concetti root e le assenze non si agganciano ai gruppi: l'INSERT OR
    # IGNORE non tocca le righe gia' presenti, quindi vanno nascoste qui.
    nomi_root = [nome for nome, _, _, _ in CONCETTI_ROOT]
    segnaposto = ','.join('?' * len(nomi_root))
    try:
        db.execute("UPDATE flag_turno SET mostra_in_struttura = 0 WHERE tipo = 'assenza'")
        db.execute(
            f"UPDATE flag_turno SET mostra_in_struttura = 0 WHERE nome IN ({segnaposto})",
            nomi_root
        )
        db.commit()
    except Exception as e:
        db.rollback()
        current_app.logger.warning('Ripristino visibilità flag default fallito: %s', e)
        return jsonify({
            'ok': False, 'errore': 'Ripristino dei flag default non riuscito.'
        }), 500

    ricalcola_tutte(db)

    return jsonify({'ok': True, 'messaggio': 'Flag default ripristinati.'}), 200


@bp.route('/tipi-richiesta/ripristina-default', methods=['POST'])
@require_role('admin')
def ripristina_tipi_richiesta_default():
    """
    Reinserisce i tipi richiesta di serie che mancano.

    Non tocca quelli presenti: un tipo rinominato o riconfigurato resta com'e'.
    """
    from app import inserisci_tipi_richiesta_default

    inseriti = inserisci_tipi_richiesta_default(get_db())

    return jsonify({'ok': True, 'inseriti': inseriti}), 200


# =============================================================================
# PROPOSTE DI CONFIGURAZIONE (dal master)
# =============================================================================

# Stati di una proposta: in attesa finche' l'amministratore non decide.
STATO_IN_ATTESA = 'in_attesa'


def _proposta_in_attesa():
    """La proposta che aspetta una decisione, se c'e'."""
    return query_one(
        "SELECT id, nome, proposta, proposta_da, note, created_at "
        "FROM proposte_configurazione WHERE stato = ?",
        (STATO_IN_ATTESA,)
    )


@bp.route('/proposta', methods=['GET'])
@require_role('admin')
def leggi_proposta():
    """
    La proposta in attesa, con il confronto rispetto a quello che c'e' ora.

    Il confronto e' la ragione per cui la proposta e' accettabile: senza,
    l'amministratore direbbe di si' alla cieca.
    """
    riga = _proposta_in_attesa()
    if not riga:
        return jsonify({'ok': True, 'proposta': None}), 200

    try:
        parti = json.loads(riga['proposta'])
    except (json.JSONDecodeError, TypeError):
        current_app.logger.warning('Proposta %s illeggibile', riga['id'])
        return jsonify({'ok': False, 'errore': 'La proposta non è leggibile.'}), 500

    differenze = confronta(parti, json.loads(crea_config_snapshot()))

    return jsonify({
        'ok': True,
        'proposta': {
            'id': riga['id'], 'nome': riga['nome'],
            'proposta_da': riga['proposta_da'], 'note': riga['note'],
            'created_at': riga['created_at'],
            'differenze': differenze,
            'senza_effetto': e_senza_effetto(differenze),
        },
    }), 200


@bp.route('/proposta/<int:pid>/accetta', methods=['PUT'])
@require_role('admin')
def accetta_proposta(pid):
    """Allinea il vocabolario del tenant alla proposta."""
    riga = query_one(
        "SELECT proposta FROM proposte_configurazione WHERE id=? AND stato=?",
        (pid, STATO_IN_ATTESA)
    )
    if not riga:
        return jsonify({'ok': False, 'errore': 'Nessuna proposta in attesa.'}), 404

    utente = get_current_user()
    try:
        esito = applica_proposta(get_db(), json.loads(riga['proposta']))
    except Exception as e:
        current_app.logger.warning('Applicazione proposta %s fallita: %s', pid, e)
        return jsonify({'ok': False, 'errore': 'Applicazione non riuscita.'}), 500

    # Durate, ore e peso discendono dagli orari appena arrivati.
    ricalcola_tutte(get_db())

    execute_write(
        "UPDATE proposte_configurazione SET stato='accettata', "
        "decisa_at=datetime('now'), decisa_da=? WHERE id=?",
        (utente['username'], pid)
    )
    return jsonify({'ok': True, 'esito': esito}), 200


@bp.route('/proposta/<int:pid>/rifiuta', methods=['PUT'])
@require_role('admin')
def rifiuta_proposta(pid):
    """Lascia la configurazione com'e' e chiude la proposta."""
    utente = get_current_user()
    cur = execute_write(
        "UPDATE proposte_configurazione SET stato='rifiutata', "
        "decisa_at=datetime('now'), decisa_da=? WHERE id=? AND stato=?",
        (utente['username'], pid, STATO_IN_ATTESA)
    )
    if not cur.rowcount:
        return jsonify({'ok': False, 'errore': 'Nessuna proposta in attesa.'}), 404

    return jsonify({'ok': True, 'messaggio': 'Proposta rifiutata.'}), 200


# =============================================================================
# STILI SEVERITA
# =============================================================================



# =============================================================================
# UTENTI
# =============================================================================

# Campi accettati dalla PUT singola e dalla PUT bulk.
# Ogni voce: nome_campo → (coercer, validator)
#   coercer: fn(value) → value normalizzato (None se cancellare il valore)
#   validator: fn(value) → None se ok, stringa errore se invalido
def _coerce_bool_int(v):
    return int(bool(v))

def _coerce_role(v):
    if v not in ('admin', 'manager', 'basic'):
        raise ValueError('Ruolo non valido.')
    return v

def _coerce_offusca(v):
    iv = int(v)
    if iv not in (0, 1, 2):
        raise ValueError('Valore offusca non valido (ammessi 0/1/2).')
    return iv

def _coerce_sovragruppo_id(v):
    """None/0/'' → NULL; altrimenti verifica che l'id esista."""
    if v in (None, 0, '', '0'):
        return None
    iv = int(v)
    if not query_one("SELECT id FROM sovragruppi WHERE id = ?", (iv,)):
        raise ValueError('Sovragruppo non trovato.')
    return iv

# campi ammessi nelle modifiche utente (singola o bulk)
# Il ruolo che puo' configurare il tenant. Senza almeno uno attivo,
# l'organizzazione non si amministra piu' da dentro.
RUOLO_AMMINISTRATORE = 'admin'

USER_FIELDS = {
    'username':              lambda v: str(v).strip(),
    'role':                  _coerce_role,
    'sigla':                 lambda v: str(v).strip().upper(),
    'is_active':             _coerce_bool_int,
    'escluso_turni':         _coerce_bool_int,
    'puo_gestire_calendari': _coerce_bool_int,
    'sovragruppo_id':        _coerce_sovragruppo_id,
    'offusca':               _coerce_offusca,
    'ordine_desiderata':     lambda v: int(v),
}


def _users_select_sql():
    """
    SELECT utenti con denormalizzazione sovragruppo (LEFT JOIN).
    Ritorna sovragruppo_sigla/_nome per visualizzazione.
    """
    return (
        "SELECT u.id, u.username, u.role, u.sigla, u.is_active, u.escluso_turni, "
        "u.puo_gestire_calendari, u.sovragruppo_id, u.offusca, u.ordine_desiderata, "
        "u.created_at, sg.sigla AS sovragruppo_sigla, sg.nome AS sovragruppo_nome "
        "FROM users u LEFT JOIN sovragruppi sg ON u.sovragruppo_id = sg.id"
    )


@bp.route('/users', methods=['GET'])
@require_role('admin', 'manager')
def lista_utenti():
    utenti = query_all(_users_select_sql() + " ORDER BY u.sigla", ())
    return jsonify({'ok': True, 'utenti': utenti}), 200


@bp.route('/users', methods=['POST'])
@require_role('admin')
def crea_utente():
    dati = request.get_json(silent=True) or {}
    username = (dati.get('username') or '').strip()
    password = (dati.get('password') or '').strip()
    role     = (dati.get('role') or '').strip()
    sigla    = (dati.get('sigla') or '').strip().upper()

    if not all([username, password, role, sigla]):
        return jsonify({'ok': False, 'errore': 'Tutti i campi sono obbligatori.'}), 400
    if role not in ('admin', 'manager', 'basic'):
        return jsonify({'ok': False, 'errore': 'Ruolo non valido.'}), 400

    # Sovragruppo opzionale alla creazione
    try:
        sovragruppo_id = _coerce_sovragruppo_id(dati.get('sovragruppo_id'))
    except ValueError as e:
        return jsonify({'ok': False, 'errore': str(e)}), 400

    esistente = query_one(
        "SELECT id FROM users WHERE username = ? OR sigla = ?", (username, sigla)
    )
    if esistente:
        return jsonify({'ok': False, 'errore': 'Username o sigla già esistente.'}), 409

    me = get_current_user()
    pw_hash = hash_password(password)

    cur = execute_write(
        "INSERT INTO users (username, password_hash, role, sigla, sovragruppo_id, created_by) "
        "VALUES (?,?,?,?,?,?)",
        (username, pw_hash, role, sigla, sovragruppo_id, me['id'])
    )
    return jsonify({'ok': True, 'id': cur.lastrowid,
                    'messaggio': f'Utente {sigla} creato.'}), 201


def _toglie_l_ultimo_amministratore(uid, fields):
    """
    La modifica lascerebbe il tenant senza amministratori attivi?

    Un tenant senza amministratore non si riconfigura piu' da dentro: per
    rientrare servirebbe il superadmin di piattaforma. Vale sia per il
    cambio di ruolo sia per la disattivazione.

    Args:
        uid (int): utente che si sta modificando.
        fields (dict): campi in arrivo.

    Returns:
        bool: True se dopo la modifica non resterebbe nessun amministratore.
    """
    perde_il_ruolo = 'role' in fields and fields['role'] != RUOLO_AMMINISTRATORE
    viene_disattivato = 'is_active' in fields and not _coerce_bool_int(fields['is_active'])
    if not (perde_il_ruolo or viene_disattivato):
        return False

    attuale = query_one(
        "SELECT role, is_active FROM users WHERE id = ?", (uid,)
    )
    if not attuale or attuale['role'] != RUOLO_AMMINISTRATORE or not attuale['is_active']:
        return False

    altri = query_one(
        "SELECT COUNT(*) AS quanti FROM users "
        "WHERE role = ? AND is_active = 1 AND id != ?",
        (RUOLO_AMMINISTRATORE, uid)
    )

    return not altri['quanti']


def _apply_user_fields(uid, fields):
    """
    Applica i campi `fields` all'utente uid.
    Gestisce anche gli effetti collaterali (password, escluso_turni→svuota assegnazioni).
    Ritorna (None, None) in caso di successo, (errore, status_code) altrimenti.
    """
    if _toglie_l_ultimo_amministratore(uid, fields):
        return ('Questo e\' l\'unico amministratore attivo: togliergli il ruolo '
                'lascerebbe l\'organizzazione senza nessuno che possa '
                'configurarla. Nominane un altro prima.'), 409

    aggiornamenti = []
    valori = []
    escludi = None

    # password: campo speciale (non in USER_FIELDS)
    if 'password' in fields and fields['password']:
        aggiornamenti.append("password_hash = ?")
        valori.append(hash_password(fields['password']))

    for campo, coercer in USER_FIELDS.items():
        if campo not in fields:
            continue
        try:
            val = coercer(fields[campo])
        except (ValueError, TypeError) as e:
            return (str(e) or f'Valore non valido per {campo}.'), 400
        aggiornamenti.append(f"{campo} = ?")
        valori.append(val)
        if campo == 'escluso_turni':
            escludi = val

    if not aggiornamenti:
        return 'Nessun campo da aggiornare.', 400

    valori.append(uid)
    execute_write(
        f"UPDATE users SET {', '.join(aggiornamenti)} WHERE id = ?", valori
    )

    # Se l'utente viene escluso, azzera le sue assegnazioni nei calendari aperti
    if escludi == 1:
        execute_write(
            """
            UPDATE assegnazioni_turni
            SET user_id = NULL, conflitto = 'empty', conflitti = '[]',
                forza_inserimento = 0, forza_note = NULL
            WHERE user_id = ?
              AND calendario_id IN (
                  SELECT id FROM calendari WHERE stato = 'APERTO'
              )
            """,
            (uid,)
        )
    return None, None


@bp.route('/users/<int:uid>', methods=['PUT'])
@require_role('admin')
def modifica_utente(uid):
    utente = query_one("SELECT id FROM users WHERE id = ?", (uid,))
    if not utente:
        return jsonify({'ok': False, 'errore': 'Utente non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    errore, status = _apply_user_fields(uid, dati)
    if errore:
        return jsonify({'ok': False, 'errore': errore}), status

    return jsonify({'ok': True, 'messaggio': 'Utente aggiornato.'}), 200


@bp.route('/users/bulk', methods=['PUT'])
@require_role('admin')
def modifica_utenti_bulk():
    """
    Modifica bulk di uno o piu' campi su piu' utenti.
    Body: { user_ids: [...], fields: { <campo>: <valore>, ... } }
    I campi ammessi sono quelli in USER_FIELDS (password esclusa: sicurezza).
    """
    dati = request.get_json(silent=True) or {}
    user_ids = dati.get('user_ids') or []
    fields = dati.get('fields') or {}

    if not isinstance(user_ids, list) or not user_ids:
        return jsonify({'ok': False, 'errore': 'Nessun utente selezionato.'}), 400
    if not isinstance(fields, dict) or not fields:
        return jsonify({'ok': False, 'errore': 'Nessun campo da aggiornare.'}), 400

    # Filtra campi: solo quelli in whitelist, password non ammessa in bulk
    campi_ammessi = {k: v for k, v in fields.items() if k in USER_FIELDS}
    if not campi_ammessi:
        return jsonify({'ok': False, 'errore': 'Nessun campo valido.'}), 400

    aggiornati = 0
    for uid in user_ids:
        try:
            uid_int = int(uid)
        except (ValueError, TypeError):
            continue
        utente = query_one("SELECT id FROM users WHERE id = ?", (uid_int,))
        if not utente:
            continue
        errore, _ = _apply_user_fields(uid_int, campi_ammessi)
        if not errore:
            aggiornati += 1

    return jsonify({
        'ok': True,
        'aggiornati': aggiornati,
        'messaggio': f'{aggiornati} utenti aggiornati.'
    }), 200


# =============================================================================
# ORDINAMENTO DESIDERATA (globale, manager+admin)
# =============================================================================

VALID_MODALITA_ORDINAMENTO = ('manuale', 'alfabetico_globale', 'alfabetico_intragruppo')


@bp.route('/ordinamento-desiderata', methods=['GET'])
@require_role('admin', 'manager')
def get_ordinamento_desiderata():
    """Restituisce modalità corrente + ordine sovragruppi + ordine utenti."""
    cfg = query_one(
        "SELECT valore FROM config WHERE chiave='modalita_ordinamento_desiderata'"
    )
    modalita = cfg['valore'] if cfg else 'alfabetico_intragruppo'

    # Sovragruppi della struttura "corrente" = preset is_default=1 (fallback: primo)
    preset = query_one(
        "SELECT id FROM struttura_presets WHERE is_default=1 LIMIT 1"
    ) or query_one("SELECT id FROM struttura_presets ORDER BY id LIMIT 1")

    sovragruppi = []
    if preset:
        sovragruppi = query_all(
            "SELECT id, sigla, nome, ordine, ordine_desiderata "
            "FROM sovragruppi WHERE preset_id=? "
            "ORDER BY COALESCE(ordine_desiderata, ordine), id",
            (preset['id'],)
        )

    return jsonify({
        'ok': True,
        'modalita': modalita,
        'sovragruppi': sovragruppi,
    }), 200


@bp.route('/ordinamento-desiderata/modalita', methods=['PUT'])
@require_role('admin', 'manager')
def set_ordinamento_desiderata_modalita():
    dati = request.get_json(silent=True) or {}
    modalita = (dati.get('modalita') or '').strip()
    if modalita not in VALID_MODALITA_ORDINAMENTO:
        return jsonify({
            'ok': False,
            'errore': f'Modalità non valida (ammesse: {", ".join(VALID_MODALITA_ORDINAMENTO)}).'
        }), 400

    execute_write(
        "INSERT INTO config (chiave, valore) VALUES ('modalita_ordinamento_desiderata', ?) "
        "ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore",
        (modalita,)
    )
    return jsonify({'ok': True, 'modalita': modalita}), 200


@bp.route('/ordinamento-desiderata/sovragruppi', methods=['PUT'])
@require_role('admin', 'manager')
def set_ordine_sovragruppi_desiderata():
    """Body: { ordine: [sg_id1, sg_id2, ...] } → riscrive sovragruppi.ordine_desiderata."""
    dati = request.get_json(silent=True) or {}
    ordine = dati.get('ordine') or []
    if not isinstance(ordine, list):
        return jsonify({'ok': False, 'errore': 'Ordine non valido.'}), 400

    for pos, sg_id in enumerate(ordine):
        try:
            sg_id_int = int(sg_id)
        except (ValueError, TypeError):
            continue
        execute_write(
            "UPDATE sovragruppi SET ordine_desiderata = ? WHERE id = ?",
            (pos, sg_id_int)
        )
    return jsonify({'ok': True, 'aggiornati': len(ordine)}), 200


@bp.route('/ordinamento-desiderata/utenti', methods=['PUT'])
@require_role('admin', 'manager')
def set_ordine_utenti_desiderata():
    """Body: { ordine: [uid1, uid2, ...] } → riscrive users.ordine_desiderata."""
    dati = request.get_json(silent=True) or {}
    ordine = dati.get('ordine') or []
    if not isinstance(ordine, list):
        return jsonify({'ok': False, 'errore': 'Ordine non valido.'}), 400

    for pos, uid in enumerate(ordine):
        try:
            uid_int = int(uid)
        except (ValueError, TypeError):
            continue
        execute_write(
            "UPDATE users SET ordine_desiderata = ? WHERE id = ?",
            (pos, uid_int)
        )
    return jsonify({'ok': True, 'aggiornati': len(ordine)}), 200


@bp.route('/users/<int:uid>', methods=['DELETE'])
@require_role('admin')
def disabilita_utente(uid):
    utente = query_one("SELECT id, sigla FROM users WHERE id = ?", (uid,))
    if not utente:
        return jsonify({'ok': False, 'errore': 'Utente non trovato.'}), 404

    execute_write("UPDATE users SET is_active = 0 WHERE id = ?", (uid,))
    return jsonify({'ok': True, 'messaggio': f'Utente {utente["sigla"]} disabilitato.'}), 200


# =============================================================================
# STRUTTURA PRESETS
# =============================================================================

@bp.route('/struttura-presets', methods=['GET'])
@require_role('admin', 'manager')
def lista_presets():
    presets = query_all(
        "SELECT id, nome, is_default, created_at, last_used_at "
        "FROM struttura_presets ORDER BY nome"
    )
    return jsonify({'ok': True, 'presets': presets}), 200


@bp.route('/struttura-presets', methods=['POST'])
@require_role('admin')
def crea_preset():
    dati = request.get_json(silent=True) or {}
    nome = (dati.get('nome') or '').strip()
    if not nome:
        return jsonify({'ok': False, 'errore': 'Nome obbligatorio.'}), 400

    esistente = query_one("SELECT id FROM struttura_presets WHERE nome=?", (nome,))
    if esistente:
        return jsonify({'ok': False, 'errore': f'Preset "{nome}" già esistente.'}), 409

    me = get_current_user()
    cur = execute_write(
        "INSERT INTO struttura_presets (nome, created_by) VALUES (?,?)",
        (nome, me['id'])
    )
    return jsonify({'ok': True, 'id': cur.lastrowid}), 201


@bp.route('/struttura-presets/<int:pid>/appearance', methods=['GET'])
@require_role('admin', 'manager')
def get_appearance_preset(pid):
    """Ritorna l'appearance del preset (con defaults applicati)."""
    from app.services.config_snapshot import APPEARANCE_DEFAULT
    preset = query_one("SELECT appearance FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404
    try:
        data = json.loads(preset['appearance']) if preset['appearance'] else {}
    except (json.JSONDecodeError, TypeError):
        data = {}
    return jsonify({'ok': True, 'appearance': {**APPEARANCE_DEFAULT, **data}}), 200


@bp.route('/struttura-presets/<int:pid>/appearance', methods=['PUT'])
@require_role('admin', 'manager')
def salva_appearance_preset(pid):
    """Salva l'appearance di un preset."""
    preset = query_one("SELECT id FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404
    dati = request.get_json(silent=True) or {}
    app_data = dati.get('appearance', {})
    execute_write(
        "UPDATE struttura_presets SET appearance=? WHERE id=?",
        (json.dumps(app_data), pid)
    )
    return jsonify({'ok': True}), 200


@bp.route('/struttura-presets/<int:pid>', methods=['PUT'])
@require_role('admin')
def modifica_preset(pid):
    preset = query_one("SELECT * FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    nome = (dati.get('nome') or preset['nome']).strip()

    execute_write(
        "UPDATE struttura_presets SET nome=? WHERE id=?",
        (nome, pid)
    )
    return jsonify({'ok': True, 'messaggio': 'Preset aggiornato.'}), 200


@bp.route('/struttura-presets/<int:pid>', methods=['DELETE'])
@require_role('admin')
def elimina_preset(pid):
    preset = query_one("SELECT id FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    execute_write("DELETE FROM struttura_presets WHERE id=?", (pid,))
    return jsonify({'ok': True, 'messaggio': 'Preset eliminato.'}), 200


@bp.route('/struttura-presets/<int:pid>/set-default', methods=['PUT'])
@require_role('admin')
def set_preset_default(pid):
    """
    Feature: imposta preset predefinito per nuovi calendari.
    Azzera is_default su tutti i preset, poi imposta is_default=1 sul preset scelto.
    """
    preset = query_one("SELECT id FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    execute_write("UPDATE struttura_presets SET is_default=0 WHERE 1=1")
    execute_write("UPDATE struttura_presets SET is_default=1 WHERE id=?", (pid,))
    return jsonify({'ok': True, 'messaggio': 'Preset predefinito impostato.'}), 200


@bp.route('/struttura-presets/<int:pid>/duplica', methods=['POST'])
@require_role('admin', 'manager')
def duplica_preset(pid):
    """
    Copia profonda di un preset struttura.
    Duplica: struttura_presets → sovragruppi → gruppi → preset_turni
             → preset_turni_qualitativo + posti_fissi (+posti_fissi_utenti)
             + preset_esclusioni_turno_per_utente + manager_accesso_turni
    Non copia: vincoli_solver (globali, non per-preset).
    """
    preset = query_one("SELECT * FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    nuovo_nome = (dati.get('nome') or f"{preset['nome']} (copia)").strip()

    if query_one("SELECT id FROM struttura_presets WHERE nome=?", (nuovo_nome,)):
        return jsonify({'ok': False, 'errore': f'Nome "{nuovo_nome}" già in uso.'}), 409

    me = get_current_user()
    cur = execute_write(
        "INSERT INTO struttura_presets (nome, created_by) VALUES (?,?)",
        (nuovo_nome, me['id'])
    )
    nuovo_pid = cur.lastrowid

    # Mappa id_vecchio → id_nuovo per sovragruppi e gruppi (necessari per riferimenti)
    sg_map = {}   # old_sg_id → new_sg_id
    g_map  = {}   # old_g_id  → new_g_id
    t_map  = {}   # old_pt_id → new_pt_id

    sgs = query_all(
        "SELECT id, sigla, nome, ambito, escluso_solver, ordine, style "
        "FROM sovragruppi WHERE preset_id=? ORDER BY ordine",
        (pid,)
    )
    for sg in sgs:
        c = execute_write(
            "INSERT INTO sovragruppi (preset_id, sigla, nome, ambito, ordine, style) VALUES (?,?,?,?,?,?)",
            (nuovo_pid, sg['sigla'], sg['nome'], sg['ambito'], sg['ordine'], sg['style'])
        )
        new_sg_id = c.lastrowid
        sg_map[sg['id']] = new_sg_id

        gruppi = query_all(
            "SELECT id, sigla, nome, flag_id, ordine, style FROM gruppi WHERE sovragruppo_id=? ORDER BY ordine",
            (sg['id'],)
        )
        for g in gruppi:
            cg = execute_write(
                "INSERT INTO gruppi (sovragruppo_id, sigla, nome, flag_id, ordine, style) VALUES (?,?,?,?,?,?)",
                (new_sg_id, g['sigla'], g['nome'], g['flag_id'], g['ordine'], g['style'])
            )
            new_g_id = cg.lastrowid
            g_map[g['id']] = new_g_id

            turni = query_all(
                "SELECT id, sigla, nome, ordine, style, priorita_solver, peso_priorita_solver, "
                "       apri_festivi, apri_superfestivi, is_disabled, is_hidden "
                "FROM preset_turni WHERE gruppo_id=? ORDER BY ordine",
                (g['id'],)
            )
            for t in turni:
                ct = execute_write(
                    "INSERT INTO preset_turni "
                    "(gruppo_id, sigla, nome, ordine, style, priorita_solver, peso_priorita_solver, "
                    " apri_festivi, apri_superfestivi, is_disabled, is_hidden) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (new_g_id, t['sigla'], t['nome'], t['ordine'], t['style'],
                     t['priorita_solver'], t['peso_priorita_solver'],
                     t['apri_festivi'], t['apri_superfestivi'],
                     t.get('is_disabled', 0), t.get('is_hidden', 0))
                )
                new_t_id = ct.lastrowid
                t_map[t['id']] = new_t_id

                # Copia tipi qualitativi
                tq_rows = query_all(
                    "SELECT tipo_qualitativo_id FROM preset_turni_qualitativo WHERE preset_turno_id=?",
                    (t['id'],)
                )
                for tq in tq_rows:
                    execute_write(
                        "INSERT OR IGNORE INTO preset_turni_qualitativo (preset_turno_id, tipo_qualitativo_id) VALUES (?,?)",
                        (new_t_id, tq['tipo_qualitativo_id'])
                    )

    # Copia posti_fissi (con posti_fissi_utenti)
    pf_rows = query_all(
        "SELECT id, preset_turno_id, giorno_settimana, nome, is_active, manager_id "
        "FROM posti_fissi WHERE preset_id=?",
        (pid,)
    )
    for pf in pf_rows:
        new_pt_id = t_map.get(pf['preset_turno_id'])
        if not new_pt_id:
            continue
        cpf = execute_write(
            "INSERT INTO posti_fissi (preset_id, preset_turno_id, giorno_settimana, nome, is_active, manager_id) "
            "VALUES (?,?,?,?,?,?)",
            (nuovo_pid, new_pt_id, pf['giorno_settimana'], pf['nome'], pf['is_active'], pf['manager_id'])
        )
        new_pf_id = cpf.lastrowid
        pfu_rows = query_all(
            "SELECT user_id, ordine FROM posti_fissi_utenti WHERE posto_fisso_id=? ORDER BY ordine",
            (pf['id'],)
        )
        for u in pfu_rows:
            execute_write(
                "INSERT INTO posti_fissi_utenti (posto_fisso_id, user_id, ordine) VALUES (?,?,?)",
                (new_pf_id, u['user_id'], u['ordine'])
            )

    # Copia esclusioni turno per utente
    et_rows = query_all(
        "SELECT user_id, tipo, target_id, eccezioni "
        "FROM preset_esclusioni_turno_per_utente WHERE preset_id=?",
        (pid,)
    )
    for et in et_rows:
        # Risolvi target_id al nuovo id se il tipo ha corrispondenza nella mappa
        if et['tipo'] == 'turno':
            new_target = t_map.get(et['target_id'])
        elif et['tipo'] == 'gruppo':
            new_target = g_map.get(et['target_id'])
        else:  # sovragruppo
            new_target = sg_map.get(et['target_id'])
        if new_target:
            # Rimappa eccezioni (target_id figli) ai nuovi id
            try:
                ecc_old = json.loads(et['eccezioni'] or '[]')
            except (json.JSONDecodeError, TypeError):
                ecc_old = []
            # Eccezioni possono essere turni o gruppi — prova entrambe le mappe
            ecc_new = []
            for e in ecc_old:
                mapped = t_map.get(e) or g_map.get(e)
                if mapped:
                    ecc_new.append(mapped)
            execute_write(
                "INSERT OR IGNORE INTO preset_esclusioni_turno_per_utente "
                "(preset_id, user_id, tipo, target_id, eccezioni) VALUES (?,?,?,?,?)",
                (nuovo_pid, et['user_id'], et['tipo'], new_target, json.dumps(ecc_new))
            )

    # Copia manager_accesso_turni (usa nuovo preset_turno_id)
    at_rows = query_all(
        "SELECT manager_id, preset_turno_id FROM manager_accesso_turni WHERE preset_turno_id IN "
        "(SELECT id FROM preset_turni WHERE gruppo_id IN "
        " (SELECT id FROM gruppi WHERE sovragruppo_id IN "
        "  (SELECT id FROM sovragruppi WHERE preset_id=?)))",
        (pid,)
    )
    for at in at_rows:
        new_pt_id = t_map.get(at['preset_turno_id'])
        if new_pt_id:
            execute_write(
                "INSERT OR IGNORE INTO manager_accesso_turni (manager_id, preset_turno_id) VALUES (?,?)",
                (at['manager_id'], new_pt_id)
            )

    return jsonify({
        'ok': True,
        'id': nuovo_pid,
        'nome': nuovo_nome,
        'messaggio': f'Preset "{nuovo_nome}" creato.'
    }), 201


# =============================================================================
# TIPI QUALITATIVO (criterio qualitativo dei turni) — globali
# =============================================================================

@bp.route('/tipi-qualitativo', methods=['GET'])
@require_role('admin', 'manager')
def lista_tipi_qualitativo():
    tipi = query_all(
        "SELECT id, nome, descrizione, carico_lavoro, ordine, is_active FROM tipi_qualitativo ORDER BY nome",
        ()
    )
    return jsonify({'ok': True, 'tipi': tipi}), 200


@bp.route('/tipi-qualitativo', methods=['POST'])
@require_role('admin')
def crea_tipo_qualitativo():
    dati   = request.get_json(silent=True) or {}
    nome   = (dati.get('nome') or '').strip()
    if not nome:
        return jsonify({'ok': False, 'errore': 'Nome obbligatorio.'}), 400
    esistente = query_one(
        "SELECT id FROM tipi_qualitativo WHERE nome=?",
        (nome,)
    )
    if esistente:
        return jsonify({'ok': False, 'errore': f'Tipo "{nome}" già esistente.'}), 409
    descrizione = (dati.get('descrizione') or '').strip()
    carico = int(dati.get('carico_lavoro', 0) or 0)
    cur = execute_write(
        "INSERT INTO tipi_qualitativo (nome, descrizione, carico_lavoro) VALUES (?,?,?)",
        (nome, descrizione, carico)
    )
    return jsonify({'ok': True, 'id': cur.lastrowid}), 201


@bp.route('/tipi-qualitativo/<int:tid>', methods=['PUT'])
@require_role('admin')
def modifica_tipo_qualitativo(tid):
    tq = query_one("SELECT * FROM tipi_qualitativo WHERE id=?", (tid,))
    if not tq:
        return jsonify({'ok': False, 'errore': 'Tipo qualitativo non trovato.'}), 404
    dati = request.get_json(silent=True) or {}
    execute_write(
        "UPDATE tipi_qualitativo SET nome=?, descrizione=?, carico_lavoro=? WHERE id=?",
        (
            dati.get('nome', tq['nome']).strip(),
            (dati.get('descrizione') if 'descrizione' in dati else tq.get('descrizione', '')).strip(),
            int(dati.get('carico_lavoro', tq.get('carico_lavoro', 0)) or 0),
            tid
        )
    )
    return jsonify({'ok': True, 'messaggio': 'Tipo qualitativo aggiornato.'}), 200


@bp.route('/tipi-qualitativo/<int:tid>', methods=['DELETE'])
@require_role('admin')
def elimina_tipo_qualitativo(tid):
    turni_dip = query_all(
        "SELECT pt.id, pt.sigla AS turno_sigla, sp.nome AS preset_nome "
        "FROM preset_turni_qualitativo ptq "
        "JOIN preset_turni pt ON ptq.preset_turno_id = pt.id "
        "JOIN gruppi g ON pt.gruppo_id = g.id "
        "JOIN sovragruppi sg ON g.sovragruppo_id = sg.id "
        "JOIN struttura_presets sp ON sg.preset_id = sp.id "
        "WHERE ptq.tipo_qualitativo_id = ?",
        (tid,)
    )

    if turni_dip:
        dettagli = [
            f"Turno \"{t['turno_sigla']}\" nel preset \"{t['preset_nome']}\""
            for t in turni_dip
        ]
        return jsonify({
            'ok': False,
            'errore': 'Impossibile eliminare: tipo in uso.',
            'dipendenze': dettagli
        }), 409

    execute_write("DELETE FROM tipi_qualitativo WHERE id=?", (tid,))
    return jsonify({'ok': True, 'messaggio': 'Tipo qualitativo eliminato.'}), 200


# =============================================================================
# STRUTTURA PRESET NORMALIZZATA
# =============================================================================

@bp.route('/struttura-presets/<int:pid>/struttura', methods=['GET'])
@require_role('admin', 'manager')
def get_struttura_preset(pid):
    preset = query_one("SELECT id, nome FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    sgs = query_all(
        "SELECT id, sigla, nome, ambito, escluso_solver, ordine, style "
        "FROM sovragruppi WHERE preset_id=? ORDER BY ordine",
        (pid,)
    )
    struttura = []
    for sg in sgs:
        gruppi_list = query_all(
            "SELECT g.id, g.sigla, g.nome, g.flag_id, g.ordine, g.style, "
            "ft.nome AS flag_nome "
            "FROM gruppi g LEFT JOIN flag_turno ft ON g.flag_id=ft.id "
            "WHERE g.sovragruppo_id=? ORDER BY g.ordine",
            (sg['id'],)
        )
        sg_out = {
            'id': sg['id'], 'sigla': sg['sigla'], 'nome': sg['nome'],
            'ambito': sg['ambito'], 'ordine': sg['ordine'],
            # Senza, chi rilegge la struttura per modificarla la riscrive
            # dentro al solver: la sospensione si perderebbe in silenzio.
            'escluso_solver': sg.get('escluso_solver', 0),
            'style': json.loads(sg.get('style', '{}')), 'gruppi': []
        }
        for g in gruppi_list:
            turni_list = query_all(
                "SELECT id, sigla, nome, ordine, style, priorita_solver, peso_priorita_solver, "
                "       apri_festivi, apri_superfestivi, is_disabled, is_hidden "
                "FROM preset_turni WHERE gruppo_id=? ORDER BY ordine",
                (g['id'],)
            )
            sg_out['gruppi'].append({
                'id': g['id'], 'sigla': g['sigla'], 'nome': g['nome'],
                'flag_id': g['flag_id'], 'flag_nome': g['flag_nome'] or '',
                'ordine': g['ordine'], 'style': json.loads(g.get('style', '{}')),
                'turni': [
                    {
                        'id': t['id'], 'sigla': t['sigla'], 'nome': t['nome'], 'ordine': t['ordine'],
                        'style': json.loads(t.get('style', '{}')),
                        'priorita_solver': t.get('priorita_solver', 'automatico'),
                        'peso_priorita_solver': t.get('peso_priorita_solver', 50),
                        'apri_festivi': t.get('apri_festivi', 0),
                        'apri_superfestivi': t.get('apri_superfestivi', 0),
                        'is_disabled': t.get('is_disabled', 0),
                        'is_hidden': t.get('is_hidden', 0),
                        'tipi_qualitativi': [
                            {'id': tq['id'], 'nome': tq['nome']}
                            for tq in query_all(
                                "SELECT tq.id, tq.nome FROM tipi_qualitativo tq "
                                "JOIN preset_turni_qualitativo ptq ON tq.id = ptq.tipo_qualitativo_id "
                                "WHERE ptq.preset_turno_id = ?", (t['id'],)
                            )
                        ]
                    }
                    for t in turni_list
                ]
            })
        struttura.append(sg_out)
    return jsonify({'ok': True, 'struttura': struttura}), 200


def _prima_fascia_duplicata(struttura_in):
    """
    Cerca una fascia oraria usata due volte nella stessa struttura.

    Il gruppo E' l'insieme dei turni di una fascia dentro un sovragruppo:
    due gruppi sulla stessa fascia non hanno significato, e l'indice unico
    idx_gruppi_sovragruppo_fascia li rifiuterebbe comunque a meta'
    salvataggio, con un errore di database al posto di un messaggio.

    Args:
        struttura_in (list): struttura in arrivo dal client.

    Returns:
        tuple|None: (nome struttura, nome fascia) del primo duplicato.
    """
    for sovragruppo in struttura_in:
        viste = set()
        for gruppo in sovragruppo.get('gruppi', []):
            flag_id = gruppo.get('flag_id')
            if flag_id is None:
                continue

            if flag_id in viste:
                fascia = query_one("SELECT nome FROM flag_turno WHERE id=?", (flag_id,))
                nome_struttura = sovragruppo.get('nome') or sovragruppo.get('sigla') or '?'
                return nome_struttura, (fascia['nome'] if fascia else str(flag_id))

            viste.add(flag_id)

    return None


@bp.route('/struttura-presets/<int:pid>/struttura', methods=['PUT'])
@require_role('admin')
def salva_struttura_preset(pid):
    preset = query_one("SELECT id FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    struttura_in = dati.get('struttura', [])

    duplicato = _prima_fascia_duplicata(struttura_in)
    if duplicato:
        nome_struttura, nome_fascia = duplicato
        return jsonify({
            'ok': False,
            'errore': f'La fascia "{nome_fascia}" è già presente in '
                      f'"{nome_struttura}": una fascia oraria può comparire '
                      f'una volta sola per struttura.'
        }), 409

    # Raccogli IDs esistenti nel DB per questo preset (per rilevare eliminazioni)
    sg_db_ids = {r['id'] for r in query_all(
        "SELECT id FROM sovragruppi WHERE preset_id=?", (pid,)
    )}
    g_db_ids = set()
    t_db_ids = set()
    for sg_id in sg_db_ids:
        for g in query_all("SELECT id FROM gruppi WHERE sovragruppo_id=?", (sg_id,)):
            g_db_ids.add(g['id'])
            for t in query_all("SELECT id FROM preset_turni WHERE gruppo_id=?", (g['id'],)):
                t_db_ids.add(t['id'])

    sg_ids_visti = set()
    g_ids_visti  = set()
    t_ids_visti  = set()

    struttura_out = []

    for sg_ordine, sg_in in enumerate(struttura_in):
        sg_id_in = sg_in.get('id')
        new_sg = not isinstance(sg_id_in, int)

        sg_style_json = json.dumps(sg_in.get('style', {}))
        if new_sg:
            cur = execute_write(
                "INSERT INTO sovragruppi (preset_id, sigla, nome, ambito, escluso_solver, "
                "ordine, style) VALUES (?,?,?,?,?,?,?)",
                (pid, sg_in.get('sigla', ''), sg_in.get('nome', ''),
                 sg_in.get('ambito', ''),
                 int(bool(sg_in.get('escluso_solver', 0))),
                 sg_ordine * 10, sg_style_json)
            )
            sg_real_id = cur.lastrowid
        else:
            execute_write(
                "UPDATE sovragruppi SET sigla=?, nome=?, ambito=?, escluso_solver=?, "
                "ordine=?, style=? WHERE id=?",
                (sg_in.get('sigla', ''), sg_in.get('nome', ''),
                 sg_in.get('ambito', ''),
                 int(bool(sg_in.get('escluso_solver', 0))),
                 sg_ordine * 10, sg_style_json, sg_id_in)
            )
            sg_real_id = sg_id_in

        sg_ids_visti.add(sg_real_id)
        gruppi_out = []

        for g_ordine, g_in in enumerate(sg_in.get('gruppi', [])):
            g_id_in = g_in.get('id')
            new_g = not isinstance(g_id_in, int)
            flag_id = g_in.get('flag_id')

            g_style_json = json.dumps(g_in.get('style', {}))
            if new_g:
                cur = execute_write(
                    "INSERT INTO gruppi (sovragruppo_id, sigla, nome, flag_id, ordine, style) "
                    "VALUES (?,?,?,?,?,?)",
                    (sg_real_id, g_in.get('sigla', ''), g_in.get('nome', ''),
                     flag_id, g_ordine * 10, g_style_json)
                )
                g_real_id = cur.lastrowid
            else:
                execute_write(
                    "UPDATE gruppi SET sigla=?, nome=?, flag_id=?, ordine=?, style=? WHERE id=?",
                    (g_in.get('sigla', ''), g_in.get('nome', ''),
                     flag_id, g_ordine * 10, g_style_json, g_id_in)
                )
                g_real_id = g_id_in

            g_ids_visti.add(g_real_id)
            turni_out = []

            for t_ordine, t_in in enumerate(g_in.get('turni', [])):
                t_id_in = t_in.get('id')
                new_t = not isinstance(t_id_in, int)

                t_style_json = json.dumps(t_in.get('style', {}))
                t_priorita = t_in.get('priorita_solver', 'automatico')
                t_peso = t_in.get('peso_priorita_solver', 50)
                t_apri_f = int(t_in.get('apri_festivi', 0) or 0)
                t_apri_sf = int(t_in.get('apri_superfestivi', 0) or 0)
                t_disabled = int(t_in.get('is_disabled', 0) or 0)
                t_hidden = int(t_in.get('is_hidden', 0) or 0)
                if new_t:
                    cur = execute_write(
                        "INSERT INTO preset_turni (gruppo_id, sigla, nome, ordine, style, "
                        "priorita_solver, peso_priorita_solver, apri_festivi, apri_superfestivi, "
                        "is_disabled, is_hidden) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (g_real_id, t_in.get('sigla', ''), t_in.get('nome', ''),
                         t_ordine * 10, t_style_json, t_priorita, t_peso,
                         t_apri_f, t_apri_sf, t_disabled, t_hidden)
                    )
                    t_real_id = cur.lastrowid
                else:
                    execute_write(
                        "UPDATE preset_turni SET sigla=?, nome=?, ordine=?, style=?, "
                        "priorita_solver=?, peso_priorita_solver=?, "
                        "apri_festivi=?, apri_superfestivi=?, "
                        "is_disabled=?, is_hidden=? WHERE id=?",
                        (t_in.get('sigla', ''), t_in.get('nome', ''), t_ordine * 10,
                         t_style_json, t_priorita, t_peso,
                         t_apri_f, t_apri_sf, t_disabled, t_hidden, t_id_in)
                    )
                    t_real_id = t_id_in

                t_ids_visti.add(t_real_id)

                # Aggiorna relazione M:N tipi_qualitativi
                execute_write(
                    "DELETE FROM preset_turni_qualitativo WHERE preset_turno_id=?",
                    (t_real_id,)
                )
                tq_out = []
                for tq in t_in.get('tipi_qualitativi', []):
                    tq_id = tq.get('id') if isinstance(tq, dict) else tq
                    if isinstance(tq_id, int):
                        execute_write(
                            "INSERT OR IGNORE INTO preset_turni_qualitativo "
                            "(preset_turno_id, tipo_qualitativo_id) VALUES (?,?)",
                            (t_real_id, tq_id)
                        )
                        tq_row = query_one("SELECT id, nome FROM tipi_qualitativo WHERE id=?", (tq_id,))
                        if tq_row:
                            tq_out.append({'id': tq_row['id'], 'nome': tq_row['nome']})

                turni_out.append({
                    'id': t_real_id, 'sigla': t_in.get('sigla', ''),
                    'nome': t_in.get('nome', ''), 'ordine': t_ordine * 10,
                    'style': t_in.get('style', {}),
                    'tipi_qualitativi': tq_out,
                    'priorita_solver': t_priorita,
                    'peso_priorita_solver': t_peso,
                    'apri_festivi': t_apri_f,
                    'apri_superfestivi': t_apri_sf,
                })

            ft_row = query_one("SELECT nome FROM flag_turno WHERE id=?", (flag_id,)) if flag_id else None
            flag_nome = ft_row['nome'] if ft_row else ''
            gruppi_out.append({
                'id': g_real_id, 'sigla': g_in.get('sigla', ''), 'nome': g_in.get('nome', ''),
                'flag_id': flag_id, 'flag_nome': flag_nome,
                'ordine': g_ordine * 10, 'style': g_in.get('style', {}), 'turni': turni_out
            })

        struttura_out.append({
            'id': sg_real_id, 'sigla': sg_in.get('sigla', ''), 'nome': sg_in.get('nome', ''),
            'ambito': sg_in.get('ambito', ''),
            'escluso_solver': int(bool(sg_in.get('escluso_solver', 0))),
            'ordine': sg_ordine * 10,
            'style': sg_in.get('style', {}), 'gruppi': gruppi_out
        })

    # Elimina entità rimosse (in ordine foglie → radice)
    for t_id in t_db_ids - t_ids_visti:
        execute_write("DELETE FROM preset_turni WHERE id=?", (t_id,))
    for g_id in g_db_ids - g_ids_visti:
        execute_write("DELETE FROM preset_turni WHERE gruppo_id=?", (g_id,))
        execute_write("DELETE FROM gruppi WHERE id=?", (g_id,))
    for sg_id in sg_db_ids - sg_ids_visti:
        execute_write("DELETE FROM sovragruppi WHERE id=?", (sg_id,))


    return jsonify({'ok': True, 'struttura': struttura_out}), 200


# =============================================================================
# STILE PRESET — salvataggio singolo + undo
# =============================================================================

@bp.route('/struttura-presets/<int:pid>/style-item', methods=['PUT'])
@require_role('admin')
def salva_style_item(pid):
    from app.services.style_history import push_style_history

    preset = query_one("SELECT id FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    items = dati.get('items', [])

    for item in items:
        tipo = item.get('tipo')
        item_id = item.get('id')
        style_after = json.dumps(item.get('style_after', {}))

        if tipo == 'sg':
            execute_write("UPDATE sovragruppi SET style=? WHERE id=?", (style_after, item_id))
        elif tipo == 'gruppo':
            execute_write("UPDATE gruppi SET style=? WHERE id=?", (style_after, item_id))
        elif tipo == 'turno':
            execute_write("UPDATE preset_turni SET style=? WHERE id=?", (style_after, item_id))

    undo_count = push_style_history('preset', pid, items)
    return jsonify({'ok': True, 'undo_count': undo_count}), 200


@bp.route('/struttura-presets/<int:pid>/style-undo', methods=['POST'])
@require_role('admin')
def undo_style_preset(pid):
    from app.services.style_history import pop_style_history, count_style_history

    preset = query_one("SELECT id FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    items = pop_style_history('preset', pid)
    if items is None:
        return jsonify({'ok': False, 'errore': 'Nessuna operazione da annullare.'}), 404

    for item in items:
        tipo = item.get('tipo')
        item_id = item.get('id')
        style_before = json.dumps(item.get('style_before', {}))

        if tipo == 'sg':
            execute_write("UPDATE sovragruppi SET style=? WHERE id=?", (style_before, item_id))
        elif tipo == 'gruppo':
            execute_write("UPDATE gruppi SET style=? WHERE id=?", (style_before, item_id))
        elif tipo == 'turno':
            execute_write("UPDATE preset_turni SET style=? WHERE id=?", (style_before, item_id))

    undo_count = count_style_history('preset', pid)
    return jsonify({'ok': True, 'undo_count': undo_count, 'items': items}), 200


# =============================================================================
# TOGGLE DISABLE/HIDE TURNI NEL PRESET
# =============================================================================

@bp.route('/struttura-presets/<int:pid>/turni/<int:tid>/toggle', methods=['PUT'])
@require_role('admin', 'manager')
def toggle_turno_stato(pid, tid):
    """
    Feature: disattiva/nasconde un turno nel preset.
    Body: { campo: 'is_disabled'|'is_hidden', valore: 0|1 }
    Un turno nascosto (is_hidden=1) implica disattivato (is_disabled=1).
    """
    turno = query_one(
        "SELECT pt.id, pt.is_disabled, pt.is_hidden "
        "FROM preset_turni pt "
        "JOIN gruppi g ON pt.gruppo_id = g.id "
        "JOIN sovragruppi sg ON g.sovragruppo_id = sg.id "
        "WHERE pt.id=? AND sg.preset_id=?",
        (tid, pid)
    )
    if not turno:
        return jsonify({'ok': False, 'errore': 'Turno non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    campo = dati.get('campo')
    valore = int(bool(dati.get('valore', 0)))

    if campo not in ('is_disabled', 'is_hidden'):
        return jsonify({'ok': False, 'errore': 'Campo non valido.'}), 400

    # is_hidden=1 implica is_disabled=1
    if campo == 'is_hidden' and valore == 1:
        execute_write(
            "UPDATE preset_turni SET is_hidden=1, is_disabled=1 WHERE id=?",
            (tid,)
        )
    # Disattivare is_disabled con is_hidden=1 toglie anche hidden
    elif campo == 'is_disabled' and valore == 0:
        execute_write(
            "UPDATE preset_turni SET is_disabled=0, is_hidden=0 WHERE id=?",
            (tid,)
        )
    else:
        execute_write(
            f"UPDATE preset_turni SET {campo}=? WHERE id=?",
            (valore, tid)
        )

    updated = query_one(
        "SELECT is_disabled, is_hidden FROM preset_turni WHERE id=?", (tid,)
    )
    return jsonify({
        'ok': True,
        'is_disabled': updated['is_disabled'],
        'is_hidden': updated['is_hidden']
    }), 200


# =============================================================================
# ESCLUSIONI TURNO PER PRESET
# =============================================================================

@bp.route('/struttura-presets/<int:pid>/esclusioni-turno', methods=['GET'])
@require_role('admin', 'manager')
def lista_esclusioni_turno(pid):
    """Ritorna tutte le esclusioni turno per un preset (usato nell'editor struttura)."""
    preset = query_one("SELECT id FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    rows = query_all(
        "SELECT id, user_id, tipo, target_id, eccezioni "
        "FROM preset_esclusioni_turno_per_utente "
        "WHERE preset_id=? ORDER BY user_id, tipo, target_id",
        (pid,)
    )
    risultato = []
    for r in rows:
        d = dict(r)
        try:
            d['eccezioni'] = json.loads(d['eccezioni'] or '[]')
        except (json.JSONDecodeError, TypeError):
            d['eccezioni'] = []
        risultato.append(d)
    return jsonify({'ok': True, 'esclusioni': risultato}), 200


@bp.route('/struttura-presets/<int:pid>/esclusioni-turno', methods=['POST'])
@require_role('admin', 'manager')
def aggiungi_esclusione_turno(pid):
    """Aggiunge una esclusione turno per un utente in un preset."""
    preset = query_one("SELECT id FROM struttura_presets WHERE id=?", (pid,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    user_id   = dati.get('user_id')
    tipo      = dati.get('tipo')
    target_id = dati.get('target_id')

    if not user_id or tipo not in ('turno', 'gruppo', 'sovragruppo') or not target_id:
        return jsonify({'ok': False, 'errore': 'Parametri non validi.'}), 400

    try:
        cur = execute_write(
            "INSERT OR IGNORE INTO preset_esclusioni_turno_per_utente "
            "(preset_id, user_id, tipo, target_id) VALUES (?,?,?,?)",
            (pid, user_id, tipo, target_id)
        )
        row = query_one(
            "SELECT id FROM preset_esclusioni_turno_per_utente "
            "WHERE preset_id=? AND user_id=? AND tipo=? AND target_id=?",
            (pid, user_id, tipo, target_id)
        )
        return jsonify({'ok': True, 'id': row['id']}), 201
    except Exception as exc:
        return jsonify({'ok': False, 'errore': str(exc)}), 500


@bp.route('/struttura-presets/<int:pid>/esclusioni-turno/<int:esc_id>', methods=['PUT'])
@require_role('admin', 'manager')
def aggiorna_eccezioni_esclusione(pid, esc_id):
    """Aggiorna le eccezioni (figli esenti) di una esclusione turno."""
    row = query_one(
        "SELECT id FROM preset_esclusioni_turno_per_utente WHERE id=? AND preset_id=?",
        (esc_id, pid)
    )
    if not row:
        return jsonify({'ok': False, 'errore': 'Esclusione non trovata.'}), 404

    dati = request.get_json(silent=True) or {}
    eccezioni = dati.get('eccezioni', [])
    valide = [e for e in eccezioni if isinstance(e, int)]
    execute_write(
        "UPDATE preset_esclusioni_turno_per_utente SET eccezioni=? WHERE id=?",
        (json.dumps(valide), esc_id)
    )
    return jsonify({'ok': True}), 200


@bp.route('/struttura-presets/<int:pid>/esclusioni-turno/<int:esc_id>', methods=['DELETE'])
@require_role('admin', 'manager')
def elimina_esclusione_turno(pid, esc_id):
    """Rimuove una singola esclusione turno da un preset."""
    row = query_one(
        "SELECT id FROM preset_esclusioni_turno_per_utente WHERE id=? AND preset_id=?",
        (esc_id, pid)
    )
    if not row:
        return jsonify({'ok': False, 'errore': 'Esclusione non trovata.'}), 404

    execute_write(
        "DELETE FROM preset_esclusioni_turno_per_utente WHERE id=?",
        (esc_id,)
    )
    return jsonify({'ok': True}), 200


# =============================================================================
# GRUPPI (tutti i preset)
# =============================================================================

@bp.route('/gruppi', methods=['GET'])
@require_role('admin', 'manager')
def lista_gruppi():
    gruppi = query_all(
        "SELECT g.id, g.sigla, g.nome, ft.nome AS flag_nome, sp.nome AS preset_nome "
        "FROM gruppi g "
        "JOIN sovragruppi sg ON g.sovragruppo_id=sg.id "
        "JOIN struttura_presets sp ON sg.preset_id=sp.id "
        "LEFT JOIN flag_turno ft ON g.flag_id=ft.id "
        "ORDER BY sp.nome, g.nome",
        ()
    )
    return jsonify({'ok': True, 'gruppi': gruppi}), 200


# =============================================================================
# REGOLE CONFLITTO (globali)
# =============================================================================

@bp.route('/regole-conflitto', methods=['GET'])
@require_role('admin', 'manager')
def lista_regole_conflitto():
    regole = query_all(
        "SELECT rc.*, fa.nome AS flag_a_nome, fb.nome AS flag_b_nome "
        "FROM regole_conflitto rc "
        "LEFT JOIN flag_turno fa ON rc.flag_a_id=fa.id "
        "LEFT JOIN flag_turno fb ON rc.flag_b_id=fb.id "
        "ORDER BY rc.id",
        ()
    )
    return jsonify({'ok': True, 'regole': regole}), 200


@bp.route('/regole-conflitto', methods=['POST'])
@require_role('admin')
def crea_regola_conflitto():
    dati = request.get_json(silent=True) or {}
    nome       = (dati.get('nome') or '').strip()
    tipo_regola = (dati.get('tipo_regola') or '').strip()

    if not nome:
        return jsonify({'ok': False, 'errore': 'Nome obbligatorio.'}), 400
    if tipo_regola not in TIPI_REGOLA:
        return jsonify({'ok': False, 'errore': 'tipo_regola non valido.'}), 400

    categoria = (dati.get('categoria') or 'consigliata').strip()
    stile = dati.get('stile', '{"backgroundColor":"#fff3cd","color":"#856404"}')
    if isinstance(stile, dict):
        stile = json.dumps(stile)

    cur = execute_write(
        """INSERT INTO regole_conflitto
           (nome, tipo_regola, flag_a_id, flag_b_id,
            offset_giorni, categoria, stile, blocca_inserimento, peso_numerico)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (nome, tipo_regola,
         dati.get('flag_a_id'), dati.get('flag_b_id'),
         int(dati.get('offset_giorni', 0)),
         categoria, stile,
         int(bool(dati.get('blocca_inserimento', False))),
         float(dati.get('peso_numerico', 1.0)))
    )
    return jsonify({'ok': True, 'id': cur.lastrowid}), 201


@bp.route('/regole-conflitto/<int:rid>', methods=['PUT'])
@require_role('admin')
def modifica_regola_conflitto(rid):
    r = query_one("SELECT * FROM regole_conflitto WHERE id=?", (rid,))
    if not r:
        return jsonify({'ok': False, 'errore': 'Regola non trovata.'}), 404
    dati = request.get_json(silent=True) or {}
    stile = dati.get('stile', r.get('stile', '{}'))
    if isinstance(stile, dict):
        stile = json.dumps(stile)
    try:
        execute_write(
            """UPDATE regole_conflitto SET
               nome=?, tipo_regola=?, flag_a_id=?, flag_b_id=?,
               offset_giorni=?, categoria=?, stile=?, blocca_inserimento=?,
               peso_numerico=?, is_active=?
               WHERE id=?""",
            (
                dati.get('nome', r['nome']),
                dati.get('tipo_regola', r['tipo_regola']),
                dati.get('flag_a_id', r.get('flag_a_id')),
                dati.get('flag_b_id', r.get('flag_b_id')),
                int(dati.get('offset_giorni', r['offset_giorni'])),
                dati.get('categoria', r.get('categoria', 'consigliata')),
                stile,
                int(bool(dati.get('blocca_inserimento', r['blocca_inserimento']))),
                float(dati.get('peso_numerico', r['peso_numerico'])),
                int(bool(dati.get('is_active', r['is_active']))),
                rid
            )
        )
    except Exception as e:
        return jsonify({'ok': False, 'errore': f'Errore DB: {e}'}), 400
    return jsonify({'ok': True, 'messaggio': 'Regola aggiornata.'}), 200


@bp.route('/regole-conflitto/<int:rid>', methods=['DELETE'])
@require_role('admin')
def elimina_regola_conflitto(rid):
    execute_write("DELETE FROM regole_conflitto WHERE id=?", (rid,))
    return jsonify({'ok': True, 'messaggio': 'Regola eliminata.'}), 200


# =============================================================================
# TIPI RICHIESTA (globali)
# =============================================================================

@bp.route('/tipi-richiesta', methods=['GET'])
@require_role('admin', 'manager', 'basic')
def lista_tipi_richiesta():
    tipi = query_all(
        "SELECT tr.id, tr.sigla, tr.descrizione, tr.tipo, tr.counting_flag, "
        "tr.ore_default, tr.ordine, tr.flag_id, "
        "ft.nome AS flag_nome "
        "FROM tipi_richiesta tr "
        "LEFT JOIN flag_turno ft ON tr.flag_id = ft.id "
        "ORDER BY tr.tipo, tr.ordine",
        ()
    )
    return jsonify({'ok': True, 'tipi': tipi}), 200


@bp.route('/tipi-richiesta', methods=['POST'])
@require_role('admin')
def crea_tipo_richiesta():
    dati = request.get_json(silent=True) or {}
    sigla  = (dati.get('sigla') or '').strip().upper()
    descr  = (dati.get('descrizione') or '').strip()
    tipo   = (dati.get('tipo') or '').strip()
    cflag  = int(bool(dati.get('counting_flag', True)))
    ore    = dati.get('ore_default')
    ordine = int(dati.get('ordine', 0))
    flag_id = dati.get('flag_id')

    if not sigla or not descr or tipo not in ('lavorativo', 'assenza'):
        return jsonify({'ok': False, 'errore': 'Dati non validi.'}), 400

    cur = execute_write(
        "INSERT INTO tipi_richiesta "
        "(sigla,descrizione,tipo,counting_flag,ore_default,ordine,flag_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (sigla, descr, tipo, cflag, ore, ordine, flag_id)
    )
    return jsonify({'ok': True, 'id': cur.lastrowid}), 201


@bp.route('/tipi-richiesta/<int:tid>', methods=['PUT'])
@require_role('admin')
def modifica_tipo_richiesta(tid):
    tr = query_one("SELECT * FROM tipi_richiesta WHERE id=?", (tid,))
    if not tr:
        return jsonify({'ok': False, 'errore': 'Tipo richiesta non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    execute_write(
        "UPDATE tipi_richiesta SET sigla=?,descrizione=?,counting_flag=?,ore_default=?,ordine=?,flag_id=? "
        "WHERE id=?",
        (
            dati.get('sigla', tr['sigla']),
            dati.get('descrizione', tr['descrizione']),
            int(bool(dati.get('counting_flag', tr['counting_flag']))),
            dati.get('ore_default', tr['ore_default']),
            int(dati.get('ordine', tr['ordine'])),
            dati.get('flag_id', tr.get('flag_id')),
            tid
        )
    )
    return jsonify({'ok': True, 'messaggio': 'Tipo richiesta aggiornato.'}), 200


@bp.route('/tipi-richiesta/<int:tid>', methods=['DELETE'])
@require_role('admin')
def elimina_tipo_richiesta(tid):
    des_dip = query_all(
        "SELECT DISTINCT c.mese, c.anno "
        "FROM desiderata d "
        "JOIN calendari c ON d.calendario_id = c.id "
        "WHERE d.tipo_richiesta_id = ? AND c.stato = 'APERTO'",
        (tid,)
    )
    wd_dip = query_all(
        "SELECT DISTINCT c.mese, c.anno "
        "FROM working_desiderata wd "
        "JOIN calendari c ON wd.calendario_id = c.id "
        "WHERE wd.tipo_richiesta_id = ? AND c.stato = 'APERTO'",
        (tid,)
    )

    nomi_mesi = ['', 'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio',
                 'Giugno', 'Luglio', 'Agosto', 'Settembre', 'Ottobre',
                 'Novembre', 'Dicembre']
    calendari_set = set()
    for r in des_dip + wd_dip:
        calendari_set.add(f"{nomi_mesi[r['mese']]} {r['anno']}")

    if calendari_set:
        dettagli = [f"Calendario {c}" for c in sorted(calendari_set)]
        return jsonify({
            'ok': False,
            'errore': 'Impossibile eliminare: tipo in uso in calendari aperti.',
            'dipendenze': dettagli
        }), 409

    execute_write("DELETE FROM tipi_richiesta WHERE id=?", (tid,))
    return jsonify({'ok': True, 'messaggio': 'Tipo richiesta eliminato.'}), 200


# =============================================================================
# CALENDARI
# =============================================================================

@bp.route('/calendari', methods=['GET'])
@require_role('admin', 'manager')
def lista_calendari():
    calendari = query_all(
        "SELECT id, mese, anno, stato, ore_giornaliere_default, "
        "deadline_globale, desiderata_congelati, versione, tipo, parent_id, chiuso_il, created_at "
        "FROM calendari ORDER BY anno DESC, mese DESC, versione DESC"
    )
    return jsonify({'ok': True, 'calendari': calendari}), 200


@bp.route('/calendari', methods=['POST'])
@require_role('admin', 'manager')
def crea_calendario():
    """
    Crea un nuovo calendario.
    Manager: richiede puo_gestire_calendari=1. Admin: sempre consentito.
    """
    me = get_current_user()
    if me['role'] == 'manager' and not me.get('puo_gestire_calendari'):
        return jsonify({'ok': False, 'errore': 'Non autorizzato a creare calendari.'}), 403

    dati = request.get_json(silent=True) or {}
    mese      = dati.get('mese')
    anno      = dati.get('anno')
    deadline  = dati.get('deadline_globale')

    # Ore giornaliere default dal config globale
    cfg_ore = query_one("SELECT valore FROM config WHERE chiave = 'ore_giornaliere'")
    ore = float(cfg_ore['valore']) if cfg_ore else 6.5
    preset_id = dati.get('preset_id')

    if not mese or not anno:
        return jsonify({'ok': False, 'errore': 'Mese e anno sono obbligatori.'}), 400
    if not (1 <= int(mese) <= 12):
        return jsonify({'ok': False, 'errore': 'Mese non valido.'}), 400

    esistente = query_one(
        "SELECT id FROM calendari WHERE mese=? AND anno=? AND tipo='programmato'",
        (mese, anno))
    if esistente:
        return jsonify({'ok': False, 'errore': f'Calendario {mese}/{anno} già esistente.'}), 409

    # Il tenant ha una struttura sola: non si chiede quale usare.
    if not preset_id:
        preset_id = _struttura_del_tenant()

    if not preset_id:
        return jsonify({
            'ok': False,
            'errore': 'Questa organizzazione non ha ancora una struttura turni: '
                      'creala dalla configurazione, poi torna qui.'
        }), 400

    # Snapshot delle regole conflitto attive al momento della creazione
    from app.services.validatori import snapshot_regole
    regole_json = snapshot_regole()

    # Snapshot completo configurazione (vincoli, accesso, flag, ecc.)
    from app.services.config_snapshot import crea_config_snapshot, APPEARANCE_DEFAULT
    config_json = crea_config_snapshot(preset_id=preset_id)

    # Snapshot appearance (estratto dalla config, salvato anche in colonna dedicata)
    if preset_id:
        app_row = query_one("SELECT appearance FROM struttura_presets WHERE id=?", (preset_id,))
        try:
            app_data = json.loads(app_row['appearance']) if app_row and app_row['appearance'] else {}
        except (json.JSONDecodeError, TypeError):
            app_data = {}
        appearance_json = json.dumps({**APPEARANCE_DEFAULT, **app_data})
    else:
        appearance_json = json.dumps(APPEARANCE_DEFAULT)

    cur = execute_write(
        "INSERT INTO calendari "
        "(mese, anno, stato, ore_giornaliere_default, deadline_globale, preset_id, "
        " regole_snapshot, config_snapshot, appearance_snapshot, created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (int(mese), int(anno), 'APERTO', ore, deadline, preset_id,
         regole_json, config_json, appearance_json, me['id'])
    )
    cal_id = cur.lastrowid

    # Aggiorna last_used_at sul preset
    if preset_id:
        execute_write(
            "UPDATE struttura_presets SET last_used_at=datetime('now') WHERE id=?",
            (preset_id,)
        )

    # Popola calendario_turni dalle tabelle normalizzate
    if preset_id:
        ordine = 0
        sgs = query_all(
            "SELECT id, sigla, nome, ambito, ordine, style FROM sovragruppi "
            "WHERE preset_id=? ORDER BY ordine",
            (preset_id,)
        )
        for sg in sgs:
            sg_style = sg.get('style', '{}')
            gruppi = query_all(
                "SELECT g.id, g.sigla, g.nome, g.ordine, g.style, "
                "g.flag_id, ft.nome AS flag_nome, "
                "ft.peso_turno, ft.ore_turno, ft.ore_primo_giorno, ft.ore_ultimo_giorno "
                "FROM gruppi g LEFT JOIN flag_turno ft ON g.flag_id=ft.id "
                "WHERE g.sovragruppo_id=? ORDER BY g.ordine",
                (sg['id'],)
            )
            for g in gruppi:
                flag_nome = g.get('flag_nome') or ''
                gruppo_style = g.get('style', '{}')
                turni = query_all(
                    "SELECT id, sigla, nome, ordine, style, priorita_solver, peso_priorita_solver, "
                    "       apri_festivi, apri_superfestivi, is_disabled, is_hidden "
                    "FROM preset_turni "
                    "WHERE gruppo_id=? ORDER BY ordine",
                    (g['id'],)
                )
                for t in turni:
                    ordine += 10
                    tq_rows = query_all(
                        "SELECT tq.id, tq.nome FROM tipi_qualitativo tq "
                        "JOIN preset_turni_qualitativo ptq ON tq.id = ptq.tipo_qualitativo_id "
                        "WHERE ptq.preset_turno_id = ?",
                        (t['id'],)
                    )
                    tipi_qual_json = json.dumps([{'id': r['id'], 'nome': r['nome']} for r in tq_rows]) if tq_rows else '[]'
                    turno_style = t.get('style', '{}')
                    execute_write(
                        "INSERT OR IGNORE INTO calendario_turni "
                        "(calendario_id, local_id, sigla, nome, flag_nome, flag_id, "
                        " tipi_qualitativi, "
                        " gruppo_id, gruppo_sigla, gruppo_nome, gruppo_ordine, "
                        " sg_id, sg_sigla, sg_nome, sg_ambito, sg_ordine, sg_style, "
                        " ordine, style, turno_style, "
                        " peso_turno, ore_turno, ore_primo_giorno, ore_ultimo_giorno, "
                        " priorita_solver, peso_priorita_solver, "
                        " apri_festivi, apri_superfestivi, "
                        " is_disabled, is_hidden) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (cal_id, t['id'], t['sigla'], t.get('nome', t['sigla']),
                         flag_nome, g.get('flag_id'),
                         tipi_qual_json, g['id'], g['sigla'], g['nome'], g['ordine'],
                         sg['id'], sg['sigla'], sg['nome'], sg['ambito'], sg['ordine'], sg_style,
                         ordine, gruppo_style, turno_style,
                         g['peso_turno'] or 1, g['ore_turno'],
                         g['ore_primo_giorno'], g['ore_ultimo_giorno'],
                         t.get('priorita_solver', 'automatico'), t.get('peso_priorita_solver', 50),
                         t.get('apri_festivi', 0), t.get('apri_superfestivi', 0),
                         t.get('is_disabled', 0), t.get('is_hidden', 0))
                    )

    # Inizializza i giorni del mese
    import calendar as cal_lib
    festivita = _calcola_festivita(int(anno))
    num_giorni = cal_lib.monthrange(int(anno), int(mese))[1]

    # Quali giorni della settimana il reparto lavora, e se i festivi contano.
    config = {r['chiave']: r['valore'] for r in query_all(
        "SELECT chiave, valore FROM config", ()
    )}
    giorni_lavorativi = leggi_giorni_lavorativi(config)

    for g in range(1, num_giorni + 1):
        import datetime
        data = datetime.date(int(anno), int(mese), g)
        tipo, lavorativo = classifica_giorno(data, festivita, giorni_lavorativi)
        lav = int(lavorativo)

        execute_write(
            "INSERT INTO giorni_calendario (calendario_id, giorno, is_lavorativo, tipo) "
            "VALUES (?,?,?,?)",
            (cal_id, g, lav, tipo)
        )

    return jsonify({
        'ok': True,
        'id': cal_id,
        'messaggio': f'Calendario {mese}/{anno} creato con {num_giorni} giorni.'
    }), 201


@bp.route('/calendari/<int:cal_id>', methods=['PUT'])
@require_role('admin', 'manager')
def modifica_calendario(cal_id):
    cal = query_one("SELECT * FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    execute_write(
        "UPDATE calendari SET ore_giornaliere_default=?, deadline_globale=? WHERE id=?",
        (
            float(dati.get('ore_giornaliere_default', cal['ore_giornaliere_default'])),
            dati.get('deadline_globale', cal['deadline_globale']),
            cal_id
        )
    )
    return jsonify({'ok': True, 'messaggio': 'Calendario aggiornato.'}), 200


@bp.route('/calendari/<int:cal_id>/stato', methods=['POST'])
@require_role('admin', 'manager')
def cambia_stato_calendario(cal_id):
    """Transizione stato calendario: APERTO→CHIUSO oppure riapertura CHIUSO→APERTO.

    Chiusura: history NON cancellata (resta disponibile per undo dopo riapertura).
    Riapertura: l'EFFETTIVO viene eliminato (con la sua history).
    """
    from datetime import datetime
    from app.services.effettivo import crea_copia_effettivo

    cal = query_one("SELECT * FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    nuovo_stato = (dati.get('stato') or '').strip().upper()

    # APERTO → CHIUSO (chiusura)
    if cal['stato'] == 'APERTO' and nuovo_stato == 'CHIUSO':
        now = datetime.utcnow().isoformat()
        nuova_versione = cal['versione'] + 1

        execute_write(
            "UPDATE calendari SET stato='CHIUSO', chiuso_il=?, versione=? WHERE id=?",
            (now, nuova_versione, cal_id))

        execute_write(
            "INSERT INTO versioni_calendario (calendario_id, versione, chiuso_il) VALUES (?,?,?)",
            (cal_id, nuova_versione, now))

        eff_id = crea_copia_effettivo(cal_id)

        return jsonify({
            'ok': True,
            'messaggio': f'Calendario chiuso (v{nuova_versione}). Effettivo creato.',
            'effettivo_id': eff_id,
            'versione': nuova_versione
        }), 200

    # CHIUSO → APERTO (riapertura)
    if cal['stato'] == 'CHIUSO' and nuovo_stato == 'APERTO':
        # Verifica che l'EFFETTIVO non sia già chiuso
        effettivo = query_one(
            "SELECT id, stato FROM calendari WHERE parent_id=? AND tipo='effettivo'",
            (cal_id,))
        if effettivo and effettivo['stato'] == 'CHIUSO':
            return jsonify({
                'ok': False,
                'errore': "Non è possibile riaprire: l'effettivo è già stato chiuso."
            }), 400

        # Elimina EFFETTIVO e la sua history.
        # CASCADE copre history/wd_history/history_ptr/wd_history_ptr e tutto il resto;
        # style_history non ha FK -> pulizia esplicita.
        if effettivo:
            execute_write(
                "DELETE FROM style_history WHERE contesto='calendario' AND contesto_id=?",
                (effettivo['id'],))
            execute_write("DELETE FROM calendari WHERE id=?", (effettivo['id'],))

        # Riapri (history del calendario principale preservata)
        now = datetime.utcnow().isoformat()
        execute_write(
            "UPDATE calendari SET stato='APERTO', chiuso_il=NULL WHERE id=?",
            (cal_id,))
        execute_write(
            "UPDATE versioni_calendario SET riaperto_il=? "
            "WHERE calendario_id=? AND versione=? AND riaperto_il IS NULL",
            (now, cal_id, cal['versione']))

        return jsonify({
            'ok': True,
            'messaggio': f'Calendario riaperto. Effettivo (v{cal["versione"]}) eliminato.'
        }), 200

    return jsonify({
        'ok': False,
        'errore': f'Transizione non valida: {cal["stato"]} → {nuovo_stato}'
    }), 400


@bp.route('/calendari/<int:cal_id>/chiudi-effettivo', methods=['POST'])
@require_role('admin', 'manager')
def chiudi_effettivo(cal_id):
    """Chiude un calendario EFFETTIVO (APERTO → CHIUSO).

    History dell'effettivo preservata: le scritture sono comunque bloccate dalle
    guard di route, ma i record di history restano in caso di riapertura.
    """
    from datetime import datetime

    cal = query_one("SELECT * FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404
    if cal['tipo'] != 'effettivo':
        return jsonify({'ok': False, 'errore': 'Non è un calendario effettivo.'}), 400
    if cal['stato'] != 'APERTO':
        return jsonify({'ok': False, 'errore': 'Effettivo non è aperto.'}), 400

    now = datetime.utcnow().isoformat()
    execute_write(
        "UPDATE calendari SET stato='CHIUSO', chiuso_il=? WHERE id=?",
        (now, cal_id))

    return jsonify({'ok': True, 'messaggio': 'Effettivo chiuso.'}), 200


@bp.route('/calendari/<int:cal_id>/riapri-effettivo', methods=['POST'])
@require_role('admin', 'manager')
def riapri_effettivo(cal_id):
    """Riapre un calendario EFFETTIVO (CHIUSO → APERTO)."""
    cal = query_one("SELECT * FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404
    if cal['tipo'] != 'effettivo':
        return jsonify({'ok': False, 'errore': 'Non è un calendario effettivo.'}), 400
    if cal['stato'] != 'CHIUSO':
        return jsonify({'ok': False, 'errore': 'Effettivo non è chiuso.'}), 400

    execute_write(
        "UPDATE calendari SET stato='APERTO', chiuso_il=NULL WHERE id=?",
        (cal_id,))
    return jsonify({'ok': True, 'messaggio': 'Effettivo riaperto.'}), 200


@bp.route('/calendari/<int:cal_id>/congela', methods=['POST'])
@require_role('admin', 'manager')
def congela_desiderata(cal_id):
    cal = query_one("SELECT id FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    me = get_current_user()

    execute_write(
        "DELETE FROM working_desiderata WHERE calendario_id=?", (cal_id,)
    )
    execute_write(
        """
        INSERT INTO working_desiderata
            (calendario_id, user_id, giorno, tipo_richiesta_id, note, updated_by)
        SELECT calendario_id, user_id, giorno, tipo_richiesta_id, note, ?
        FROM desiderata
        WHERE calendario_id = ?
        """,
        (me['id'], cal_id)
    )
    execute_write(
        "UPDATE calendari SET desiderata_congelati=1 WHERE id=?", (cal_id,)
    )

    return jsonify({'ok': True, 'messaggio': 'Desiderata congelati e working desiderata aggiornati.'}), 200


@bp.route('/calendari/<int:cal_id>/scongela', methods=['POST'])
@require_role('admin')
def scongela_desiderata(cal_id):
    cal = query_one("SELECT id, desiderata_congelati FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404
    if not cal['desiderata_congelati']:
        return jsonify({'ok': False, 'errore': 'I desiderata non sono congelati.'}), 400

    execute_write(
        "DELETE FROM working_desiderata WHERE calendario_id=?", (cal_id,)
    )
    execute_write(
        "UPDATE calendari SET desiderata_congelati=0 WHERE id=?", (cal_id,)
    )

    return jsonify({'ok': True, 'messaggio': 'Desiderata scongelati. Working desiderata eliminati.'}), 200


@bp.route('/calendari/<int:cal_id>', methods=['DELETE'])
@require_role('admin', 'manager')
def elimina_calendario(cal_id):
    """
    Elimina un calendario.
    Manager: richiede puo_gestire_calendari=1. Admin: sempre consentito.
    """
    me = get_current_user()
    if me['role'] == 'manager' and not me.get('puo_gestire_calendari'):
        return jsonify({'ok': False, 'errore': 'Non autorizzato a eliminare calendari.'}), 403

    cal = query_one("SELECT id, mese, anno FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    execute_write("DELETE FROM calendari WHERE id=?", (cal_id,))
    return jsonify({
        'ok': True,
        'messaggio': f'Calendario {cal["mese"]}/{cal["anno"]} eliminato.'
    }), 200


@bp.route('/calendari/<int:cal_id>/riazzera', methods=['POST'])
@require_role('admin')
def riazzera_calendario(cal_id):
    cal = query_one("SELECT id, mese, anno FROM calendari WHERE id=?", (cal_id,))
    if not cal:
        return jsonify({'ok': False, 'errore': 'Calendario non trovato.'}), 404

    execute_write("DELETE FROM assegnazioni_turni WHERE calendario_id=?", (cal_id,))
    execute_write("DELETE FROM history WHERE calendario_id=?", (cal_id,))
    execute_write("DELETE FROM history_ptr WHERE calendario_id=?", (cal_id,))
    execute_write("UPDATE calendari SET stato='APERTO' WHERE id=?", (cal_id,))

    return jsonify({
        'ok': True,
        'messaggio': f'Calendario {cal["mese"]}/{cal["anno"]} riazzerato.'
    }), 200


@bp.route('/calendari/<int:cal_id>/ricarica-struttura', methods=['POST'])
@require_role('admin')
def ricarica_struttura(cal_id):
    """
    Ricarica la struttura turni di un calendario da un preset.

    Modalità (campo 'mode'):
      - 'preview': restituisce differenze senza applicarle
      - 'apply':   applica le modifiche

    Logica:
      - Confronta calendario_turni.local_id con preset_turni.id
      - Turni presenti in entrambi → aggiorna metadati (sigla, nome, stile, flag, ordine, ore...)
      - Turni solo nel preset → aggiunge (nuovi)
      - Turni solo nel calendario → rimuove (CASCADE elimina assegnazioni)
      - History: pulisce step orfani + resetta puntatore
    """
    cal = ottieni_calendario_aperto(
        cal_id, "id, mese, anno, stato, preset_id")

    dati = request.get_json(silent=True) or {}
    mode = dati.get('mode', 'preview')
    preset_id = dati.get('preset_id', cal['preset_id'])

    if not preset_id:
        return jsonify({'ok': False, 'errore': 'Nessun preset specificato.'}), 400

    preset = query_one("SELECT id, nome FROM struttura_presets WHERE id=?", (preset_id,))
    if not preset:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    # --- Raccogli turni correnti nel calendario ---
    ct_rows = query_all(
        "SELECT id, local_id FROM calendario_turni WHERE calendario_id=?",
        (cal_id,)
    )
    ct_by_local = {str(r['local_id']): r['id'] for r in ct_rows}  # local_id → ct.id

    # --- Raccogli turni dal preset (stessa logica di crea_calendario) ---
    preset_turni_map = {}  # preset_turno.id → dict con tutti i campi snapshot
    ordine = 0
    sgs = query_all(
        "SELECT id, sigla, nome, ambito, ordine, style FROM sovragruppi "
        "WHERE preset_id=? ORDER BY ordine",
        (preset_id,)
    )
    for sg in sgs:
        sg_style = sg.get('style', '{}')
        gruppi = query_all(
            "SELECT g.id, g.sigla, g.nome, g.ordine, g.style, "
            "g.flag_id, ft.nome AS flag_nome, "
            "ft.peso_turno, ft.ore_turno, ft.ore_primo_giorno, ft.ore_ultimo_giorno "
            "FROM gruppi g LEFT JOIN flag_turno ft ON g.flag_id=ft.id "
            "WHERE g.sovragruppo_id=? ORDER BY g.ordine",
            (sg['id'],)
        )
        for g in gruppi:
            flag_nome = g.get('flag_nome') or ''
            gruppo_style = g.get('style', '{}')
            turni = query_all(
                "SELECT id, sigla, nome, ordine, style, priorita_solver, peso_priorita_solver, "
                "       apri_festivi, apri_superfestivi, is_disabled, is_hidden "
                "FROM preset_turni "
                "WHERE gruppo_id=? ORDER BY ordine",
                (g['id'],)
            )
            for t in turni:
                ordine += 10
                tq_rows = query_all(
                    "SELECT tq.id, tq.nome FROM tipi_qualitativo tq "
                    "JOIN preset_turni_qualitativo ptq ON tq.id = ptq.tipo_qualitativo_id "
                    "WHERE ptq.preset_turno_id = ?",
                    (t['id'],)
                )
                tipi_qual_json = json.dumps(
                    [{'id': r['id'], 'nome': r['nome']} for r in tq_rows]
                ) if tq_rows else '[]'
                turno_style = t.get('style', '{}')

                preset_turni_map[str(t['id'])] = {
                    'local_id': t['id'],
                    'sigla': t['sigla'],
                    'nome': t.get('nome', t['sigla']),
                    'flag_nome': flag_nome,
                    'flag_id': g.get('flag_id'),
                    'tipi_qualitativi': tipi_qual_json,
                    'gruppo_id': g['id'],
                    'gruppo_sigla': g['sigla'],
                    'gruppo_nome': g['nome'],
                    'gruppo_ordine': g['ordine'],
                    'sg_id': sg['id'],
                    'sg_sigla': sg['sigla'],
                    'sg_nome': sg['nome'],
                    'sg_ambito': sg['ambito'],
                    'sg_ordine': sg['ordine'],
                    'sg_style': sg_style,
                    'ordine': ordine,
                    'style': gruppo_style,
                    'turno_style': turno_style,
                    'peso_turno': g.get('peso_turno', 1),
                    'ore_turno': g.get('ore_turno'),
                    'ore_primo_giorno': g.get('ore_primo_giorno'),
                    'ore_ultimo_giorno': g.get('ore_ultimo_giorno'),
                    'priorita_solver': t.get('priorita_solver', 'automatico'),
                    'peso_priorita_solver': t.get('peso_priorita_solver', 50),
                    'apri_festivi': t.get('apri_festivi', 0),
                    'apri_superfestivi': t.get('apri_superfestivi', 0),
                    'is_disabled': t.get('is_disabled', 0),
                    'is_hidden': t.get('is_hidden', 0),
                }

    # --- Calcola differenze ---
    local_ids_cal = set(ct_by_local.keys())
    local_ids_preset = set(preset_turni_map.keys())

    da_aggiungere = local_ids_preset - local_ids_cal
    da_rimuovere = local_ids_cal - local_ids_preset
    da_aggiornare = local_ids_cal & local_ids_preset

    # Conta assegnazioni che verranno perse
    ass_perse = 0
    if da_rimuovere:
        ct_ids_da_rimuovere = [ct_by_local[lid] for lid in da_rimuovere]
        placeholders = ','.join('?' * len(ct_ids_da_rimuovere))
        row = query_one(
            f"SELECT COUNT(*) AS n FROM assegnazioni_turni "
            f"WHERE turno_id IN ({placeholders})",
            ct_ids_da_rimuovere
        )
        ass_perse = row['n'] if row else 0

    diff = {
        'aggiunti': [preset_turni_map[lid]['sigla'] for lid in sorted(da_aggiungere)],
        'rimossi': [],
        'aggiornati': len(da_aggiornare),
        'assegnazioni_perse': ass_perse,
    }
    # Nomi dei turni rimossi
    if da_rimuovere:
        ct_ids_rm = [ct_by_local[lid] for lid in da_rimuovere]
        placeholders = ','.join('?' * len(ct_ids_rm))
        rm_rows = query_all(
            f"SELECT sigla FROM calendario_turni WHERE id IN ({placeholders})",
            ct_ids_rm
        )
        diff['rimossi'] = [r['sigla'] for r in rm_rows]

    if mode == 'preview':
        return jsonify({'ok': True, 'diff': diff}), 200

    # --- Applica ---
    # 1. Rimuovi turni non più nel preset (CASCADE elimina assegnazioni)
    for lid in da_rimuovere:
        execute_write(
            "DELETE FROM calendario_turni WHERE id=?",
            (ct_by_local[lid],)
        )

    # 2. Aggiorna metadati turni esistenti
    for lid in da_aggiornare:
        pt = preset_turni_map[lid]
        execute_write(
            "UPDATE calendario_turni SET "
            "sigla=?, nome=?, flag_nome=?, flag_id=?, tipi_qualitativi=?, "
            "gruppo_id=?, gruppo_sigla=?, gruppo_nome=?, gruppo_ordine=?, "
            "sg_id=?, sg_sigla=?, sg_nome=?, sg_ambito=?, sg_ordine=?, sg_style=?, "
            "ordine=?, style=?, turno_style=?, "
            "peso_turno=?, ore_turno=?, ore_primo_giorno=?, ore_ultimo_giorno=?, "
            "priorita_solver=?, peso_priorita_solver=?, "
            "apri_festivi=?, apri_superfestivi=?, "
            "is_disabled=?, is_hidden=? "
            "WHERE id=?",
            (pt['sigla'], pt['nome'], pt['flag_nome'], pt['flag_id'],
             pt['tipi_qualitativi'],
             pt['gruppo_id'], pt['gruppo_sigla'], pt['gruppo_nome'], pt['gruppo_ordine'],
             pt['sg_id'], pt['sg_sigla'], pt['sg_nome'], pt['sg_ambito'], pt['sg_ordine'],
             pt['sg_style'], pt['ordine'], pt['style'], pt['turno_style'],
             pt['peso_turno'], pt['ore_turno'],
             pt['ore_primo_giorno'], pt['ore_ultimo_giorno'],
             pt.get('priorita_solver', 'automatico'), pt.get('peso_priorita_solver', 50),
             pt.get('apri_festivi', 0), pt.get('apri_superfestivi', 0),
             pt.get('is_disabled', 0), pt.get('is_hidden', 0),
             ct_by_local[lid])
        )

    # 3. Aggiungi nuovi turni dal preset
    for lid in da_aggiungere:
        pt = preset_turni_map[lid]
        execute_write(
            "INSERT INTO calendario_turni "
            "(calendario_id, local_id, sigla, nome, flag_nome, flag_id, "
            " tipi_qualitativi, "
            " gruppo_id, gruppo_sigla, gruppo_nome, gruppo_ordine, "
            " sg_id, sg_sigla, sg_nome, sg_ambito, sg_ordine, sg_style, "
            " ordine, style, turno_style, "
            " peso_turno, ore_turno, ore_primo_giorno, ore_ultimo_giorno, "
            " priorita_solver, peso_priorita_solver, "
            " apri_festivi, apri_superfestivi, "
            " is_disabled, is_hidden) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cal_id, pt['local_id'], pt['sigla'], pt['nome'],
             pt['flag_nome'], pt['flag_id'],
             pt['tipi_qualitativi'],
             pt['gruppo_id'], pt['gruppo_sigla'], pt['gruppo_nome'], pt['gruppo_ordine'],
             pt['sg_id'], pt['sg_sigla'], pt['sg_nome'], pt['sg_ambito'], pt['sg_ordine'],
             pt['sg_style'], pt['ordine'], pt['style'], pt['turno_style'],
             pt['peso_turno'], pt['ore_turno'],
             pt['ore_primo_giorno'], pt['ore_ultimo_giorno'],
             pt.get('priorita_solver', 'automatico'), pt.get('peso_priorita_solver', 50),
             pt.get('apri_festivi', 0), pt.get('apri_superfestivi', 0),
             pt.get('is_disabled', 0), pt.get('is_hidden', 0))
        )

    # 4. Pulizia history — rimuovi step orfani e resetta puntatore
    # Trova tutti i turno_id ancora validi nel calendario
    ct_validi = query_all(
        "SELECT id FROM calendario_turni WHERE calendario_id=?",
        (cal_id,)
    )
    ct_ids_validi = {r['id'] for r in ct_validi}

    # Controlla step history con riferimenti a turni eliminati
    history_rows = query_all(
        "SELECT id, tabella, record_id, dati_precedenti, dati_nuovi "
        "FROM history WHERE calendario_id=? ORDER BY step ASC",
        (cal_id,)
    )

    orfani_ids = []
    for h in history_rows:
        if h['tabella'] == 'swap':
            # Per swap, controlla tutte le sub-operazioni
            try:
                prec = json.loads(h['dati_precedenti'] or '[]')
                nuovi = json.loads(h['dati_nuovi'] or '[]')
                ops = prec + nuovi
                for op in ops:
                    if op.get('tabella') == 'assegnazioni_turni':
                        dati = op.get('dati') or {}
                        turno_id = dati.get('turno_id')
                        if turno_id and turno_id not in ct_ids_validi:
                            orfani_ids.append(h['id'])
                            break
            except (json.JSONDecodeError, TypeError):
                orfani_ids.append(h['id'])
        elif h['tabella'] == 'assegnazioni_turni':
            # Controlla turno_id in dati_precedenti e dati_nuovi
            try:
                prec = json.loads(h['dati_precedenti'] or '{}')
                nuovi = json.loads(h['dati_nuovi'] or '{}')
                turno_id_p = prec.get('turno_id') if isinstance(prec, dict) else None
                turno_id_n = nuovi.get('turno_id') if isinstance(nuovi, dict) else None
                if ((turno_id_p and turno_id_p not in ct_ids_validi) or
                    (turno_id_n and turno_id_n not in ct_ids_validi)):
                    orfani_ids.append(h['id'])
            except (json.JSONDecodeError, TypeError):
                orfani_ids.append(h['id'])

    # Elimina step orfani
    for oid in orfani_ids:
        execute_write("DELETE FROM history WHERE id=?", (oid,))

    # Riscala step rimanenti e resetta puntatore
    remaining = query_all(
        "SELECT id FROM history WHERE calendario_id=? ORDER BY step ASC",
        (cal_id,)
    )
    for i, row in enumerate(remaining, start=1):
        execute_write("UPDATE history SET step=? WHERE id=?", (i, row['id']))

    new_max = len(remaining)
    execute_write(
        "INSERT INTO history_ptr (calendario_id, current_step, max_step) "
        "VALUES (?,?,?) ON CONFLICT(calendario_id) DO UPDATE SET "
        "current_step=excluded.current_step, max_step=excluded.max_step",
        (cal_id, new_max, new_max)
    )

    # Aggiorna preset_id nel calendario se cambiato
    if preset_id != cal['preset_id']:
        execute_write(
            "UPDATE calendari SET preset_id=? WHERE id=?",
            (preset_id, cal_id)
        )

    # 5. Ricarica snapshot regole conflitto dalle regole attuali
    from app.services.validatori import snapshot_regole
    regole_json = snapshot_regole()

    # 6. Ricarica config snapshot completo (vincoli, accesso, flag, ecc.)
    from app.services.config_snapshot import crea_config_snapshot, APPEARANCE_DEFAULT
    config_json = crea_config_snapshot(preset_id=preset_id)

    # 7. Aggiorna anche appearance_snapshot dal preset corrente
    app_row = query_one(
        "SELECT appearance FROM struttura_presets WHERE id=?", (preset_id,)
    )
    app_data = {}
    if app_row and app_row['appearance']:
        try:
            app_data = json.loads(app_row['appearance'])
        except (json.JSONDecodeError, TypeError):
            pass
    appearance_json = json.dumps({**APPEARANCE_DEFAULT, **app_data})

    execute_write(
        "UPDATE calendari SET regole_snapshot=?, config_snapshot=?, appearance_snapshot=? WHERE id=?",
        (regole_json, config_json, appearance_json, cal_id)
    )

    return jsonify({
        'ok': True,
        'diff': diff,
        'history_puliti': len(orfani_ids),
        'messaggio': (
            f'Struttura ricaricata: {len(da_aggiungere)} aggiunti, '
            f'{len(da_rimuovere)} rimossi, {len(da_aggiornare)} aggiornati. '
            f'{len(orfani_ids)} step history ripuliti. '
            f'Regole, vincoli, accesso, configurazione e aspetto griglia aggiornati.'
        )
    }), 200


# =============================================================================
# GIORNI CALENDARIO
# =============================================================================

@bp.route('/calendari/<int:cal_id>/giorni', methods=['GET'])
@require_role('admin', 'manager')
def lista_giorni(cal_id):
    giorni = query_all(
        "SELECT giorno, is_lavorativo, ore_lavorative, tipo "
        "FROM giorni_calendario WHERE calendario_id=? ORDER BY giorno",
        (cal_id,)
    )
    return jsonify({'ok': True, 'giorni': giorni}), 200


@bp.route('/calendari/<int:cal_id>/giorni', methods=['PUT'])
@require_role('admin')
def aggiorna_giorni(cal_id):
    dati = request.get_json(silent=True) or {}
    giorni = dati.get('giorni', [])
    if not giorni:
        return jsonify({'ok': False, 'errore': 'Lista giorni vuota.'}), 400

    for g in giorni:
        execute_write(
            """
            UPDATE giorni_calendario
            SET is_lavorativo=?, ore_lavorative=?, tipo=?
            WHERE calendario_id=? AND giorno=?
            """,
            (
                int(bool(g.get('is_lavorativo', g.get('lavorativo', 1)))),
                g.get('ore_lavorative'),
                g.get('tipo', 'normale'),
                cal_id,
                g['giorno']
            )
        )
    return jsonify({'ok': True, 'messaggio': f'{len(giorni)} giorni aggiornati.'}), 200


# =============================================================================
# APERTURE STRAORDINARIE (per-calendario, per-turno)
# =============================================================================

@bp.route('/calendari/<int:cal_id>/aperture', methods=['GET'])
@require_role('admin', 'manager')
def lista_aperture(cal_id):
    """Restituisce aperture per ogni turno del calendario."""
    turni = query_all(
        "SELECT id, sigla, apri_festivi, apri_superfestivi, aperture_straordinarie "
        "FROM calendario_turni WHERE calendario_id=? ORDER BY ordine",
        (cal_id,)
    )
    result = []
    for t in turni:
        try:
            ap = json.loads(t['aperture_straordinarie']) if t['aperture_straordinarie'] else []
        except (json.JSONDecodeError, TypeError):
            ap = []
        result.append({
            'turno_id': t['id'],
            'sigla': t['sigla'],
            'apri_festivi': t['apri_festivi'],
            'apri_superfestivi': t['apri_superfestivi'],
            'aperture_straordinarie': ap,
        })
    return jsonify({'ok': True, 'aperture': result}), 200


@bp.route('/calendari/<int:cal_id>/aperture', methods=['PUT'])
@require_role('admin', 'manager')
def salva_aperture(cal_id):
    """Salva aperture per uno o più turni del calendario."""
    dati = request.get_json(silent=True) or {}
    aperture = dati.get('aperture', [])

    for item in aperture:
        turno_id = item.get('turno_id')
        if not turno_id:
            continue
        apri_f = int(item.get('apri_festivi', 0) or 0)
        apri_sf = int(item.get('apri_superfestivi', 0) or 0)
        ap_str = json.dumps(item.get('aperture_straordinarie', []))
        execute_write(
            "UPDATE calendario_turni SET apri_festivi=?, apri_superfestivi=?, "
            "aperture_straordinarie=? WHERE id=? AND calendario_id=?",
            (apri_f, apri_sf, ap_str, turno_id, cal_id)
        )

    return jsonify({'ok': True, 'messaggio': f'{len(aperture)} turni aggiornati.'}), 200


# =============================================================================
# DEADLINE UTENTI
# =============================================================================

@bp.route('/calendari/<int:cal_id>/deadline', methods=['GET'])
@require_role('admin', 'manager')
def lista_deadline(cal_id):
    dl = query_all(
        """
        SELECT du.user_id, u.sigla, du.deadline
        FROM deadline_utenti du
        JOIN users u ON du.user_id = u.id
        WHERE du.calendario_id = ?
        ORDER BY u.sigla
        """,
        (cal_id,)
    )
    return jsonify({'ok': True, 'deadline': dl}), 200


@bp.route('/calendari/<int:cal_id>/deadline', methods=['PUT'])
@require_role('admin', 'manager')
def imposta_deadline(cal_id):
    dati = request.get_json(silent=True) or {}
    user_id  = dati.get('user_id')
    deadline = dati.get('deadline')

    if not user_id:
        return jsonify({'ok': False, 'errore': 'user_id obbligatorio.'}), 400

    if deadline is None:
        execute_write(
            "DELETE FROM deadline_utenti WHERE calendario_id=? AND user_id=?",
            (cal_id, user_id)
        )
        return jsonify({'ok': True, 'messaggio': 'Deadline personale rimossa.'}), 200

    execute_write(
        """
        INSERT INTO deadline_utenti (calendario_id, user_id, deadline) VALUES (?,?,?)
        ON CONFLICT(calendario_id, user_id) DO UPDATE SET deadline = excluded.deadline
        """,
        (cal_id, user_id, deadline)
    )
    return jsonify({'ok': True, 'messaggio': 'Deadline personale aggiornata.'}), 200


# =============================================================================
# CONFIG
# =============================================================================

@bp.route('/config', methods=['GET'])
@require_role('admin')
def get_config():
    righe = query_all("SELECT chiave, valore, descrizione FROM config")
    config = {r['chiave']: r['valore'] for r in righe}
    return jsonify({'ok': True, 'config': config}), 200


@bp.route('/config', methods=['PUT'])
@require_role('admin')
def aggiorna_config():
    dati = request.get_json(silent=True) or {}
    for chiave, valore in dati.items():
        execute_write(
            "INSERT INTO config (chiave, valore) VALUES (?,?) "
            "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore",
            (chiave, str(valore))
        )
    return jsonify({'ok': True, 'messaggio': f'{len(dati)} parametri aggiornati.'}), 200


# =============================================================================
# VINCOLI SOLVER
# =============================================================================

@bp.route('/vincoli-globali', methods=['GET'])
@require_role('admin', 'manager')
def get_vincoli_globali():
    rows = query_all("SELECT id, chiave, valore, descrizione, is_active FROM vincoli_globali ORDER BY id")
    return jsonify({'ok': True, 'vincoli': [dict(r) for r in rows]}), 200


@bp.route('/vincoli-globali', methods=['PUT'])
@require_role('admin')
def set_vincoli_globali():
    dati = request.get_json(silent=True) or {}
    vincoli = dati.get('vincoli', [])
    for v in vincoli:
        execute_write(
            "INSERT INTO vincoli_globali (chiave, valore, descrizione, is_active) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore, "
            "descrizione=excluded.descrizione, is_active=excluded.is_active",
            (v['chiave'], str(v['valore']),
             v.get('descrizione', ''), int(v.get('is_active', 1)))
        )
    return jsonify({'ok': True, 'messaggio': f'{len(vincoli)} vincoli aggiornati.'}), 200


@bp.route('/vincoli-utente/<int:uid>', methods=['GET'])
@require_role('admin', 'manager')
def get_vincoli_utente(uid):
    rows = query_all(
        "SELECT id, chiave, valore, note FROM vincoli_utente WHERE user_id=? ORDER BY chiave",
        (uid,)
    )
    return jsonify({'ok': True, 'vincoli': [dict(r) for r in rows]}), 200


@bp.route('/vincoli-utente/<int:uid>', methods=['PUT'])
@require_role('admin', 'manager')
def set_vincoli_utente(uid):
    dati = request.get_json(silent=True) or {}
    vincoli = dati.get('vincoli', [])
    # Rimpiazza tutti i vincoli per l'utente
    execute_write("DELETE FROM vincoli_utente WHERE user_id=?", (uid,))
    for v in vincoli:
        if v.get('valore') is not None and str(v['valore']).strip():
            execute_write(
                "INSERT INTO vincoli_utente (user_id, chiave, valore, note) VALUES (?,?,?,?)",
                (uid, v['chiave'], str(v['valore']), v.get('note', ''))
            )
    return jsonify({'ok': True, 'messaggio': f'Vincoli utente aggiornati.'}), 200


@bp.route('/vincoli-utente/<int:uid>/<chiave>', methods=['DELETE'])
@require_role('admin', 'manager')
def del_vincolo_utente(uid, chiave):
    execute_write(
        "DELETE FROM vincoli_utente WHERE user_id=? AND chiave=?",
        (uid, chiave)
    )
    return jsonify({'ok': True, 'messaggio': 'Vincolo utente rimosso.'}), 200


# =============================================================================
# ESCLUSIONI UTENTE (flag-based)
# =============================================================================

@bp.route('/giorni-esclusi/<int:uid>', methods=['GET'])
@require_role('admin', 'manager')
def get_giorni_esclusi(uid):
    """Restituisce i giorni della settimana esclusi per un utente (0=Lun..6=Dom)."""
    row = query_one("SELECT giorni_esclusi FROM users WHERE id=?", (uid,))
    if not row:
        return jsonify({'ok': False, 'errore': 'Utente non trovato.'}), 404
    try:
        giorni = json.loads(row['giorni_esclusi'] or '[]')
    except (json.JSONDecodeError, TypeError):
        giorni = []
    return jsonify({'ok': True, 'giorni_esclusi': giorni}), 200


@bp.route('/giorni-esclusi/<int:uid>', methods=['PUT'])
@require_role('admin', 'manager')
def set_giorni_esclusi(uid):
    """Salva i giorni della settimana esclusi per un utente."""
    dati = request.get_json(silent=True) or {}
    giorni = dati.get('giorni_esclusi', [])
    # Validazione: solo interi 0-6
    validi = [d for d in giorni if isinstance(d, int) and 0 <= d <= 6]
    execute_write(
        "UPDATE users SET giorni_esclusi=? WHERE id=?",
        (json.dumps(sorted(set(validi))), uid)
    )
    return jsonify({'ok': True, 'messaggio': 'Giorni esclusi aggiornati.'}), 200


# =============================================================================
# VINCOLI SOLVER (flag / tipo qualitativo)
# =============================================================================

@bp.route('/vincoli-solver', methods=['GET'])
@require_role('admin', 'manager')
def get_vincoli_solver():
    """Lista vincoli solver con nome flag/tipo risolto."""
    rows = query_all(
        "SELECT id, tipo, ref_id, max_n, is_active, descrizione "
        "FROM vincoli_solver ORDER BY tipo, ref_id"
    )
    risultato = []
    for r in rows:
        d = dict(r)
        if d['tipo'] == 'flag':
            ref = query_one("SELECT nome FROM flag_turno WHERE id=?", (d['ref_id'],))
            d['ref_nome'] = ref['nome'] if ref else '?'
        else:
            ref = query_one("SELECT nome FROM tipi_qualitativo WHERE id=?", (d['ref_id'],))
            d['ref_nome'] = ref['nome'] if ref else '?'
        risultato.append(d)
    return jsonify({'ok': True, 'vincoli': risultato}), 200


@bp.route('/vincoli-solver', methods=['PUT'])
@require_role('admin')
def set_vincoli_solver():
    """UPSERT lista vincoli solver."""
    dati = request.get_json(silent=True) or {}
    vincoli = dati.get('vincoli', [])
    for v in vincoli:
        tipo = v.get('tipo')
        ref_id = v.get('ref_id')
        if not tipo or not ref_id:
            continue
        execute_write(
            "INSERT INTO vincoli_solver (tipo, ref_id, max_n, is_active, descrizione) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(tipo, ref_id) DO UPDATE SET max_n=excluded.max_n, "
            "is_active=excluded.is_active, descrizione=excluded.descrizione",
            (tipo, ref_id, int(v.get('max_n', 0)),
             int(v.get('is_active', 1)), v.get('descrizione', ''))
        )
    return jsonify({'ok': True, 'messaggio': f'{len(vincoli)} vincoli solver aggiornati.'}), 200


@bp.route('/vincoli-solver/<int:vid>', methods=['DELETE'])
@require_role('admin')
def del_vincolo_solver(vid):
    execute_write("DELETE FROM vincoli_solver WHERE id=?", (vid,))
    return jsonify({'ok': True, 'messaggio': 'Vincolo solver rimosso.'}), 200


@bp.route('/vincoli-solver-utente/<int:uid>', methods=['GET'])
@require_role('admin', 'manager')
def get_vincoli_solver_utente(uid):
    rows = query_all(
        "SELECT id, tipo, ref_id, max_n, note "
        "FROM vincoli_solver_utente WHERE user_id=? ORDER BY tipo, ref_id",
        (uid,)
    )
    risultato = []
    for r in rows:
        d = dict(r)
        if d['tipo'] == 'flag':
            ref = query_one("SELECT nome FROM flag_turno WHERE id=?", (d['ref_id'],))
            d['ref_nome'] = ref['nome'] if ref else '?'
        else:
            ref = query_one("SELECT nome FROM tipi_qualitativo WHERE id=?", (d['ref_id'],))
            d['ref_nome'] = ref['nome'] if ref else '?'
        risultato.append(d)
    return jsonify({'ok': True, 'vincoli': risultato}), 200


@bp.route('/vincoli-solver-utente/<int:uid>', methods=['PUT'])
@require_role('admin', 'manager')
def set_vincoli_solver_utente(uid):
    dati = request.get_json(silent=True) or {}
    vincoli = dati.get('vincoli', [])
    execute_write("DELETE FROM vincoli_solver_utente WHERE user_id=?", (uid,))
    for v in vincoli:
        tipo = v.get('tipo')
        ref_id = v.get('ref_id')
        if not tipo or not ref_id:
            continue
        execute_write(
            "INSERT OR IGNORE INTO vincoli_solver_utente "
            "(user_id, tipo, ref_id, max_n, note) VALUES (?,?,?,?,?)",
            (uid, tipo, ref_id, int(v.get('max_n', 0)), v.get('note', ''))
        )
    return jsonify({'ok': True, 'messaggio': 'Vincoli solver utente aggiornati.'}), 200


@bp.route('/vincoli-solver-utente/<int:uid>/<int:vid>', methods=['DELETE'])
@require_role('admin', 'manager')
def del_vincolo_solver_utente(uid, vid):
    execute_write(
        "DELETE FROM vincoli_solver_utente WHERE id=? AND user_id=?", (vid, uid)
    )
    return jsonify({'ok': True, 'messaggio': 'Vincolo solver utente rimosso.'}), 200


@bp.route('/solver-utenti-riepilogo', methods=['GET'])
@require_role('admin', 'manager')
def solver_utenti_riepilogo():
    """Riepilogo vincoli + giorni esclusi + vincoli solver per tutti gli utenti basic attivi."""
    utenti = query_all(
        "SELECT id, sigla, username, giorni_esclusi "
        "FROM users WHERE is_active=1 AND role IN ('basic','manager','admin') ORDER BY sigla"
    )
    risultato = []
    for u in utenti:
        vincoli = query_all(
            "SELECT chiave, valore FROM vincoli_utente WHERE user_id=?", (u['id'],)
        )
        vincoli_solver = query_all(
            "SELECT vsu.tipo, vsu.ref_id, vsu.max_n, vsu.note "
            "FROM vincoli_solver_utente vsu WHERE vsu.user_id=?", (u['id'],)
        )
        vs_out = []
        for vs in vincoli_solver:
            d = dict(vs)
            if d['tipo'] == 'flag':
                ref = query_one("SELECT nome FROM flag_turno WHERE id=?", (d['ref_id'],))
            else:
                ref = query_one("SELECT nome FROM tipi_qualitativo WHERE id=?", (d['ref_id'],))
            d['ref_nome'] = ref['nome'] if ref else '?'
            vs_out.append(d)
        try:
            giorni_esclusi = json.loads(u['giorni_esclusi'] or '[]')
        except (json.JSONDecodeError, TypeError):
            giorni_esclusi = []
        risultato.append({
            'id': u['id'], 'sigla': u['sigla'], 'username': u['username'],
            'vincoli': [dict(v) for v in vincoli],
            'giorni_esclusi': giorni_esclusi,
            'vincoli_solver': vs_out,
        })
    return jsonify({'ok': True, 'utenti': risultato}), 200


# =============================================================================
# HELPER PRIVATI
# =============================================================================

def _calcola_festivita(anno):
    """
    Le date festive di un anno, dalle ricorrenze configurate nel tenant.

    Erano scritte nel codice, uguali per tutti: il santo patrono di Roma
    finiva festivo anche a Torino. Ora stanno in tabella, seminate con le
    nazionali italiane e modificabili da chi configura.

    Args:
        anno (int): anno del calendario.

    Returns:
        dict: {'festivi': [iso], 'superfestivi': [iso]}.
    """
    return espandi_festivita(
        query_all(
            "SELECT nome, giorno, mese, offset_pasqua, tipo, is_active "
            "FROM festivita WHERE is_active = 1", ()
        ),
        int(anno)
    )


# =============================================================================
# MODELLO EXCEL — la struttura letta da un foglio di calcolo
# =============================================================================

# Quanto puo' pesare il foglio caricato. I modelli veri stanno sotto il mezzo
# megabyte; oltre, e' probabile che sia un altro file.
DIMENSIONE_MAX_MODELLO = 8 * 1024 * 1024

# Caratteri della password provvisoria generata per chi arriva dal foglio.
CIFRE_PASSWORD_PROVVISORIA = 10

# Lunghezza massima della sigla ricavata da un nome lungo.
LUNGHEZZA_SIGLA = 8


def _sigla_da_nome(nome, lunghezza=LUNGHEZZA_SIGLA):
    """
    Una sigla leggibile ricavata da un nome: sole lettere e cifre, maiuscole.

    Args:
        nome (str): nome di partenza.
        lunghezza (int): quanti caratteri tenere.

    Returns:
        str: la sigla, eventualmente vuota se il nome non ha caratteri utili.
    """
    return ''.join(c for c in nome.upper() if c.isalnum())[:lunghezza]


def _sigla_libera(base, gia_usate):
    """
    Una sigla che non collide con quelle gia' prese, numerandola se serve.

    Args:
        base (str): sigla desiderata.
        gia_usate (set): sigle occupate; viene aggiornato.

    Returns:
        str: la sigla assegnata.
    """
    base = base or 'X'
    candidata = base
    contatore = 2
    while candidata in gia_usate:
        coda = str(contatore)
        candidata = base[:LUNGHEZZA_SIGLA - len(coda)] + coda
        contatore += 1

    gia_usate.add(candidata)

    return candidata


def _modello_dalla_richiesta():
    """
    Il foglio allegato alla richiesta, letto e validato.

    Returns:
        tuple: (nome file, contenuto in byte, None) oppure (None, None, errore).
    """
    caricato = request.files.get('file')
    if caricato is None or not caricato.filename:
        return None, None, 'Nessun file allegato.'

    contenuto = caricato.read()
    if not contenuto:
        return None, None, 'Il file e vuoto.'
    if len(contenuto) > DIMENSIONE_MAX_MODELLO:
        return None, None, 'Il file e troppo grande per essere un modello turni.'

    return caricato.filename, contenuto, None


@bp.route('/modello/analizza', methods=['POST'])
@require_role('admin')
def analizza_modello():
    """
    Legge un foglio Excel e racconta che struttura ci ha trovato.

    Non scrive niente: serve a far vedere all'amministratore cosa verrebbe
    creato, e cosa nel foglio non e' stato capito, prima di decidere.
    """
    nome_file, contenuto, errore = _modello_dalla_richiesta()
    if errore:
        return jsonify({'ok': False, 'errore': errore}), 400

    try:
        letto = leggi_struttura(io.BytesIO(contenuto))
    except ValueError as e:
        return jsonify({'ok': False, 'errore': str(e)}), 400
    except Exception as e:
        current_app.logger.warning('Lettura del modello fallita: %s', e)
        return jsonify({'ok': False, 'errore': 'Il file non si legge come foglio Excel.'}), 400

    return jsonify({
        'ok': True,
        'nome_file': nome_file,
        **letto,
        **_gia_presenti(letto),
    }), 200


def _gia_presenti(letto):
    """
    Cosa del foglio il tenant ha gia', per non prometterlo come nuovo.

    Args:
        letto (dict): esito di leggi_struttura().

    Returns:
        dict: sigle di persone e nomi di tipologie gia' esistenti.
    """
    sigle = {r['sigla'].upper() for r in query_all("SELECT sigla FROM users", ())}
    tipologie = {r['nome'] for r in query_all("SELECT nome FROM tipi_qualitativo", ())}

    return {
        'persone_gia_presenti': sorted(
            p['sigla'] for p in letto['persone'] if p['sigla'].upper() in sigle
        ),
        'tipologie_gia_presenti': sorted(
            t for t in letto['tipologie'] if t in tipologie
        ),
    }


def _crea_tipologie(nomi):
    """Crea le tipologie turno che mancano. Restituisce nome → id."""
    per_nome = {
        r['nome']: r['id']
        for r in query_all("SELECT id, nome FROM tipi_qualitativo", ())
    }

    for nome in nomi:
        if nome in per_nome:
            continue
        cur = execute_write(
            "INSERT INTO tipi_qualitativo (nome, descrizione) VALUES (?,?)",
            (nome, 'Dal modello Excel')
        )
        per_nome[nome] = cur.lastrowid

    return per_nome


def _crea_persone(persone):
    """
    Crea le persone che mancano, con una password provvisoria ciascuna.

    Chi c'e' gia', riconosciuto dalla sigla, non viene toccato: il foglio non
    deve sovrascrivere le persone del programma.

    Args:
        persone (list): [{sigla, cognome, nome}] dal foglio.

    Returns:
        list: [{sigla, username, password}] di chi e' stato creato.
    """
    esistenti = {
        r['sigla'].upper() for r in query_all("SELECT sigla FROM users", ())
    }
    username_presi = {
        r['username'].lower() for r in query_all("SELECT username FROM users", ())
    }

    credenziali = []
    for p in persone:
        if p['sigla'].upper() in esistenti:
            continue

        username = p['sigla'].lower()
        if username in username_presi:
            continue

        password = secrets.token_urlsafe(CIFRE_PASSWORD_PROVVISORIA)
        execute_write(
            "INSERT INTO users (username, password_hash, role, sigla) "
            "VALUES (?,?,'basic',?)",
            (username, hash_password(password), p['sigla'].upper())
        )
        esistenti.add(p['sigla'].upper())
        username_presi.add(username)
        credenziali.append({
            'sigla': p['sigla'].upper(), 'username': username, 'password': password,
        })

    return credenziali


def _struttura_del_tenant():
    """
    La struttura turni del tenant: ne ha una sola.

    E' quella marcata come predefinita. Se nessuna lo e' — puo' succedere a
    un'installazione che ne ha accumulate prima che la regola esistesse — si
    prende l'ultima creata, invece di lasciare l'organizzazione senza
    struttura e senza modo di fare un calendario. Il primo import la marca, e
    da li' in avanti la scelta e' scritta.

    Returns:
        int|None: id della struttura, None se il tenant non ne ha nessuna.
    """
    predefinita = query_one(
        "SELECT id FROM struttura_presets WHERE is_default=1", ()
    )
    if predefinita:
        return predefinita['id']

    ultima = query_one(
        "SELECT id FROM struttura_presets ORDER BY id DESC LIMIT 1", ()
    )

    return ultima['id'] if ultima else None


def _svuota_struttura(preset_id):
    """
    Toglie da una struttura turni tutto il suo contenuto.

    Cancellare i sovragruppi porta via a cascata gruppi e turni, e con loro
    posti fissi ed esclusioni, che parlavano di turni che non esistono piu'.
    I calendari gia' creati non ne risentono: ciascuno porta la propria copia
    della struttura, fatta al momento della creazione.
    """
    execute_write("DELETE FROM sovragruppi WHERE preset_id=?", (preset_id,))


def _crea_struttura_turni(nome_preset, letto):
    """
    Scrive nella struttura turni del tenant quella letta dal foglio.

    Il tenant ha una struttura sola: se ce l'ha gia', questa la sostituisce —
    non se ne affianca una seconda. I turni conservano l'ordine del foglio,
    che e' quello con cui la griglia del modello dispone le righe, ed e' cio'
    che permettera' di riesportarci dentro un mese.

    Args:
        nome_preset (str): nome da dare alla struttura turni.
        letto (dict): esito di leggi_struttura().

    Returns:
        tuple: (id della struttura, None) oppure (None, messaggio d'errore).
    """
    fasce = {
        r['nome']: r['id']
        for r in query_all("SELECT id, nome FROM flag_turno", ())
    }
    mancanti = sorted({t['fascia'] for t in letto['turni']} - set(fasce))
    if mancanti:
        return None, (
            f"Nel programma mancano le fasce orarie {', '.join(mancanti)}: "
            f"creale nella configurazione, poi riprova."
        )

    tipologie = _crea_tipologie(letto['tipologie'])

    preset_id = _struttura_del_tenant()
    if preset_id is None:
        preset_id = execute_write(
            "INSERT INTO struttura_presets (nome, created_by, is_default) "
            "VALUES (?,?,1)",
            (nome_preset, get_current_user()['id'])
        ).lastrowid
    else:
        _svuota_struttura(preset_id)
        execute_write(
            "UPDATE struttura_presets SET nome=?, is_default=1 WHERE id=?",
            (nome_preset, preset_id)
        )
        # Una sola predefinita: se ne restassero altre, il calendario non
        # saprebbe piu' quale struttura usare.
        execute_write(
            "UPDATE struttura_presets SET is_default=0 WHERE id!=?", (preset_id,)
        )

    sigle_sg = set()
    for ordine_sg, struttura in enumerate(letto['strutture']):
        cur = execute_write(
            "INSERT INTO sovragruppi (preset_id, sigla, nome, ordine) VALUES (?,?,?,?)",
            (preset_id, _sigla_libera(_sigla_da_nome(struttura['nome']), sigle_sg),
             struttura['nome'], ordine_sg * 10)
        )
        _crea_turni_della_struttura(
            cur.lastrowid, struttura['chiave'], letto['turni'], fasce, tipologie
        )

    return preset_id, None


def _crea_turni_della_struttura(sg_id, chiave, turni, fasce, tipologie):
    """
    Crea i gruppi di fascia di una struttura, e sotto ciascuno i suoi turni.

    Il gruppo non e' un livello che l'utente sceglie: nasce dal fatto che due
    turni cadono nella stessa fascia, come nella configurazione guidata.
    """
    suoi = [t for t in turni if t['struttura'] == chiave]
    sigle_turni = set()

    for ordine_g, fascia in enumerate(dict.fromkeys(t['fascia'] for t in suoi)):
        cur = execute_write(
            "INSERT INTO gruppi (sovragruppo_id, sigla, nome, flag_id, ordine) "
            "VALUES (?,?,?,?,?)",
            (sg_id, _sigla_da_nome(fascia, 3), fascia.capitalize(),
             fasce[fascia], ordine_g * 10)
        )
        gruppo_id = cur.lastrowid

        for ordine_t, turno in enumerate(t for t in suoi if t['fascia'] == fascia):
            cur = execute_write(
                "INSERT INTO preset_turni (gruppo_id, sigla, nome, ordine) "
                "VALUES (?,?,?,?)",
                (gruppo_id, _sigla_libera(_sigla_da_nome(turno['nome']), sigle_turni),
                 turno['nome'], ordine_t * 10)
            )
            if turno['tipologia'] in tipologie:
                execute_write(
                    "INSERT OR IGNORE INTO preset_turni_qualitativo "
                    "(preset_turno_id, tipo_qualitativo_id) VALUES (?,?)",
                    (cur.lastrowid, tipologie[turno['tipologia']])
                )


@bp.route('/modello/applica', methods=['POST'])
@require_role('admin')
def applica_modello():
    """
    Crea struttura turni, tipologie e persone da un foglio Excel, e lo tiene.

    Il foglio resta nel tenant: e' il modello in cui i mesi programmati
    verranno riesportati, e la struttura appena creata gli combacia riga per
    riga.

    Form multipart:
        file (file): il foglio.
        nome_preset (str): come chiamare la struttura turni.
        strutture (str): JSON {chiave: nome}, per correggere le sedi dedotte
                         dal foglio. Due nomi uguali fondono due strutture.
    """
    nome_file, contenuto, errore = _modello_dalla_richiesta()
    if errore:
        return jsonify({'ok': False, 'errore': errore}), 400

    nome_preset = (request.form.get('nome_preset') or '').strip()
    if not nome_preset:
        return jsonify({'ok': False, 'errore': 'Dai un nome alla struttura turni.'}), 400
    altra = query_one(
        "SELECT id FROM struttura_presets WHERE nome=? AND id!=COALESCE(?, -1)",
        (nome_preset, _struttura_del_tenant())
    )
    if altra:
        return jsonify({
            'ok': False,
            'errore': f'Un\'altra struttura turni si chiama gia "{nome_preset}".'
        }), 409

    try:
        letto = leggi_struttura(io.BytesIO(contenuto))
    except ValueError as e:
        return jsonify({'ok': False, 'errore': str(e)}), 400

    try:
        rinomina = json.loads(request.form.get('strutture') or '{}')
    except json.JSONDecodeError:
        return jsonify({'ok': False, 'errore': 'Correzioni alle strutture illeggibili.'}), 400
    if not isinstance(rinomina, dict):
        return jsonify({'ok': False, 'errore': 'Correzioni alle strutture illeggibili.'}), 400

    letto = rinomina_strutture(letto, rinomina)

    sostituita = _struttura_del_tenant() is not None

    preset_id, errore = _crea_struttura_turni(nome_preset, letto)
    if errore:
        return jsonify({'ok': False, 'errore': errore}), 409

    credenziali = _crea_persone(letto['persone'])

    execute_write(
        "INSERT INTO modello_turni (id, nome_file, contenuto, caricato_at) "
        "VALUES (1,?,?,datetime('now')) "
        "ON CONFLICT(id) DO UPDATE SET nome_file=excluded.nome_file, "
        "contenuto=excluded.contenuto, caricato_at=excluded.caricato_at",
        (nome_file, contenuto)
    )

    return jsonify({
        'ok': True,
        'preset_id': preset_id,
        'sostituita': sostituita,
        'strutture': len(letto['strutture']),
        'turni': len(letto['turni']),
        'tipologie': len(letto['tipologie']),
        'persone_create': credenziali,
        'avvisi': letto['avvisi'],
    }), 201


@bp.route('/modello', methods=['GET'])
@require_role('admin')
def stato_modello():
    """Se questo tenant ha un modello caricato, e quale."""
    riga = query_one(
        "SELECT nome_file, caricato_at, LENGTH(contenuto) AS byte "
        "FROM modello_turni WHERE id=1", ()
    )

    return jsonify({'ok': True, 'modello': riga}), 200


# =============================================================================
# FESTIVITA' — le ricorrenze che rendono festivo un giorno
# =============================================================================

# Quanti giorni prima o dopo la Pasqua puo' cadere una ricorrenza: oltre, non
# e' piu' una festivita' legata alla Pasqua ma un'altra cosa.
OFFSET_PASQUA_MAX = 70

TIPI_FESTIVITA = (TIPO_FESTIVO, TIPO_SUPERFESTIVO)


def _leggi_ricorrenza(dati, correnti=None):
    """
    Estrae e valida una ricorrenza dal payload.

    Una festivita' o ha una data fissa (giorno e mese) o si conta dalla
    Pasqua: le due si escludono, e senza nessuna delle due la riga non
    individua nessun giorno.

    Args:
        dati (dict): payload della richiesta.
        correnti (dict|None): riga esistente, sulla PUT.

    Returns:
        tuple: (dict con i campi, None) oppure ({}, messaggio d'errore).
    """
    correnti = correnti or {}

    nome = (dati.get('nome') if 'nome' in dati else correnti.get('nome')) or ''
    nome = str(nome).strip()
    if not nome:
        return {}, 'Il nome della festivita e obbligatorio.'

    def numero(campo):
        grezzo = dati.get(campo, correnti.get(campo))
        if grezzo is None or grezzo == '':
            return None
        try:
            return int(grezzo)
        except (TypeError, ValueError):
            raise ValueError(campo)

    try:
        giorno, mese, offset = numero('giorno'), numero('mese'), numero('offset_pasqua')
    except ValueError as e:
        return {}, f'Valore non numerico per {e}.'

    if offset is not None:
        if not -OFFSET_PASQUA_MAX <= offset <= OFFSET_PASQUA_MAX:
            return {}, 'La distanza dalla Pasqua e fuori scala.'
        giorno = mese = None
    else:
        if giorno is None or mese is None:
            return {}, 'Servono giorno e mese, oppure la distanza dalla Pasqua.'
        if not 1 <= mese <= 12 or not 1 <= giorno <= 31:
            return {}, 'Giorno o mese fuori intervallo.'

    tipo = dati.get('tipo', correnti.get('tipo', TIPO_SUPERFESTIVO))
    if tipo not in TIPI_FESTIVITA:
        tipo = TIPO_SUPERFESTIVO

    attiva = dati.get('is_active', correnti.get('is_active', 1))

    return {
        'nome': nome, 'giorno': giorno, 'mese': mese, 'offset_pasqua': offset,
        'tipo': tipo, 'is_active': int(bool(attiva)),
    }, None


@bp.route('/festivita', methods=['GET'])
@require_role('admin', 'manager')
def lista_festivita():
    """
    Le ricorrenze configurate, con le date che assumono in un anno.

    Query string:
        anno (int): anno per cui calcolare le date; senza, quello corrente.
    """
    try:
        anno = int(request.args.get('anno') or datetime.now().year)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'errore': 'Anno non valido.'}), 400

    righe = query_all(
        "SELECT id, nome, giorno, mese, offset_pasqua, tipo, is_active "
        "FROM festivita ORDER BY offset_pasqua IS NULL DESC, mese, giorno, nome",
        ()
    )
    for r in righe:
        data = data_della_ricorrenza(r, anno)
        r['data'] = data.isoformat() if data else None

    return jsonify({'ok': True, 'anno': anno, 'festivita': righe}), 200


@bp.route('/festivita', methods=['POST'])
@require_role('admin')
def crea_festivita():
    """Aggiunge una ricorrenza."""
    dati = request.get_json(silent=True) or {}
    campi, errore = _leggi_ricorrenza(dati)
    if errore:
        return jsonify({'ok': False, 'errore': errore}), 400

    if query_one("SELECT id FROM festivita WHERE nome=?", (campi['nome'],)):
        return jsonify({
            'ok': False, 'errore': f"Festivita \"{campi['nome']}\" gia presente."
        }), 409

    cur = execute_write(
        "INSERT INTO festivita (nome, giorno, mese, offset_pasqua, tipo, is_active) "
        "VALUES (?,?,?,?,?,?)",
        (campi['nome'], campi['giorno'], campi['mese'], campi['offset_pasqua'],
         campi['tipo'], campi['is_active'])
    )

    return jsonify({'ok': True, 'id': cur.lastrowid}), 201


@bp.route('/festivita/<int:fid>', methods=['PUT'])
@require_role('admin')
def modifica_festivita(fid):
    """Modifica una ricorrenza, o la spegne senza cancellarla."""
    corrente = query_one("SELECT * FROM festivita WHERE id=?", (fid,))
    if not corrente:
        return jsonify({'ok': False, 'errore': 'Festivita non trovata.'}), 404

    dati = request.get_json(silent=True) or {}
    campi, errore = _leggi_ricorrenza(dati, corrente)
    if errore:
        return jsonify({'ok': False, 'errore': errore}), 400

    dup = query_one("SELECT id FROM festivita WHERE nome=? AND id!=?",
                    (campi['nome'], fid))
    if dup:
        return jsonify({
            'ok': False, 'errore': f"Nome \"{campi['nome']}\" gia in uso."
        }), 409

    execute_write(
        "UPDATE festivita SET nome=?, giorno=?, mese=?, offset_pasqua=?, "
        "tipo=?, is_active=? WHERE id=?",
        (campi['nome'], campi['giorno'], campi['mese'], campi['offset_pasqua'],
         campi['tipo'], campi['is_active'], fid)
    )

    return jsonify({'ok': True, 'messaggio': 'Festivita aggiornata.'}), 200


@bp.route('/festivita/<int:fid>', methods=['DELETE'])
@require_role('admin')
def elimina_festivita(fid):
    """
    Elimina una ricorrenza.

    I calendari gia' creati non cambiano: la classificazione dei loro giorni
    e' scritta in `giorni_calendario` al momento della creazione.
    """
    if not query_one("SELECT id FROM festivita WHERE id=?", (fid,)):
        return jsonify({'ok': False, 'errore': 'Festivita non trovata.'}), 404

    execute_write("DELETE FROM festivita WHERE id=?", (fid,))

    return jsonify({'ok': True, 'messaggio': 'Festivita eliminata.'}), 200


# =============================================================================
# ACCESSO MANAGER — restrizioni manager→utenti e manager→turni
# =============================================================================

@bp.route('/accesso-manager', methods=['GET'])
@require_role('admin')
def get_accesso_manager():
    """Restituisce configurazione completa accesso manager (utenti + turni)."""
    managers = query_all(
        "SELECT id, sigla, username, role FROM users WHERE role IN ('admin','manager') AND is_active=1 ORDER BY sigla"
    )

    # Accesso utenti: user_id → [manager_ids]
    # Sentinel manager_id=0 → "ristretto a nessuno" → restituito come []
    acc_utenti_rows = query_all("SELECT manager_id, user_id FROM manager_accesso_utenti")
    accesso_utenti = {}
    for r in acc_utenti_rows:
        uid = str(r['user_id'])
        if r['manager_id'] == 0:
            accesso_utenti.setdefault(uid, [])  # sentinel: lista vuota esplicita
        else:
            accesso_utenti.setdefault(uid, []).append(r['manager_id'])

    # Accesso turni: preset_turno_id → [manager_ids]
    acc_turni_rows = query_all("SELECT manager_id, preset_turno_id FROM manager_accesso_turni")
    accesso_turni = {}
    for r in acc_turni_rows:
        tid = str(r['preset_turno_id'])
        if r['manager_id'] == 0:
            accesso_turni.setdefault(tid, [])
        else:
            accesso_turni.setdefault(tid, []).append(r['manager_id'])

    # --- Rilevamento riferimenti orfani ---
    orfani_turni = []  # preset_turno_id che non esistono più in preset_turni
    orfani_utenti = []  # user_id che non sono più attivi
    orfani_managers = []  # manager_id che non sono più attivi

    if acc_turni_rows:
        turni_ids_ref = {r['preset_turno_id'] for r in acc_turni_rows if r['manager_id'] != 0}
        if turni_ids_ref:
            turni_esistenti = {r['id'] for r in query_all("SELECT id FROM preset_turni")}
            orfani_turni = [tid for tid in turni_ids_ref if tid not in turni_esistenti]

    if acc_utenti_rows:
        utenti_ids_ref = {r['user_id'] for r in acc_utenti_rows if r['manager_id'] != 0}
        if utenti_ids_ref:
            utenti_attivi = {r['id'] for r in query_all("SELECT id FROM users WHERE is_active=1")}
            orfani_utenti = [uid for uid in utenti_ids_ref if uid not in utenti_attivi]

    # Manager orfani: manager_id presenti nelle tabelle accesso ma non più attivi
    all_manager_ids_ref = set()
    for r in acc_turni_rows:
        if r['manager_id'] not in (0,):
            all_manager_ids_ref.add(r['manager_id'])
    for r in acc_utenti_rows:
        if r['manager_id'] not in (0,):
            all_manager_ids_ref.add(r['manager_id'])
    if all_manager_ids_ref:
        managers_attivi = {m['id'] for m in managers}
        orfani_managers = [mid for mid in all_manager_ids_ref if mid not in managers_attivi]

    return jsonify({
        'ok': True,
        'managers': [dict(m) for m in managers],
        'accesso_utenti': accesso_utenti,
        'accesso_turni': accesso_turni,
        'orfani': {
            'turni': orfani_turni,
            'utenti': orfani_utenti,
            'managers': orfani_managers,
            'has_orfani': bool(orfani_turni or orfani_utenti or orfani_managers),
        }
    }), 200


@bp.route('/accesso-manager/utenti', methods=['PUT'])
@require_role('admin')
def set_accesso_utenti():
    """Salva restrizioni accesso manager→utenti. Body: { accesso: { user_id: [manager_ids] } }."""
    dati = request.get_json(silent=True) or {}
    accesso = dati.get('accesso', {})

    db = get_db()
    for uid_str, manager_ids in accesso.items():
        uid = int(uid_str)
        db.execute("DELETE FROM manager_accesso_utenti WHERE user_id=?", (uid,))
        if manager_ids is None:
            pass  # null = rimuovi restrizione (0 righe = accesso completo)
        elif len(manager_ids) == 0:
            # Sentinel: ristretto a nessuno
            db.execute("INSERT INTO manager_accesso_utenti (manager_id, user_id) VALUES (0, ?)", (uid,))
        else:
            for mid in manager_ids:
                db.execute(
                    "INSERT INTO manager_accesso_utenti (manager_id, user_id) VALUES (?, ?)",
                    (mid, uid)
                )
    db.commit()
    return jsonify({'ok': True}), 200


@bp.route('/accesso-manager/turni', methods=['PUT'])
@require_role('admin')
def set_accesso_turni():
    """Salva restrizioni accesso manager→turni. Body: { accesso: { preset_turno_id: [manager_ids] } }."""
    dati = request.get_json(silent=True) or {}
    accesso = dati.get('accesso', {})

    db = get_db()
    for tid_str, manager_ids in accesso.items():
        tid = int(tid_str)
        db.execute("DELETE FROM manager_accesso_turni WHERE preset_turno_id=?", (tid,))
        if manager_ids is None:
            pass  # null = rimuovi restrizione
        elif len(manager_ids) == 0:
            db.execute("INSERT INTO manager_accesso_turni (manager_id, preset_turno_id) VALUES (0, ?)", (tid,))
        else:
            for mid in manager_ids:
                db.execute(
                    "INSERT INTO manager_accesso_turni (manager_id, preset_turno_id) VALUES (?, ?)",
                    (mid, tid)
                )
    db.commit()
    return jsonify({'ok': True}), 200


@bp.route('/accesso-manager/pulisci-orfani', methods=['POST'])
@require_role('admin')
def pulisci_orfani_accesso():
    """Elimina riferimenti orfani nelle tabelle accesso manager."""
    db = get_db()

    # Turni orfani: preset_turno_id non esistenti in preset_turni
    turni_esistenti = {r['id'] for r in query_all("SELECT id FROM preset_turni")}
    turni_ref = query_all("SELECT DISTINCT preset_turno_id FROM manager_accesso_turni WHERE manager_id != 0")
    turni_rimossi = 0
    for r in turni_ref:
        if r['preset_turno_id'] not in turni_esistenti:
            db.execute("DELETE FROM manager_accesso_turni WHERE preset_turno_id=?", (r['preset_turno_id'],))
            turni_rimossi += 1

    # Utenti orfani: user_id non attivi
    utenti_attivi = {r['id'] for r in query_all("SELECT id FROM users WHERE is_active=1")}
    utenti_ref = query_all("SELECT DISTINCT user_id FROM manager_accesso_utenti WHERE manager_id != 0")
    utenti_rimossi = 0
    for r in utenti_ref:
        if r['user_id'] not in utenti_attivi:
            db.execute("DELETE FROM manager_accesso_utenti WHERE user_id=?", (r['user_id'],))
            utenti_rimossi += 1

    # Manager orfani: manager_id non più attivi
    managers_attivi = {r['id'] for r in query_all(
        "SELECT id FROM users WHERE role IN ('admin','manager') AND is_active=1"
    )}
    managers_rimossi = 0
    for table in ('manager_accesso_turni', 'manager_accesso_utenti'):
        refs = query_all(f"SELECT DISTINCT manager_id FROM {table} WHERE manager_id != 0")
        for r in refs:
            if r['manager_id'] not in managers_attivi:
                db.execute(f"DELETE FROM {table} WHERE manager_id=?", (r['manager_id'],))
                managers_rimossi += 1

    db.commit()
    return jsonify({
        'ok': True,
        'turni_rimossi': turni_rimossi,
        'utenti_rimossi': utenti_rimossi,
        'managers_rimossi': managers_rimossi,
    }), 200


# =============================================================================
# PRESET OTTIMIZZAZIONE (CRUD)
# =============================================================================

@bp.route('/preset-ottimizzazione', methods=['GET'])
@require_role('admin', 'manager')
def lista_preset_ottimizzazione():
    """Restituisce tutti i preset ottimizzazione attivi e inattivi."""
    rows = query_all(
        "SELECT id, nome, tipo, ref_id, pesi, is_default, ordine, is_active "
        "FROM preset_ottimizzazione ORDER BY ordine, id"
    )
    preset = []
    for r in rows:
        p = dict(r)
        try:
            p['pesi'] = json.loads(p['pesi'] or '{}')
        except (json.JSONDecodeError, TypeError):
            p['pesi'] = {}
        preset.append(p)
    return jsonify({'ok': True, 'preset': preset}), 200


@bp.route('/preset-ottimizzazione', methods=['POST'])
@require_role('admin')
def crea_preset_ottimizzazione():
    """
    Crea un nuovo preset ottimizzazione.

    Body JSON:
        nome (str): nome univoco
        tipo (str): completo|per_flag|per_parametro|personalizzato
        ref_id (int|null): flag_turno.id per tipo=per_flag
        pesi (dict): {ore, target, festivi, peso, varieta, desiderata}

    Returns:
        201: { ok, preset: {...} }
    """
    dati = request.get_json(silent=True) or {}
    nome = (dati.get('nome') or '').strip()
    tipo = dati.get('tipo', '')
    ref_id = dati.get('ref_id')
    pesi = dati.get('pesi', {})

    if not nome:
        return jsonify({'ok': False, 'errore': 'Nome obbligatorio.'}), 400

    tipi_validi = {'completo', 'per_flag', 'per_parametro', 'personalizzato'}
    if tipo not in tipi_validi:
        return jsonify({'ok': False, 'errore': f'Tipo non valido: {tipo}'}), 400

    if tipo == 'per_flag':
        if ref_id is None:
            return jsonify({'ok': False, 'errore': 'ref_id obbligatorio per tipo=per_flag.'}), 400
        flag = query_one("SELECT id FROM flag_turno WHERE id=?", (ref_id,))
        if not flag:
            return jsonify({'ok': False, 'errore': f'Flag {ref_id} non trovato.'}), 400

    # Duplicato?
    dup = query_one("SELECT id FROM preset_ottimizzazione WHERE nome=?", (nome,))
    if dup:
        return jsonify({'ok': False, 'errore': f'Nome "{nome}" gia\' in uso.'}), 400

    max_ordine = query_one("SELECT MAX(ordine) AS m FROM preset_ottimizzazione")
    ordine = (max_ordine['m'] or 0) + 10 if max_ordine else 10

    cursor = execute_write(
        "INSERT INTO preset_ottimizzazione (nome, tipo, ref_id, pesi, ordine) "
        "VALUES (?, ?, ?, ?, ?)",
        (nome, tipo, ref_id if tipo == 'per_flag' else None,
         json.dumps(pesi, ensure_ascii=False), ordine)
    )
    nuovo = query_one("SELECT * FROM preset_ottimizzazione WHERE id=?", (cursor.lastrowid,))
    p = dict(nuovo)
    try:
        p['pesi'] = json.loads(p['pesi'] or '{}')
    except (json.JSONDecodeError, TypeError):
        p['pesi'] = {}

    return jsonify({'ok': True, 'preset': p}), 201


@bp.route('/preset-ottimizzazione/<int:preset_id>', methods=['PUT'])
@require_role('admin')
def aggiorna_preset_ottimizzazione(preset_id):
    """
    Aggiorna un preset ottimizzazione esistente.

    Body JSON: stessi campi di POST + is_active (opzionale).
    """
    esistente = query_one("SELECT * FROM preset_ottimizzazione WHERE id=?", (preset_id,))
    if not esistente:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404

    dati = request.get_json(silent=True) or {}
    nome = (dati.get('nome') or '').strip() or esistente['nome']
    tipo = dati.get('tipo', esistente['tipo'])
    ref_id = dati.get('ref_id', esistente['ref_id'])
    pesi = dati.get('pesi')
    is_active = dati.get('is_active', esistente['is_active'])
    ordine = dati.get('ordine', esistente['ordine'])

    tipi_validi = {'completo', 'per_flag', 'per_parametro', 'personalizzato'}
    if tipo not in tipi_validi:
        return jsonify({'ok': False, 'errore': f'Tipo non valido: {tipo}'}), 400

    if tipo == 'per_flag':
        if ref_id is None:
            return jsonify({'ok': False, 'errore': 'ref_id obbligatorio per tipo=per_flag.'}), 400
        flag = query_one("SELECT id FROM flag_turno WHERE id=?", (ref_id,))
        if not flag:
            return jsonify({'ok': False, 'errore': f'Flag {ref_id} non trovato.'}), 400

    # Duplicato nome?
    dup = query_one(
        "SELECT id FROM preset_ottimizzazione WHERE nome=? AND id!=?",
        (nome, preset_id)
    )
    if dup:
        return jsonify({'ok': False, 'errore': f'Nome "{nome}" gia\' in uso.'}), 400

    pesi_json = json.dumps(pesi, ensure_ascii=False) if pesi is not None else esistente['pesi']

    execute_write(
        "UPDATE preset_ottimizzazione SET nome=?, tipo=?, ref_id=?, pesi=?, "
        "is_active=?, ordine=? WHERE id=?",
        (nome, tipo, ref_id if tipo == 'per_flag' else None,
         pesi_json, is_active, ordine, preset_id)
    )

    aggiornato = query_one("SELECT * FROM preset_ottimizzazione WHERE id=?", (preset_id,))
    p = dict(aggiornato)
    try:
        p['pesi'] = json.loads(p['pesi'] or '{}')
    except (json.JSONDecodeError, TypeError):
        p['pesi'] = {}

    return jsonify({'ok': True, 'preset': p}), 200


@bp.route('/preset-ottimizzazione/<int:preset_id>', methods=['DELETE'])
@require_role('admin')
def elimina_preset_ottimizzazione(preset_id):
    """
    Elimina un preset ottimizzazione.
    I preset con is_default=1 non possono essere eliminati (solo disattivati).
    """
    esistente = query_one("SELECT * FROM preset_ottimizzazione WHERE id=?", (preset_id,))
    if not esistente:
        return jsonify({'ok': False, 'errore': 'Preset non trovato.'}), 404
    if esistente['is_default']:
        return jsonify({
            'ok': False,
            'errore': 'Preset di default non eliminabile. Usa is_active=0 per disattivarlo.'
        }), 400

    execute_write("DELETE FROM preset_ottimizzazione WHERE id=?", (preset_id,))
    return jsonify({'ok': True}), 200
