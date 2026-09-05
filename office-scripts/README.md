# Office Scripts

Gli script che girano dentro Excel, sul modello prodotto da
`genera_config_turni.py`.

## Installazione

Gli script non stanno dentro il file `.xlsx`: vivono nel OneDrive di chi
li crea, sotto `Documenti/Office Scripts`, e si condividono con la
cartella di lavoro. Per installarne uno:

1. Apri `modello_config.xlsx` (da OneDrive o SharePoint, non da disco).
2. Scheda **Automatizza** → **Nuovo script**.
3. Incolla il contenuto di `solver_turni.ts` e salva col nome
   `Solver turni`.
4. **Condividi** lo script con la cartella di lavoro, cosi' lo trovano
   anche gli altri che la aprono.

Serve una licenza Microsoft 365 commerciale. La scheda Automatizza
compare in Excel per il web, per Windows (versione 2210 o superiore) e
per Mac.

## `solver_turni.ts`

Riempie le celle vuote del foglio `Calendario`.

**Non tocca le celle gia' scritte.** Chi programma decide a mano i turni
che vuole controllare, lancia il solver, e quello completa il resto.
Rilanciarlo non disfa niente, e le assegnazioni manuali contano per
l'equilibrio del carico esattamente come le altre.

L'ordine di lavoro:

1. i turni fissi di `T_PostiFissi`, che sono decisioni gia' prese
2. i turni obbligatori, dal piu' necessario
3. i turni opzionali, finche' resta gente disponibile

Per ogni cella scarta chi non e' ammissibile e sceglie, fra i rimasti,
il punteggio migliore.

**Divieti** (non negoziabili): un turno al giorno a testa; la notte non
sta con nient'altro lo stesso giorno; il giorno dopo la notte si riposa;
chi ha chiesto un'assenza non viene assegnato; i `mai` e i `solo` di
`T_Preferenze`; i tetti di `T_Tetti`; il vincolo di presidio.

**Punteggio** (piu' alto vince): desiderata centrato, chi e' indietro coi
turni dovuti, presidio proprio, piu' i pesi di `evita` e `preferisci`
presi da `T_Parametri`.

I turni di una sede con `conta_nei_dovuti = NO` — le aggiuntive — non
concorrono all'equilibrio del carico.
