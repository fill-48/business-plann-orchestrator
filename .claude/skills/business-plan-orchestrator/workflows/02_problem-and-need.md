# Workflow 02 — Problema e bisogno (Stage 1, `01_problem-and-need/`)

> Numerazione dei file: **Stage 1** → cartella `01_problem-and-need/` → questo
> workflow (`02_problem-and-need.md`). Metodologia on-demand:
> [`methodology/problem-and-need.md`](../methodology/problem-and-need.md) +
> [`methodology/evidence-framework.md`](../methodology/evidence-framework.md).
> Subagent: [`runtime-agents/customer-problem-analyst.md`](../runtime-agents/customer-problem-analyst.md).
>
> `<skill_dir>` = directory che contiene `SKILL.md` (normalmente
> `~/.claude/skills/business-plan-orchestrator`; contiene `validators/` e
> `transaction/`). `<project>` = cartella del progetto nella working
> directory dell'utente, mai dentro `<skill_dir>`.

## Invarianti transazionali (non negoziabili)

1. **Nessuna scrittura canonica manuale.** L'unico scrittore canonico è
   `transaction/transaction_manager.py`. L'orchestratore non modifica mai a
   mano `shared/`, `structured-output.json` canonici o `project-status.md`
   (le transizioni operative passano da `governance-status`).
2. **Validator exit ≠ 0 ⇒ stop**: niente transaction manager, niente
   avanzamento, `project-status` invariato. Sono ammesse solo le scritture
   di governance: report in area generata, audit, conflict record,
   stato operativo via `governance-status`.
3. **Exit code**: `1` = candidate non valido (correggere e rivalidare);
   `2` = invocazione errata (bug del workflow, non del candidate);
   `3` = stato canonico/journal corrotto (fermarsi e riportare all'utente).

## Passo 0 — Recovery preventivo

Prima di ogni sessione di stage, sana eventuali transazioni interrotte:

```bash
python "<skill_dir>/transaction/transaction_manager.py" recover --project "<project>"
```

## Passo 1 — Ingress gate

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --stage 01_problem-and-need --phase ingress
```

- exit 0 → ingresso autorizzato (Sezione 0 approvata, nessuna COND dovuta).
- exit 1 → riporta gli errori all'utente e fermati (nessuna creazione file).
- Poi apri lo stage (unica scrittura ammessa, via governance):

```bash
python "<skill_dir>/transaction/transaction_manager.py" governance-status \
  --project "<project>" \
  --updates '{"status": "in_progress", "current_task": "stage-1-problem"}' \
  --reason "ingress Stage 1 autorizzato dai validator"
```

## Passo 2 — Carica la metodologia (on-demand)

Leggi `methodology/problem-and-need.md` ora — non prima, non per altri
stage (politica di caricamento del contesto,
[`reference/architecture.md`](../reference/architecture.md) §20).

## Passo 3 — Lancia il subagent nel candidate workspace

Genera un transaction id (`<tx>` = timestamp+random) e lancia
`customer-problem-analyst` **a runtime** con il contratto del suo file
(chiavi di [`reference/architecture.md`](../reference/architecture.md) §11.2),
indicando Stage 1 come stage attivo e come **unico percorso
scrivibile** il candidate workspace:

```text
<project>/01_problem-and-need/.working/<tx>/
```

Output attesi nel candidate: `structured-output.json` (problem_statement),
`section-draft.md`, `proposed-assumptions.json` (ogni valore quantitativo
come `P-ASS-*`, mai numeri inline), `handoff.md`. Il subagent non tocca
`shared/`, non alloca `ASS-*`, non approva gate.

## Passo 4 — Validazione candidate (durante la produzione)

```bash
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/01_problem-and-need/.working/<tx>" \
  --stage 01_problem-and-need --phase candidate
```

Exit 1 → correggi il candidate (nuova iterazione del subagent sui punti
segnalati), rivalida. Mai "sistemare a mano" i file canonici.

## Passo 5 — QA di stage e criteri di completezza

Compila `stage-qa.md` **nel candidate** rispondendo ai criteri:

1. problema misurabile e falsificabile;
2. ≥1 evidenza classificata (o gap `missing_information` esplicito);
3. percepito vs dimostrato esplicito (`perceived_vs_demonstrated`);
4. alternative/status quo valutati.

Criteri parzialmente mancanti ma correggibili → stato `needs_revision`
(via `governance-status`) e nuova iterazione. Problema non falsificabile o
zero evidenze senza gap dichiarato → `blocked` e riporta all'utente.

## Passo 6 — Egress e applicazione transazionale

Esegui **tutti** i validator applicabili (matrice di enforcement in
`config/enforcement-config.json`) in fase egress:

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --candidate "<project>/01_problem-and-need/.working/<tx>" \
  --stage 01_problem-and-need --phase egress
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/01_problem-and-need/.working/<tx>" \
  --stage 01_problem-and-need --phase egress
```

Solo con **tutti exit 0**, applica e avanza nella **stessa transazione
recuperabile** (il transaction manager riesegue comunque i validator sullo
snapshot: validation binding):

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage \
  --project "<project>" --stage 01_problem-and-need \
  --candidate "<project>/01_problem-and-need/.working/<tx>" \
  --gate-result approved
```

Con criticità tracciabili (COND con owner/severity/due) usa
`--gate-result approved_with_conditions` e includi
`proposed-conditions.json` nel candidate. Su `rejected`: interpreta il
report, nessuna scrittura canonica è avvenuta; correggi e ripeti.

## Passo 7 — Verifica post-commit e handoff

Dopo `"result": "applied"`:

- `current_stage` = `02_customer-segmentation`, `completed_stages` include
  `01_problem-and-need` (verificato leggendo `project-status.md`);
- `01_problem-and-need/structured-output.json` e `handoff.md` canonici
  scritti dal transaction manager con i `P-ASS-*` sostituiti dagli `ASS-*`
  allocati (mappa in `pass_map` dell'output);
- comunica all'utente gli `ASS-*` allocati e l'azione successiva
  (`workflows/03_customer-segmentation.md`).

## Incoerenze e conflitti

La Regola di persistenza di `SKILL.md` resta attiva: un valore che
contraddice un `ASS-*` canonico apre `INCOERENZA RILEVATA`
(`conflict_awaiting_confirmation` via `governance-status`), turni separati,
mai media/refuso/silenzio. Il candidate resta in `.working/` finché il
conflitto non è risolto.

## Resume

Se la sessione riprende con `current_stage: "01_problem-and-need"`:
`recover` (Passo 0) → rileggi `project-status.md`, l'ultimo `handoff.md` di
Sezione 0 e gli output del candidate se presenti → riprendi dal passo
coerente con `next_action`. Stage `approved*` non si riaprono senza
`ISSUE-` (gestione delle incoerenze,
[`reference/architecture.md`](../reference/architecture.md) §15).
