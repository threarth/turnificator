# Backlog

Lavoro concordato e non ancora fatto, con quanto serve per riprenderlo a
freddo. Le decisioni già prese stanno in fondo: sono il contesto senza cui le
voci qui sopra si rifanno sbagliate.

---

## 1. Fasce «solo su richiesta» e composizione — ~~interfaccia e solver~~ fatto

Fatto. Restano due code, in fondo a questa voce.

- **Interfaccia**: la sezione Fasce è uscita da `ConfigurazioneGuidata` ed è
  `SezioneFasce.svelte`. Ha la casella «Su richiesta» per riga e, sotto la
  riga, l'editor della composizione — impostabile, non derivata.
- **API**: POST e PUT scrivono `componenti` (prima li leggeva solo la GET).
  Una PUT che non ne parla lascia la composizione com'è.
- **Snapshot**: `solo_su_richiesta` e `flag_composizione` sono nello snapshot
  del calendario, e `snap_flag_map` li restituisce con la mappa.
- **Solver**: filtro hard sulle fasce riservate; `copertura_richiesta()` in
  `fasce_orarie.py` risponde `match` / `parziale` / `mismatch` ed è l'unico
  punto dove la domanda si fa, usato da validatori, solver e colore cella.

La semantica scelta — soddisfatta solo a composizione intera — sta fra le
decisioni, in fondo.

### Code

- **La composizione non si propone.** `solo_su_richiesta` viaggia con le
  proposte del master, `flag_composizione` no: è una tabella di sole coppie di
  id, senza nome, e il meccanismo delle proposte va per nome. Servirebbe una
  parte a sé, che traduce le coppie in nomi e le ritraduce all'arrivo.
- **Le funzioni lunghe si sono allungate.** `crea_config_snapshot`,
  `valida_assegnazione`, `get_disponibili`, `modifica_flag_turno` e
  `_migra_flag_e_regole` erano già oltre le 40 righe e hanno preso qualche
  riga in più. Nessuna è stata spezzata: è una refattorizzazione da fare
  apposta, non di straforo.

---

## 2. Pagina di riepilogo sotto il calendario

Specifica presa da `esempio.xlsx.xlsx` (foglio `Inserimento`, righe 137-180, e
foglio `Riepilogo`). Va **sotto la griglia del calendario**, nella pagina
manager.

### I blocchi, come sono nel foglio

| Blocco | Righe |
|---|---|
| Turni feriali e festivi | notti feriali, notti festive, giorni feriali, giorni festivi, turni 12h |
| Solo weekend | diurni sab/dom, notti sab, notti dom, **ore** |
| Globale | lavorati, assenze giustificate, totale — con «TURNI DA SVOLGERE: n» nel titolo |
| Per struttura (foglio `Riepilogo`) | lavoratori in riga, strutture in colonna, più `AGGIUNT.` e `TOTALE` |
| Per settimana | settimane in colonna, lavoratori in riga, riga con i **dovuti di quella settimana**, colonna `TOT` |

### Regole di calcolo

- **Si contano i pesi, non le righe**: una lunga o una notte valgono 2.
  È già come il solver confronta il fatto con il dovuto.
- **Ore del weekend**: la notte scavalca la mezzanotte e va spezzata sui due
  giorni. Per `notte 20:00-08:40`: **240 minuti** sul giorno di inizio,
  **520 + la pausa** sul giorno dopo. Si deriva dagli orari della fascia,
  senza inchiodare niente: se `orario_fine < orario_inizio` la fascia
  scavalca.
  Esempio dell'utente: notte del venerdì → il sabato prende 8h40 (+10);
  notte della domenica → domenica 4h, lunedì 8h40 (+10).
- I dovuti per settimana escono da `calendario_giorni.classifica_giorno`,
  contando i giorni lavorativi della settimana (lunedì-domenica).

---

## 3. Minori, concordati

- **Delta turni con le frecce**: `max_n_turni_mese` esiste come vincolo
  globale; manca il controllo +/- nell'interfaccia.
- **Dire chi usa cosa** nelle intestazioni delle sezioni guidate:
  *impostazioni per il solver* (solo su richiesta), *regole* (solver **e**
  visualizzazione dei turni), *vincoli* (solo solver).

---

## 4. Debiti tecnici noti, non urgenti

- **Due convenzioni per il giorno della settimana**: `0 = lunedì` nel solver
  e in `calendario_giorni`, `0 = domenica` nei conteggi del context menu e
  nella pagina manager. Non è stata unificata: cambiarla tocca dati salvati.
- **`ConfigurazioneGuidata.svelte` è sulle 730 righe.** Tipologie, assenze,
  regole, giorni, conteggi, persone e ora fasce sono componenti a sé.
  Restano inline strutture e turni, che condividono l'array `strutture` e
  vanno passate con `bind:`.
- **I flag di serie stanno in due posti**: `migrations/init_db.sql` e
  `CONCETTI_ROOT` / `FASCE_DEFAULT` in `app/__init__.py`. Per i tipi
  richiesta la duplicazione è già stata tolta, per i flag no.

---

## Decisioni prese, da non rifare

**Un tenant, una configurazione.** Nessun selettore dentro il tenant: la
configurazione manuale scrive sulle tabelle vive. Il multi sta sul master, che
tiene configurazioni di riferimento e le **propone** ai tenant — non le impone.

**Le proposte vanno per nome, mai per id.** Due tenant hanno id diversi per la
stessa fascia. Vale anche per i riferimenti fra tabelle, che si riagganciano
in un secondo giro quando i flag proposti esistono. Si propongono solo
vocabolario e regole: struttura turni, persone, vincoli e conteggi restano del
posto.

**Festivi e superfestivi non sono mai turni dovuti.** Lavorare un festivo è
sempre un turno *in più*, che matura un recupero. Non c'è un'opzione: la
scelta non esiste.

**`flag_composizione` serve solo alla soddisfacibilità di una richiesta.**
Durata, ore e peso restano derivati dagli orari e non si leggono mai da lì:
era la confusione fra le due cose a renderla una fonte di divergenze la prima
volta che è esistita. La migrazione `_rimuovi_colonna_entita` **non deve**
cancellarla — lo faceva, e cancellava la tabella a ogni avvio.

**Una composizione è soddisfatta solo quando è intera.** Chi ha chiesto la
lunga e ha ricevuto la sola mattina non è in errore: gli manca un pezzo. Lo
dice `desiderata_composizione_parziale`, un tipo di regola con stile e gravità
configurabili come gli altri, che **non blocca** — se bloccasse, il
riempimento scarterebbe quella mattina e la composizione non si formerebbe
mai. Per lo stesso motivo l'optimizer la esclude dalle regole bloccanti.
Sparisce da sé quando arriva il pezzo che manca, perché
`_ricalcola_conflitti_vicini` rivaluta lo stesso lavoratore su ieri/oggi/domani
a ogni salvataggio.

**Tre nomi sono strutturali**: `turno_tipo`, `notturno`, `diurno`. Il codice
li cerca per nome. `guardia_24h` non lo è.

**Il turno tipo** si modifica nella durata, non nel nome, e non si elimina.

**Un solo modo per dire che una persona non fa un turno**: il limite per
utente a zero. `esclusioni_utente` è stata rimossa perché diceva la stessa
cosa.

**Ogni calendario porta il proprio snapshot** della configurazione, ed è il
motivo per cui modificarla non riscrive il passato. Ore, regole e tipi
richiesta leggono da lì; chi legge dal vivo torna a divergere.
