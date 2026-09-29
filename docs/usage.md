# Uso

## Avviare un nuovo progetto

1. Crea una cartella di lavoro dedicata, fuori da questo repository e fuori
   da repository pubblici (conterrà dati riservati).
2. Apri Claude Code in quella cartella.
3. Invoca la skill:

   ```text
   /business-plan-orchestrator <descrizione della tua idea>
   ```

   oppure descrivi l'idea in linguaggio naturale chiedendo di strutturarla in
   un business plan.

La skill crea `<cartella di lavoro>/<slug-del-progetto>/` con la cartella
`00_idea-discovery/` e la cartella `shared/` dei registri.

## Lo Stage 0 e il prompt contract

Lo Stage 0 trasforma l'idea grezza in un concept strutturato:

1. registra l'idea **testualmente** in `raw-idea.md`;
2. fa uno step-back e un reverse prompting per far emergere ciò che manca;
3. ti pone domande mirate (ruolo `founder-interviewer`);
4. classifica la startup (tipo, stadio, lettore primario, tipo di funding,
   orizzonte);
5. prepara il **prompt contract**: obiettivo, destinatario, output,
   perimetro, regole su fonti e assunzioni, criteri di approvazione.

Le cartelle degli stage successivi vengono create **solo dopo** che approvi
il prompt contract.

## Lavorare stage per stage

Ogni stage segue lo stesso schema:

```text
domande mirate → subagent a runtime → proposta nel candidate
→ validator deterministici → decision gate → commit del transaction manager → handoff
```

- I subagent scrivono solo in `<stage>/.working/<tx>/` (il **candidate**).
- I validator verificano il candidate; se falliscono, nulla viene scritto
  nei file canonici e ti viene spiegato che cosa correggere.
- Il **transaction manager** è l'unico a scrivere i file canonici
  (`structured-output.json`, registri in `shared/`), in modo atomico e con
  journal di recovery.
- Il **decision gate** chiude lo stage con `approved`,
  `approved_with_conditions` (con condizioni `COND-*` da chiudere entro uno
  stage indicato), `needs_revision` o `blocked`.

Per l'elenco degli stage e dei loro gate vedi [`workflow.md`](workflow.md).

## Riprendere in una nuova sessione

Apri Claude Code nella stessa cartella di lavoro e invoca di nuovo la skill.
L'orchestratore legge `shared/project-status.md`, i registri e l'ultimo
`handoff.md`, e riprende da `next_action` senza riaprire stage già
approvati.

## Valori in conflitto: `INCOERENZA RILEVATA`

Ogni numero o claim rilevante vive in un unico registro
(`shared/assumptions-register.json`). Se proponi un valore diverso da quello
registrato, l'orchestratore **non lo scrive**: mostra un blocco

```text
INCOERENZA RILEVATA

ID: ISSUE-<n>
Variabile: <nome>
Valore A: <valore> (<file>)
Valore B: <valore> (<file>)
...
```

e attende una tua conferma esplicita **in un messaggio successivo**. Solo
allora aggiorna la stessa voce `ASS-*`, conserva lo storico e registra la
decisione.

## Modificare un'assunzione già confermata

Le assunzioni confermate non si modificano a mano. L'orchestratore usa il
comando `update-assumption` del transaction manager, che prima del commit
riesegue i controlli d'impatto sugli stage già chiusi: se la modifica rompe
un vincolo già verificato, nulla viene scritto e ti viene mostrato il
conflitto.

## Output

A fine percorso trovi:

- `output/business-plan.md` — il business plan in diciassette capitoli;
- `10_financial-plan/financial-plan.md` e `10_financial-plan/financial-model.xlsx`;
- `11_funding-request/funding-request.md`;
- `12_data-room/data-room-index.md`;
- i registri in `shared/`.

Ogni valore del documento finale è tracciato alla sua fonte canonica; le
assunzioni portano sempre la loro etichetta epistemica e le lacune della data
room restano visibili.

## Buone pratiche

- Rispondi con dati veri quando li hai e dichiara quando non li hai: la skill
  registra `missing_information` invece di inventare.
- Tieni le prove (interviste, preventivi, contratti) dentro la cartella del
  progetto: la data room le indicizza dove sono, senza copiarle.
- Non modificare a mano i file canonici, `output/business-plan.md` o gli
  handoff: le modifiche manuali rompono la tracciabilità e vengono segnalate
  dai validator come incoerenze.
- Tratta il risultato come una bozza da verificare, non come consulenza.

## Esempio

In [`examples/fictional-startup/`](../examples/fictional-startup/) trovi un
progetto fittizio completato fino allo Stage 9. Copialo in una cartella di
lavoro e invoca la skill per proseguire dallo Stage 10.
