# Workflow — Stage 13 · `13_document-generation`

> **Numerazione dei file.** Il workflow `NN_…` serve lo stage `NN-1`: questo
> file, `14_document-generation.md`, è il workflow dello **Stage 13**. Non
> esiste alcuno Stage 14: lo Stage 13 è l'**ultimo** stage di `stage_order` e
> il suo `advance-stage` porta il progetto allo **stato terminale** del piano.

Stage: `13_document-generation` · Runtime-agent: `business-plan-writer` ·
Metodologia: [`methodology/document-generation.md`](../methodology/document-generation.md) ·
Schema: [`schemas/document-generation.schema.json`](../schemas/document-generation.schema.json)

Lo Stage 13 è un **assemblatore**, non un nuovo stadio di ragionamento.
Compone il business plan finale — **diciassette capitoli** in ordine fisso —
esclusivamente dai canonici JSON degli Stage 1–12 e dai registri di
`shared/`. Non fa ricerca, non stima, non ricalcola il modello finanziario,
non cambia la funding request, non riscrive la Data Room e non promuove mai
un'assunzione a fatto. Ogni carattere del documento è **verbatim canonico**,
**modello costante** privo di cifre o **letterale legato** `BND-*`.

Segnaposto dei comandi: `<skill_dir>` è la directory che contiene `SKILL.md`
(normalmente `~/.claude/skills/business-plan-orchestrator`); `<project>` è la
cartella del progetto nella working directory dell'utente; `<tx>` è
l'identificatore della transazione, un singolo segmento di path.

---

## Passo 1 — Precondizioni e apertura, senza un passo d'ingresso fittizio

Lo Stage 12 `12_data-room` è in `completed_stages` e `current_stage` è
`13_document-generation`. Questo workflow **non** invoca `validate_stage_gate`
né `validate_referential_integrity`: quei validator dichiarano gli stage 1–9
e rispondono con un errore d'uso su ogni altro stage. Il gate d'ingresso è
il costruttore del Passo 3, che respinge una catena incompleta (`docgen_chain_incomplete`) prima
di qualunque scrittura. Lo stato attivo dello stage si apre con il transaction
manager:

```bash
python "<skill_dir>/transaction/transaction_manager.py" governance-status --project <project> --updates '{"status": "in_progress", "current_task": "document-generation"}' --reason "avvio dello Stage 13"
```

## Passo 2 — La proposta del writer, nel solo candidate

Il runtime-agent `business-plan-writer` legge i canonici in sola lettura e
scrive **una sola** cosa:

```text
<project>/13_document-generation/.working/<tx>/document-proposal.json
```

La proposta è conforme a `$defs.proposal` dello schema e **seleziona**, non
scrive: la data dichiarata `as_of` (nessun orologio è letto), un'etichetta di
versione **priva di cifre** e, facoltativamente, al più cinque milestone
`MIL-*` della roadmap e cinque claim `CLM-*` **supportati** della Data Room da
mettere in evidenza nell'executive summary. Senza `highlights` vale la
selezione di default: le prime cinque milestone per data obiettivo e i primi
cinque claim supportati.

## Passo 3 — Costruzione deterministica

```bash
python "<skill_dir>/validators/validate_document_generation.py" --build --project <project> --tx <tx>
```

Il costruttore legge gli ingressi, esegue i controlli `XS-01`…`XS-12`,
assembla i capitoli 2–17 e **per ultimo** l'executive summary, rende il
Markdown in memoria, applica i quality gate, verifica che ogni file del
progetto fuori dal candidate sia **byte-identico** prima e dopo, e solo allora
pubblica in modo **atomico** il candidate (`structured-output.json`,
`handoff.md`). Un rifiuto è attribuito con un codice `docgen_*` o `path_escape`
e non pubblica nulla; le incoerenze fra valori (ingresso diverso da quello
pinnato dalla Data Room, base finanziaria stantia) sono riportate nel formato
`INCOERENZA RILEVATA`. Un registro modificato dopo la Data Room è un
**WARNING** divulgato nel documento, non un blocco.

## Passo 4 — Egress, nella forma reale del transaction manager

```bash
python "<skill_dir>/validators/validate_document_generation.py" --project <project> --candidate <project>/13_document-generation/.working/<tx> --stage 13_document-generation --phase egress
```

L'egress **ricostruisce** il documento dagli ingressi e dalla proposta e lo
confronta byte per byte con il candidate; rilegge ogni letterale legato dalla
sua foglia sorgente; verifica etichette epistemiche, stato dei claim,
disclosure e quality gate della resa.

Exit `≠ 0` ⇒ **stop**: nessuna scrittura canonica, solo governance.

## Passo 5 — Transazione canonica terminale

L'unico scrittore canonico è il transaction manager, che riesegue da sé
l'egress sullo snapshot del candidate:

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage --project <project> --stage 13_document-generation --candidate <project>/13_document-generation/.working/<tx> --gate-result approved
```

Lo Stage 13 è l'ultimo stage di `stage_order` ed è il `release_boundary`: il
commit porta il progetto allo **stato terminale** del piano —
`13_document-generation` in `completed_stages`, `current_stage` invariato,
`status` `approved`, `current_task` `plan-complete` e un `next_action` di
piano completato; l'uscita del transaction manager porta `"advanced_to":
null` e `"completed": true`. Da qui `apply` e `advance-stage` rispondono
`stage_already_completed` e `governance-status` non riapre lo stage.

## Passo 6 — Pubblicazione del business plan

```bash
python "<skill_dir>/validators/validate_document_generation.py" --publish --project <project>
```

Solo con il predicato terminale vero: rende il canonico **committato** e
scrive **solo** `output/business-plan.md`, con sha256 uguale a
`rendering.markdown_sha256`. È idempotente; se il file esiste ed è diverso
risponde `docgen_output_stale` senza toccarlo.

## Passo 7 — Verifica di impatto sul canonico pubblicato

```bash
python "<skill_dir>/validators/validate_document_generation.py" --project <project> --stage 13_document-generation --phase impact
```

Il documento è un'**istantanea datata** (`as_of` più le impronte degli
ingressi): un valore di registro cambiato dopo il completamento è un
**WARNING**, mai un `FAIL`; handoff e derivato, fuori dalla
validation view, sono `NOT_APPLICABLE` con motivo.

## Passo 8 — Chiusura

Comunica al founder che il business plan è **completo** e pubblicato in
`output/business-plan.md`. Dichiara che la review finale avversariale non è
stata eseguita (il review loop finale non è incluso in v0.7.1) e che PDF e
DOCX non sono disponibili: la numerazione è logica e non ci sono numeri di
pagina. Rigenerare il documento richiede il protocollo di riapertura dello
stage terminale, che non è incluso in v0.7.1.

---

## Ripresa

| Stato osservato | Azione |
|---|---|
| `current_stage` 13, nessun candidate | Passo 1 |
| candidate presente, non committato | rieseguire Passo 3 e Passo 4 |
| journal non terminale | `recover` del transaction manager |
| stato terminale, derivato assente | Passo 6 |
| stato terminale, derivato presente e identico | nulla: piano completo |
| stato terminale, derivato presente e diverso | Passo 6 risponde `docgen_output_stale`: riportare al founder |

## Anti-pattern

- scrivere prosa nuova, «migliorare» un testo approvato o riassumerlo;
- ricalcolare, arrotondare o convertire un numero, o leggerlo da un
  derivato Markdown o dal workbook;
- presentare un valore di assunzione senza la sua etichetta epistemica;
- mettere in evidenza un claim non supportato o contestato;
- omettere una condizione aperta, un claim non supportato o un conflitto
  della Data Room per rendere il documento «più pulito»;
- modificare a mano il canonico, l'handoff o `output/business-plan.md`;
- simulare numeri di pagina o annunciare un PDF che non esiste.
