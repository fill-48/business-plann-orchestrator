# Workflow — Stage 12 · `12_data-room`

> **Numerazione dei file.** Il workflow `NN_…` serve lo stage `NN-1`: questo
> file, `13_data-room.md`, è il workflow dello **Stage 12**, non dello
> Stage 13. È la stessa convenzione per cui `workflows/12_funding-request.md`
> serve lo Stage 11. Il prefisso `13_` non rende questo file un artefatto
> dello Stage 13 `13_document-generation`, servito da
> `workflows/14_document-generation.md`.

Stage: `12_data-room` · Runtime-agent: `evidence-analyst` ·
Metodologia: [`methodology/data-room.md`](../methodology/data-room.md) ·
Schema: [`schemas/data-room.schema.json`](../schemas/data-room.schema.json)

La Data Room è lo **strato di evidenza dell'intero business plan**, non un
contenitore di allegati della funding request. **Indicizza** le prove già
prodotte dagli Stage 0–11 e i file forniti dall'utente ai loro path relativi
**esistenti**, e registra la tracciabilità claim → evidenza di ogni
affermazione materiale del piano. Non genera, non copia, non sposta e non
riscrive alcun file indicizzato.

Segnaposto dei comandi: `<skill_dir>` è la directory che contiene `SKILL.md`
(normalmente `~/.claude/skills/business-plan-orchestrator`); `<project>` è la
cartella del progetto nella working directory dell'utente; `<tx>` è
l'identificatore della transazione, un singolo segmento di path.

---

## Passo 1 — Precondizioni, senza un passo d'ingresso fittizio

Lo Stage 11 `11_funding-request` è in `completed_stages` e `current_stage` è
`12_data-room`. Questo workflow **non** invoca `validate_stage_gate` né
`validate_referential_integrity` sullo Stage 12: quei validator dichiarano gli
stage 1–9 e rispondono con un errore d'uso su ogni altro stage: invocarli
qui è un errore del workflow. Il gate d'ingresso della Data Room è
il costruttore del Passo 3, che respinge un ingresso incoerente **prima** di
qualunque pubblicazione.

## Passo 2 — La proposta dell'analista, nel solo candidate

Il runtime-agent `evidence-analyst` legge i registri condivisi e le uscite
degli stage in sola lettura e scrive **una sola** cosa:

```text
<project>/12_data-room/.working/<tx>/data-room-proposal.json
```

La proposta è conforme a `$defs.proposal` di
`schemas/data-room.schema.json` e dichiara: la data di riferimento `as_of` e
la soglia `max_age_days` (ingressi **dichiarati** della staleness, nessun
orologio è letto), i file forniti dall'utente da indicizzare, i documenti
attesi e non ancora disponibili, e i claim del piano con i loro legami alle
evidenze registrate (`supporting`, `contradicting`, `partial`, `missing`).
I claim si identificano con una chiave locale: gli identificatori `CLM-*`
sono allocati **solo** dal costruttore, nel canonico dello Stage 12.

## Passo 3 — Costruzione deterministica e indice derivato

```bash
python "<skill_dir>/validators/validate_data_room.py" --build --project <project> --tx <tx>
```

Il costruttore deriva il manifest (sezioni, documenti `DR-*`, checksum,
disponibilità, qualità delle fonti, indice delle evidenze, staleness,
lacune, conflitti, completezza, voci aperte, identità), lo valida con gli
**stessi** controlli dell'egress, verifica che ogni file del progetto fuori da
`12_data-room/` sia **byte-identico** prima e dopo, e solo allora pubblica in
modo **atomico** il candidate (`structured-output.json`, `handoff.md`) e
l'indice derivato `12_data-room/data-room-index.md`. Un rifiuto è attribuito
con un codice `data_room_*` e non pubblica nulla.

`<tx>` è un singolo segmento sicuro (`[A-Za-z0-9._-]`, senza separatori,
lettera di drive, `:` o punto finale). Prima di leggere la proposta e prima
di ogni scrittura il costruttore verifica che candidate e indice restino
sotto `12_data-room/`, senza attraversare symlink, junction o reparse point:
altrimenti il rifiuto è `path_escape` e nessun file è scritto. Le voci del
registro delle fonti che non sono file del progetto — URL, domini nudi,
DOI, citazioni — restano nel registro e non bloccano la costruzione; un path
va indicato nella sua grafia canonica su disco, e una fonte si dichiara una
sola volta.

## Passo 4 — Egress, nella forma reale del transaction manager

```bash
python "<skill_dir>/validators/validate_data_room.py" --project <project> --candidate <project>/12_data-room/.working/<tx> --stage 12_data-room --phase egress
```

L'egress verifica anche che l'handoff del candidate e l'indice derivato
siano la resa deterministica del manifest: un handoff assente, privato dei
blocchi `INCOERENZA RILEVATA` o con copertura e voci aperte diverse dal
manifest, o un indice modificato a mano, sono respinti.

Exit `≠ 0` ⇒ **stop**: nessuna scrittura canonica, solo governance.

## Passo 5 — Transazione canonica

L'unico scrittore canonico è il transaction manager, che riesegue da sé
l'egress sullo snapshot del candidate e pubblica il manifest e l'handoff:

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage --project <project> --stage 12_data-room --candidate <project>/12_data-room/.working/<tx> --gate-result approved
```

## Passo 6 — Verifica di impatto sul canonico pubblicato

```bash
python "<skill_dir>/validators/validate_data_room.py" --project <project> --stage 12_data-room --phase impact
```

In fase impact i controlli che richiedono file fuori dalla validation view
(fonti, handoff, derivati, indice) sono `NOT_APPLICABLE` con motivo, mai
`FAIL`; i registri condivisi, mutabili per transazione, sono verificati per
coerenza semantica e non per byte, e sono scanditi per i segreti insieme al
manifest e alle uscite canoniche della view.

## Passo 7 — Avanzamento allo Stage 13

Dopo l'`advance-stage`, `completed_stages` include `12_data-room`,
`current_stage` è `13_document-generation`, `status` è `not_started` e
`next_action` — calcolato dal transaction manager nella stessa transazione —
indica di avviarlo. Azione successiva:
[`workflows/14_document-generation.md`](14_document-generation.md)
(Stage 13), che assembla il business plan finale e lo chiude.

`release_boundary` vale `13_document-generation`, l'ultimo stage di
`stage_order`: lo Stage 13 è dentro il confine. Il transaction manager
risponde `stage_not_implemented` (exit `1`) solo a uno stage oltre il
confine, e nessuno stage del piano lo supera.

---

## Anti-pattern

- trattare la Data Room come la cartella degli allegati della funding request;
- copiare, rinominare o «normalizzare» un file dell'utente per indicizzarlo;
- creare cartelle fisiche per le undici sezioni;
- presentare un'assunzione del founder come evidenza di un claim;
- fondere due evidenze opposte nella più recente invece di aprire
  `INCOERENZA RILEVATA`;
- dichiarare una percentuale di copertura senza denominatore e distribuzione
  per classe;
- collegare due volte la stessa evidenza a un claim, o dichiarare due volte
  la stessa fonte;
- modificare a mano l'handoff canonico o l'indice derivato;
- dichiarare chiuso un debito perché ora compare in un indice.
