# Backlog

Lavoro concordato e non ancora fatto, con quanto serve per riprenderlo a
freddo. Le decisioni già prese stanno in fondo: sono il contesto senza cui le
voci qui sopra si rifanno sbagliate.

---

## 1. Fasce «solo su richiesta» e composizione — interfaccia e solver

Database e API sono **già pronti** (commit `5356faa`):

- `flag_turno.solo_su_richiesta` — il solver non usa la fascia di sua
  iniziativa, la mette solo dove il lavoratore l'ha chiesta. È il caso della
  *lunga*.
- `flag_composizione (flag_id, componente_flag_id)` — quali fasce insieme
  soddisfano la richiesta di un'altra: chi chiede `L` può ricevere
  `mattina` + `pomeriggio`.
- `GET/POST/PUT /api/admin/flag-turno` leggono e scrivono entrambe;
  la GET restituisce `componenti` come array di id.

### Manca — interfaccia

Nella sezione **Fasce orarie** della configurazione guidata
(`ConfigurazioneGuidata.svelte`, blocco `sezioneCorrente === 'fasce'`, che è
ancora inline nel file):

- casella **«Solo su richiesta»** per riga;
- selezione delle fasce che la compongono — «la lunga è la somma di
  mattina + pomeriggio». Va **impostabile**, non derivata: è stata una
  richiesta esplicita.

### Manca — solver

1. **Solo su richiesta**: nel filtro hard delle celle
   (`solver.py`, `_esegui_assegnazione`, dove si scartano i candidati), se la
   fascia della cella ha `solo_su_richiesta` e il working desiderata del
   candidato non chiede quella fascia, il candidato non è ammissibile.
2. **Composizione**: la richiesta di `L` deve considerarsi soddisfatta se al
   lavoratore vengono assegnate le fasce che la compongono. Tocca il
   riconoscimento del mismatch — `_flag_nome_matcha` in `validatori.py` e la
   copia in-memory in `solver.py::_valida_conflitti_inmem` — che oggi
   confronta solo per discendenza, e `mattina` non discende da `lunga`.

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
- **`ConfigurazioneGuidata.svelte` è sulle 900 righe.** Tipologie, assenze,
  regole, giorni, conteggi, persone sono già componenti a sé; restano inline
  le tre storiche — fasce, strutture, turni. Fasce è la più facile da
  estrarre e non condivide stato; strutture e turni condividono l'array
  `strutture` e vanno passate con `bind:`.
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

**Tre nomi sono strutturali**: `turno_tipo`, `notturno`, `diurno`. Il codice
li cerca per nome. `guardia_24h` non lo è.

**Il turno tipo** si modifica nella durata, non nel nome, e non si elimina.

**Un solo modo per dire che una persona non fa un turno**: il limite per
utente a zero. `esclusioni_utente` è stata rimossa perché diceva la stessa
cosa.

**Ogni calendario porta il proprio snapshot** della configurazione, ed è il
motivo per cui modificarla non riscrive il passato. Ore, regole e tipi
richiesta leggono da lì; chi legge dal vivo torna a divergere.
