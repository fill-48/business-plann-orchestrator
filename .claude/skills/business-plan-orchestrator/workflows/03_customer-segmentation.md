# Workflow 03 — Customer segmentation (Stage 2, `02_customer-segmentation/`)

> Numerazione dei file: **Stage 2** → cartella `02_customer-segmentation/` →
> questo workflow (`03_customer-segmentation.md`). Metodologia on-demand:
> [`methodology/customer-segmentation.md`](../methodology/customer-segmentation.md) +
> [`methodology/evidence-framework.md`](../methodology/evidence-framework.md).
> Subagent: [`runtime-agents/customer-problem-analyst.md`](../runtime-agents/customer-problem-analyst.md)
> (stesso agent di Stage 1, stage-bounded: qui lavora **solo** su Stage 2).
>
> Invarianti transazionali, semantica degli exit code e regole di
> conflitto: identiche a `02_problem-and-need.md` → «Invarianti
> transazionali». Qui non si ripetono.
>
> `<skill_dir>` = directory che contiene `SKILL.md` (normalmente
> `~/.claude/skills/business-plan-orchestrator`); `<project>` = cartella del
> progetto nella working directory dell'utente.

## Passo 0 — Recovery preventivo

```bash
python "<skill_dir>/transaction/transaction_manager.py" recover --project "<project>"
```

## Passo 1 — Ingress gate

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --stage 02_customer-segmentation --phase ingress
```

Exit 0 richiede Stage 1 in `completed_stages` con gate `approved*` e
nessuna COND aperta dovuta. Poi:

```bash
python "<skill_dir>/transaction/transaction_manager.py" governance-status \
  --project "<project>" \
  --updates '{"status": "in_progress", "current_task": "stage-2-segments"}' \
  --reason "ingress Stage 2 autorizzato dai validator"
```

## Passo 2 — Metodologia on-demand

Leggi `methodology/customer-segmentation.md` ora. Input canonici di
riferimento: `01_problem-and-need/structured-output.json` (il problema) e
gli `ASS-*`/`EVD-*` già registrati.

## Passo 3 — Subagent nel candidate workspace

Lancia `customer-problem-analyst` a runtime (contratto di
[`reference/architecture.md`](../reference/architecture.md) §11.2), stage
attivo
Stage 2, unico percorso scrivibile:

```text
<project>/02_customer-segmentation/.working/<tx>/
```

Output attesi: `structured-output.json` (`customer_segments` con id
`SEG-*`, ruoli user/buyer/decision maker/influencer/payer/gatekeeper,
`problem_ref`, `beachhead` con `selection_criteria`), `section-draft.md`,
`proposed-assumptions.json` (`P-ASS-*` per numerosità/spesa dei segmenti),
`handoff.md`.

## Passo 4 — Validazione candidate

```bash
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/02_customer-segmentation/.working/<tx>" \
  --stage 02_customer-segmentation --phase candidate
```

I `SEG-*` referenziano `ASS-*`/`EVD-*`/`P-ASS-*` — mai numeri replicati
(ogni valore vive in un solo identificatore). Exit 1 → iterazione
correttiva del subagent, poi rivalidare.

## Passo 5 — QA di stage e criteri di completezza

`stage-qa.md` nel candidate, criteri:

1. ≥1 segmento prioritario **ancorato** al problema di Stage 1
   (`problem_ref` + `problem_fit` non generico);
2. ruoli separati — buyer e user distinti o coincidenza dichiarata;
3. beachhead con criterio esplicito (`selection_criteria`);
4. gap di evidenza sui segmenti dichiarati, non nascosti.

Buyer/user confusi o beachhead senza criterio → `blocked`; segmento
senza evidenza → `needs_revision` o COND tracciata
(`approved_with_conditions`).

## Passo 6 — Egress e applicazione transazionale

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --candidate "<project>/02_customer-segmentation/.working/<tx>" \
  --stage 02_customer-segmentation --phase egress
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/02_customer-segmentation/.working/<tx>" \
  --stage 02_customer-segmentation --phase egress
```

Tutti exit 0 → applica e avanza:

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage \
  --project "<project>" --stage 02_customer-segmentation \
  --candidate "<project>/02_customer-segmentation/.working/<tx>" \
  --gate-result approved
```

(`approved_with_conditions` + `proposed-conditions.json` nel candidate se
restano COND tracciate.) Su `rejected`: solo governance, correggi il
candidate e ripeti.

## Passo 7 — Verifica post-commit e handoff

Dopo `"result": "applied"`: `current_stage` =
`03_value-proposition`, `completed_stages` include
`02_customer-segmentation`, `SEG-*` canonici scritti con i riferimenti
`ASS-*` sostituiti. Azione successiva:
`workflows/04_value-proposition.md`.

## Resume

Come per Stage 1: `recover`, rilettura catena (`project-status.md` →
ultimo `handoff.md` → candidate eventuale), ripresa da `next_action`,
nessuna riapertura di stage `approved*` senza `ISSUE-`.
