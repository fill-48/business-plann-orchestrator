# Workflow 06 — Business model (Stage 5, `05_business-model/`)

> Numerazione dei file: **Stage 5** → cartella `05_business-model/` → questo
> workflow (`06_business-model.md`). Metodologia on-demand:
> [`methodology/business-model.md`](../methodology/business-model.md) +
> [`methodology/evidence-framework.md`](../methodology/evidence-framework.md).
> Subagent: [`runtime-agents/business-model-analyst.md`](../runtime-agents/business-model-analyst.md).
>
> Da questo stage sono attivi i validator di dominio
> `validate_unit_economics` (stage 5–6) e `validate_cross_stage_consistency`
> (stage 5–6), oltre a `validate_market_arithmetic` (stage 4–6) — matrice di
> enforcement in `config/enforcement-config.json`.
> **Nessuna proiezione finanziaria**: solo driver come assunzioni.
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
  --project "<project>" --stage 05_business-model --phase ingress
```

Lo Stage 4 deve essere `approved*` e in `completed_stages`; una `COND-`
open con `due_before_stage: 05_business-model` produce exit 1
`condition_due`. Poi:

```bash
python "<skill_dir>/transaction/transaction_manager.py" governance-status \
  --project "<project>" \
  --updates '{"status": "in_progress", "current_task": "stage-5-business-model"}' \
  --reason "ingress Stage 5 autorizzato dai validator"
```

## Passo 2 — Metodologia on-demand

Leggi `methodology/business-model.md` ora. Prima di proporre qualunque
valore quantitativo, esegui la verifica di persistenza sul registro
(`🔍 Verifica persistenza`, SKILL.md): il prezzo discusso a Stage 3–4 può
già esistere come `ASS-*` — in quel caso si **referenzia**, mai si
duplica.

## Passo 3 — Subagent nel candidate workspace

Lancia `business-model-analyst` a runtime (contratto di
[`reference/architecture.md`](../reference/architecture.md) §11.2), unico
percorso scrivibile:

```text
<project>/05_business-model/.working/<tx>/
```

Output attesi: `structured-output.json` (`business_model` con
`pricing_ref`, `revenue_ref`, `contribution_margin_ref`, ricorrenza e
canale; l'eventuale `price` duplicato **deve** coincidere con
l'ASS-pricing), `proposed-assumptions.json` (prezzo, costi variabili
unitari, driver di volume e derivati come `P-ASS-*` con
`derivation.variables` esplicite), `research.md`, `analysis.md`,
`section-draft.md`, `handoff.md`.

## Passo 4 — Validazione candidate

```bash
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/05_business-model/.working/<tx>" \
  --stage 05_business-model --phase candidate
```

## Passo 5 — QA di stage e criteri di completezza

`stage-qa.md` nel candidate, criteri:

1. prezzo netto = **un solo** `ASS-` (`pricing_ref`), strettamente
   positivo, con composizione esplicita;
2. ricavo = **formula di driver** (`revenue_ref` derived con `variables`),
   mai un numero scritto a mano;
3. contribution margin **calcolato**: `prezzo − Σ(costi variabili
   unitari)`, col pricing tra le `variables`; un margine negativo è un
   rosso metodologico da motivare (`negative_margin`);
4. ricorrenza e meccanica di monetizzazione esplicite;
5. nessuna proiezione pluriennale: solo driver as-assumptions.

Un margine "a parole" o un prezzo divergente da un `ASS-*` canonico →
`INCOERENZA RILEVATA` (protocollo SKILL.md), nessuna scrittura.

## Passo 6 — Egress e applicazione transazionale

Tutti i validator applicabili allo Stage 5 (matrice di enforcement in
`config/enforcement-config.json`):

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --candidate "<project>/05_business-model/.working/<tx>" \
  --stage 05_business-model --phase egress
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/05_business-model/.working/<tx>" \
  --stage 05_business-model --phase egress
python "<skill_dir>/validators/validate_market_arithmetic.py" \
  --project "<project>" --candidate "<project>/05_business-model/.working/<tx>" \
  --stage 05_business-model --phase egress
python "<skill_dir>/validators/validate_unit_economics.py" \
  --project "<project>" --candidate "<project>/05_business-model/.working/<tx>" \
  --stage 05_business-model --phase egress
python "<skill_dir>/validators/validate_cross_stage_consistency.py" \
  --project "<project>" --candidate "<project>/05_business-model/.working/<tx>" \
  --stage 05_business-model --phase egress
```

Codici tipici di `validate_unit_economics`: `price_not_positive`,
`price_conflict` (prezzo duplicato ≠ ASS-pricing: è un **conflitto**, mai
una media), `revenue_not_derived`, `margin_not_derived`,
`margin_missing_price`, `value_mismatch`/`unit_mismatch` (ricalcolo DSL);
warning `negative_margin`. `validate_cross_stage_consistency` a Stage 5
verifica il mercato canonico e segnala il funnel come `not_yet_required`
(il CAC è dovuto a Stage 6, mai un FAIL anticipato). Exit 1 → correggi il
candidate e ripeti; mai ritoccare i registri canonici a mano.

Tutti exit 0 → applica e avanza:

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage \
  --project "<project>" --stage 05_business-model \
  --candidate "<project>/05_business-model/.working/<tx>" \
  --gate-result approved
```

(`approved_with_conditions` + `proposed-conditions.json` per gap tracciati,
es. prezzo da validare con i primi clienti.)

## Passo 7 — Verifica post-commit e handoff

Dopo `"result": "applied"`: `current_stage` = `06_go-to-market`,
`completed_stages` include `05_business-model`. Il pricing canonico
(`ASS-*` allocato) è il **solo** prezzo che lo Stage 6 potrà referenziare
(`price_divergence` altrimenti); il contribution margin alimenterà il
confronto con il CAC del funnel.

Azione successiva: `workflows/07_go-to-market.md` (Stage 6).

## Resume

Come per gli stage precedenti (`recover` → catena di ripresa di
[`reference/architecture.md`](../reference/architecture.md) §13.3 →
`next_action`).
Dopo qualunque modifica canonica confermata che tocca prezzo o costi,
riesegui `validate_unit_economics --phase impact` su `05_business-model`
(e la matrice impact a valle) prima di proseguire.
