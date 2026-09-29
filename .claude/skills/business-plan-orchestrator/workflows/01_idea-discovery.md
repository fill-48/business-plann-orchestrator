# Workflow 01 — Idea discovery (Sezione 0)

> Flow obbligatorio
> ([`reference/architecture.md`](../reference/architecture.md) §8.2): raw-idea
> → step-back →
> reverse-prompting → domande mirate → classificazione → prompt-contract →
> concept consolidato → registri iniziali → gate → (se approvato) creazione
> sezioni successive → handoff.
>
> Precondizione: `00_project-initialization.md` già eseguito (esiste
> `<slug>/00_idea-discovery/` e `<slug>/shared/`).

## Regola di persistenza (obbligatoria, si applica a **ogni** passo di questo workflow)

> Perché questa forma: una verifica sparsa su più file, senza un passo
> visibile obbligatorio, non basta a impedire una sovrascrittura silenziosa
> né un mismatch di ID (un'assunzione citata con un ID diverso da quello
> effettivamente scritto). Questa regola previene entrambi ancorando il
> controllo a **un solo file meccanicamente verificabile** e rendendo il
> controllo un **passo visibile obbligatorio**, non un ragionamento interno
> facoltativo.

Questa regola si applica insieme al protocollo a stati vincolante in
`checks/persistence-conflict-protocol.json`. Il protocollo distingue quattro
casi che non vanno confusi:

- `NO_CONFLICT`: valore menzionato ma non ancora persistito; valore gia'
  persistito con lo stesso contenuto; o precisazione non confliggente.
- `CONFLICT_DETECTED_AWAITING_CONFIRMATION`: sostituzione proposta di un
  valore ufficiale gia' persistito.
- `CHANGE_REJECTED_OR_UNCONFIRMED`: risposta ambigua, non confermativa o
  rifiuto dopo un conflitto rilevato.
- `CHANGE_CONFIRMED`: conferma esplicita arrivata in un turno utente
  successivo, riferita alla stessa variabile e ai valori vecchio/nuovo.

La proposta della modifica e la conferma non possono essere ricavate dallo
stesso turno utente. Durante `CONFLICT_DETECTED_AWAITING_CONFIRMATION` non
esiste nessuna eccezione: non aggiornare `assumptions-register.json`, non
scrivere il nuovo valore in file di prosa, non appendere una decisione finale
al `decision-log.md`, non propagare il valore a concept, prompt contract,
sezioni o output. Lo stato di attesa e' conversazionale: se il contesto viene
perso, ricostruisci il conflitto dal registro ufficiale e chiedi di nuovo la
conferma invece di scrivere.

### Regola A — un solo registro autorevole, consultato con un passo visibile

`shared/assumptions-register.json` è l'**unica fonte da consultare** per
sapere se un valore quantitativo o un claim rilevante è già stato fissato
(Principio 2: un solo assumptions-register.json ufficiale). Ogni valore
quantitativo o claim rilevante che emerge in conversazione va registrato
**per primo** in `assumptions-register.json` — non solo in prosa
(`founder-answers.md`, `brainstorming-log.md`, `startup-concept.md`), che
possono seguire ma non sostituire questa registrazione.

**Prima di scrivere un valore quantitativo o un claim rilevante in
qualunque file**, esegui — e mostra esplicitamente all'utente nella tua
risposta, non solo internamente — questo passo:

```text
🔍 Verifica persistenza — variabile: <nome variabile>
   Ricerca in shared/assumptions-register.json per category "<categoria>"...
   → Nessuna voce trovata: prima persistenza, procedo con ASS-<nuovo id>.
   OPPURE
   → Trovata ASS-<id esistente> con valore <X>: [nessuna divergenza — riuso ASS-<id>]
     oppure [divergenza — vedi Regola B sotto]
```

Questo passo **non è opzionale e non va saltato silenziosamente**: se lo
salti, un futuro controllo (umano o automatico) deve poterlo notare dalla
tua stessa risposta.

### Regola B — cosa fare in base al risultato della ricerca

1. **Nessuna voce esistente per questa categoria/variabile**: è la prima
   persistenza. Crea una nuova voce in `assumptions-register.json` con il
   prossimo ID libero e procedi direttamente — nessuna cerimonia necessaria.
2. **Voce esistente trovata, stesso valore**: nessuna incoerenza. Riusa
   l'ID esistente in ogni riferimento successivo (prosa, messaggi,
   `decision-log.md`) — non crearne uno nuovo per la stessa variabile.
3. **Voce esistente trovata, valore diverso**: **non scrivere né propagare
   nulla**. Mostra il blocco `INCOERENZA RILEVATA` (formato in `SKILL.md`)
   usando **l'ID esistente** trovato al passo di ricerca (mai un ID nuovo),
   con Valore A = valore già in `assumptions-register.json`, Valore B =
   valore nuovo appena fornito. **Attendi conferma esplicita dell'utente**
   su quale valore è quello ufficiale, prima di scrivere o modificare
   qualunque file — inclusi `founder-answers.md`, `startup-concept.md`,
   `prompt-contract.md`. Una frase contenuta nello stesso turno della proposta
   non vale come conferma: rispondi con `INCOERENZA RILEVATA`, chiedi conferma
   in un turno successivo, e ferma le scritture.

### Regola C — coerenza degli ID (obbligatoria)

L'ID di assunzione citato in **qualunque** messaggio rivolto all'utente o in
qualunque file deve corrispondere **esattamente** all'ID della voce
effettivamente scritta o aggiornata in `assumptions-register.json` in quel
turno. Non citare mai un ID diverso da quello realmente toccato. Se stai
aggiornando un'assunzione esistente, riusa il suo ID — **non crearne mai una
seconda voce per la stessa variabile** (produrrebbe un mismatch di ID: uno
`statement` che riferisce un ID e un messaggio operativo che ne cita un
altro).

**Esempio concreto:**
l'utente indica un prezzo di 4,99€. Non esiste ancora una voce
`assumptions-register.json` per "pricing" → crei `ASS-002` con valore
4,99€, e lo citi come `ASS-002` ovunque. In un messaggio successivo l'utente
dice "in realtà il prezzo è 7,99€". Cerchi in `assumptions-register.json`
per category "pricing" → trovi `ASS-002` con 4,99€ → valore diverso → mostri
`INCOERENZA RILEVATA` (ID: ISSUE-progressivo, Variabile: prezzo, Valore A:
4,99€ [ASS-002], Valore B: 7,99€, …) e attendi conferma. Se l'utente conferma
7,99€, **aggiorni la stessa voce ASS-002** (non crei ASS-004) e citi
`ASS-002` nel messaggio operativo di conferma.

**Risposte non confermative:** frasi come "capisco", "ok", "valutiamolo",
"ha senso", o qualunque risposta che non confermi esplicitamente la
sostituzione della stessa variabile dal valore A al valore B non autorizzano
scritture. Classificale come `CHANGE_REJECTED_OR_UNCONFIRMED`: il valore
persistito resta invariato e non viene aggiunta una decisione finale.

**Invarianti da rispettare sempre durante la risoluzione:**

- `raw-idea.md` non viene mai riscritto (resta l'unica fonte del testo
  originale verbatim, comprese le versioni "superate" delle cifre).
- La risoluzione va registrata in `decision-log.md` come decisione esplicita
  (quale valore è ufficiale e perché, quale ID di assunzione riguarda), non
  come correzione silenziosa.
- La tracciabilità resta intatta: non cancellare la versione precedente dai
  log (`brainstorming-log.md`, `founder-answers.md`) — annotala come
  superata, non eliminarla.
- Il valore risolto **non** viene automaticamente promosso a `validated` in
  `assumptions-register.json`: una correzione del founder resta comunque una
  `founder_assumption`/`unvalidated`, a meno che non arrivi una prova esterna
  reale (vedi `methodology/evidence-framework.md`).

## Passo 1 — Raccogliere l'idea grezza

Chiedi all'utente di descrivere l'idea, senza forzare un formato. Scrivi il
testo **verbatim** in `00_idea-discovery/raw-idea.md`. Non riformulare, non
"migliorare" il testo in questo passo — la rielaborazione avviene nei passi
successivi, in modo tracciabile.

Aggiorna `shared/project-status.md`: `current_task: "step-back"`.

## Passo 2 — Step-back analysis

Runtime-check già fatto in Workflow 00. Se `step_back.mode == "skill"`, invoca
`/step-back-prompting` sul testo di `raw-idea.md`. Se `mode == "fallback"`,
segui `fallbacks/step-back-prompting.md` (che impone di dichiarare il fallback
all'utente).

Scrivi il risultato in `00_idea-discovery/brainstorming-log.md`
(`templates/brainstorming-log.md` → sezione 2).

## Passo 3 — Reverse prompting

Stessa logica: se `reverse_prompting.mode == "skill"`, invoca
`/reverse-prompting`; altrimenti `fallbacks/reverse-prompting.md`.

Obiettivo: far emergere le assunzioni implicite dell'idea grezza tramite
domande mirate all'utente. Scrivi domande/risposte in `brainstorming-log.md`
→ sezione 3.

**Ogni volta che una risposta introduce un valore quantitativo o un claim
rilevante** (prezzo, capacità, percentuale, tempistica...), applica **prima**
la Regola A/B/C di persistenza qui sopra (verifica visibile in
`assumptions-register.json`, poi scrivi lì per primo) — **solo dopo**
riporta il valore anche in `brainstorming-log.md`. Non scrivere mai il
valore solo in prosa senza la corrispondente voce nel registro.

## Passo 4 — Domande mirate (subagent `founder-interviewer`)

Lancia il subagent **a runtime** usando il contratto in
`runtime-agents/founder-interviewer.md`. Passa come `required_inputs`
esattamente i file elencati in quel contratto (non l'intero progetto — politica
di caricamento del contesto,
[`reference/architecture.md`](../reference/architecture.md) §20).

Il subagent produce una bozza di:
- `00_idea-discovery/founder-answers.md`
- una proposta per `startup-concept.md` e `startup-profile.json`

**L'orchestratore, non il subagent**, valida la proposta di `startup-profile`
contro `schemas/startup-profile.schema.json` prima di scriverla in
`shared/startup-profile.json` ([`reference/architecture.md`](../reference/architecture.md)
§11.4: i subagent non sovrascrivono i registri
condivisi senza validazione).

Se l'utente fornisce **due valori** per la stessa variabile durante
l'intervista, il subagent non sceglie e non scrive: segnala all'orchestratore,
che applica la Regola A/B/C di persistenza (ricerca in
`assumptions-register.json`, apre `INCOERENZA RILEVATA` con l'ID esistente se
un valore era già lì) e chiede all'utente di decidere prima di scrivere
qualunque file.

Se l'utente **non fornisce dati sufficienti** su una dimensione, marcala
`missing_information`, aggiungila a `shared/open-questions.md`, e prosegui:
non bloccare l'intero flow per un singolo gap non critico.

## Passo 5 — Classificazione della startup

Usa `methodology/startup-classification.md` per finalizzare le 5 dimensioni e
compilare `shared/startup-profile.json` (validato contro schema). Registra
`dominant_metrics` e `classification_confidence`.

Aggiorna `shared/project-status.md`: `current_task: "prompt-contract"`.

## Passo 6 — Concept consolidato

Sintetizza in `00_idea-discovery/startup-concept.md` (2-4 paragrafi): problema,
cliente, soluzione, evidenze principali, classificazione, capitale/orizzonte.
Deve essere leggibile da chi non ha seguito la sessione — è la base per il
prompt contract.

## Passo 7 — Prompt contract

Se `prompt_contracts.mode == "skill"`, invoca `/prompt-contracts`; altrimenti
segui `fallbacks/prompt-contracts.md`. In entrambi i casi il contratto finale
usa i 16 campi di `templates/prompt-contract.md` e viene scritto in
`00_idea-discovery/prompt-contract.md`.

**Presenta il contratto all'utente e attendi approvazione esplicita.** Se
l'utente chiede modifiche, aggiorna e richiedi nuova approvazione. Non passare
al Passo 8 finché lo stato non è `approved`.

## Passo 8 — Registri iniziali (verifica di completezza)

Se hai seguito la Regola A/B/C ai Passi 3-4, `assumptions-register.json` è
già stato popolato **incrementalmente** man mano che emergevano i valori —
questo passo è una verifica di completezza, non la prima occasione per
scriverlo. Controlla che in `shared/` siano popolati almeno:

- `assumptions-register.json`: le assunzioni critiche emerse (≥1 se l'idea ne
  contiene, altrimenti `[]` è accettabile solo se genuinamente non ce ne sono).
  Se trovi valori quantitativi in `founder-answers.md`/`startup-concept.md`
  **senza** una voce corrispondente qui, è un difetto da correggere prima di
  procedere (non un caso normale).
- `evidence-register.json`: le evidenze raccolte, correttamente classificate.
- `risk-register.json`: eventuali rischi già evidenti in questa fase (può
  restare `[]` in Sezione 0 se non emergono rischi specifici).
- `decision-log.md`: la decisione di approvazione del prompt contract, come
  voce (DEC-001 o successivo), più ogni decisione di risoluzione incoerenza
  presa ai Passi precedenti.

## Passo 9 — Decision gate

Decision gate della Sezione 0
([`reference/architecture.md`](../reference/architecture.md) §8.6).

La Sezione 0 può chiudersi **solo se tutti** questi criteri sono veri:

1. Il concept è comprensibile (`startup-concept.md` completo e coerente).
2. La tipologia di startup è classificata (`startup-profile.json` valido).
3. Il destinatario del piano è identificato (`primary_reader` non vuoto).
4. Gli output richiesti sono definiti (campo 3 del prompt contract).
5. Le assunzioni iniziali sono registrate (`assumptions-register.json`
   coerente con quanto discusso).
6. I principali data gap sono espliciti (`open-questions.md` aggiornato).
7. Il prompt contract è `approved`.

Se **anche uno solo** manca, lo stage resta `needs_revision` o `blocked` —
**non creare** le cartelle successive. Riporta all'utente quale criterio manca
e cosa serve per soddisfarlo.

Se tutti i criteri sono veri:

1. Crea, dentro `<project_slug>/`, le cartelle:
   `01_problem-and-need/ … 12_data-room/`, `review/`, `output/`
   (struttura canonica di
   [`reference/architecture.md`](../reference/architecture.md) §9 — vuote,
   nessun file dentro: i loro contenuti sono prodotti dai workflow dei
   rispettivi stage, attraverso il transaction manager).
2. Aggiorna `shared/project-status.md`:
   `current_stage: "01_problem-and-need"`, `status: "not_started"`,
   `completed_stages: ["00_idea-discovery"]`,
   `next_action: "Avviare Stage 1 — Problema e bisogno"`.
3. Registra la decisione di approvazione in `decision-log.md`.

## Passo 10 — Handoff

Scrivi `00_idea-discovery/handoff.md` usando `templates/section-handoff.md`,
compilando tutte le 11 sezioni. Questo file è ciò che una nuova sessione legge
per riprendere senza rifare la Sezione 0 da capo.

## Gestione delle incoerenze durante il flow

Vedi "Regola di persistenza" in cima a questo file: quella regola è **attiva
in ogni passo**, non solo a valle. In sintesi — un valore non ancora scritto
in nessun file può essere corretto direttamente; un valore già scritto in
**almeno un file** del progetto, se contraddetto da un valore nuovo, richiede
**sempre** il blocco `INCOERENZA RILEVATA` (formato in `SKILL.md`) e
un'attesa di conferma esplicita **prima** di scrivere o propagare il nuovo
valore in qualunque file. Non mediare, non scegliere il dato più recente, non
trattarlo come refuso: la decisione spetta all'utente, e va registrata in
`decision-log.md` una volta presa.

La conferma deve arrivare in un turno utente successivo e deve essere
esplicita. Se il turno successivo e' ambiguo o non confermativo, lo stato e'
`CHANGE_REJECTED_OR_UNCONFIRMED`: non scrivere nulla e lascia invariato il
valore ufficiale. Solo `CHANGE_CONFIRMED` autorizza aggiornamento della stessa
voce `ASS-*`, storico del valore precedente, decision log e propagazione.

## Resume — ripresa in una nuova sessione

Se `shared/project-status.md` esiste già con `current_stage: "00_idea-discovery"`:

1. Leggi, in ordine: `project-status.md` → `project-config.json` →
   `assumptions-register.json` → `evidence-register.json` → `decision-log.md`
   → l'ultimo `00_idea-discovery/handoff.md` → gli output già presenti in
   `00_idea-discovery/`.
2. Riprendi dal passo indicato in `next_action` — non ripetere i passi già
   completati (verificabili dai file già scritti) senza un motivo esplicito.
3. Se `current_stage` è già `"01_problem-and-need"` (o oltre), la Sezione 0 è
   chiusa: non riaprirla. Prosegui con il workflow dello stage corrente
   (`workflows/02_problem-and-need.md` per lo Stage 1; la tabella di
   instradamento è in `SKILL.md`).
