# Workflow 04 — Value proposition (Stage 3, `03_value-proposition/`)

> Numerazione dei file: **Stage 3** → cartella `03_value-proposition/` → questo
> workflow (`04_value-proposition.md`). Metodologia on-demand:
> [`methodology/value-proposition.md`](../methodology/value-proposition.md) +
> [`methodology/evidence-framework.md`](../methodology/evidence-framework.md).
> Subagent: [`runtime-agents/value-proposition-strategist.md`](../runtime-agents/value-proposition-strategist.md).
>
> Questo stage chiude con il **checkpoint evidenze**: è il gate che
> decide se la catena può proseguire verso mercato e concorrenza.
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
  --project "<project>" --stage 03_value-proposition --phase ingress
```

Poi:

```bash
python "<skill_dir>/transaction/transaction_manager.py" governance-status \
  --project "<project>" \
  --updates '{"status": "in_progress", "current_task": "stage-3-value-prop"}' \
  --reason "ingress Stage 3 autorizzato dai validator"
```

## Passo 2 — Metodologia on-demand

Leggi `methodology/value-proposition.md` ora. Input canonici:
`01_problem-and-need/structured-output.json`,
`02_customer-segmentation/structured-output.json` (i `SEG-*` e il
beachhead), registri `ASS-*`/`EVD-*`.

## Passo 3 — Subagent nel candidate workspace

Lancia `value-proposition-strategist` a runtime (contratto di
[`reference/architecture.md`](../reference/architecture.md) §11.2), unico
percorso scrivibile:

```text
<project>/03_value-proposition/.working/<tx>/
```

Output attesi: `structured-output.json` (`value_proposition` con id
`VP-*`, `segment_ref` ai `SEG-*`, `mapping` jobs/pains/gains ↔
relievers/creators, `switching_rationale`, `value_metrics` referenziate,
`proof_points` con `evidence_classification`), `section-draft.md`,
`proposed-assumptions.json` (ogni metrica quantificata come `P-ASS-*`,
mai cifre inline), `handoff.md` — e, se nessun proof point ha classe
validata, `proposed-conditions.json` con la COND di validazione.

## Passo 4 — Validazione candidate

```bash
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/03_value-proposition/.working/<tx>" \
  --stage 03_value-proposition --phase candidate
```

## Passo 5 — QA di stage, criteri di completezza e checkpoint evidenze

`stage-qa.md` nel candidate, criteri:

1. ogni gain/pain mappato dagli output di Stage 1–2 (riferimenti `SEG-*`);
2. ogni claim con proof point o marcato assunzione (6 classi esatte);
3. metrica di valore presente e referenziata (mai cifra inline);
4. switching rationale vs status quo di Stage 1.

Slogan senza metrica, o nessun proof né gap dichiarato → `blocked`.

## Passo 6 — Checkpoint evidenze + egress transazionale

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --candidate "<project>/03_value-proposition/.working/<tx>" \
  --stage 03_value-proposition --phase egress
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/03_value-proposition/.working/<tx>" \
  --stage 03_value-proposition --phase egress
```

`validate_stage_gate` in egress di Stage 3 applica il checkpoint leggendo
le classi di evidenza dei `proof_points`:

| Esito del checkpoint | Report | Azione |
|---|---|---|
| ≥1 proof point con classe validata (`verified_fact`/`internal_evidence`/`external_source` + `EVD-*`) | PASS | `advance-stage --gate-result approved` |
| solo classi non validate, ma COND idonea presente (canonica o `proposed-conditions.json`: `validation_action`, `owner`, `due_before_stage` a valle) | WARNING `evidence_unvalidated`, exit 0 | **obbligatorio** `advance-stage --gate-result approved_with_conditions` — mai `approved` con questo warning |
| solo classi non validate, nessuna COND idonea | FAIL `evidence_checkpoint`, exit 1 | stop: proponi la COND (o raccogli evidenze) e ripeti |

Applicazione (solo con tutti i validator exit 0):

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage \
  --project "<project>" --stage 03_value-proposition \
  --candidate "<project>/03_value-proposition/.working/<tx>" \
  --gate-result approved_with_conditions   # o approved, secondo la tabella
```

Il transaction manager rifiuta `approved_with_conditions` senza
`proposed-conditions.json` e riesegue comunque i validator sullo
snapshot. Su `rejected`: solo governance.

## Passo 7 — Verifica post-commit e handoff

Dopo `"result": "applied"`: `current_stage` = `04_market-and-competition`,
`completed_stages` include `03_value-proposition`; se
`approved_with_conditions`, la COND è nel `conditions-register.json`
canonico con `resolution_status: "open"` — **bloccherà l'ingresso dello
stage dovuto** (`due_before_stage`) finché non sarà `resolved`/`waived`
con `DEC-` tracciata. Comunicalo esplicitamente all'utente nel handoff,
insieme alla `validation_action` attesa e al suo owner.

Azione successiva: `workflows/05_market-and-competition.md` (Stage 4) —
che al Passo 1 troverà il blocco se la COND è ancora aperta.

## Resume

Come per gli stage precedenti. In più: se il gate era stato chiuso
`approved_with_conditions`, verifica lo stato delle COND **prima** di
proporre l'ingresso a Stage 4 — la risoluzione richiede evidenza
(`evidence_ref`) e decisione (`resolved_by: DEC-*`), registrate via
transazione di governance, mai un edit manuale del registro.
