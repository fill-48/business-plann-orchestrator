# Workflow 07 — Go-to-market (Stage 6, `06_go-to-market/`)

> Numerazione dei file: **Stage 6** → cartella `06_go-to-market/` → questo
> workflow (`07_go-to-market.md`). Metodologia on-demand:
> [`methodology/go-to-market.md`](../methodology/go-to-market.md) +
> [`methodology/evidence-framework.md`](../methodology/evidence-framework.md).
> Subagent: [`runtime-agents/go-to-market-analyst.md`](../runtime-agents/go-to-market-analyst.md).
>
> Da questo stage è attivo `validate_funnel_arithmetic` (solo stage 6),
> oltre a `validate_unit_economics`, `validate_cross_stage_consistency`
> (stage 5–6) e `validate_market_arithmetic` (stage 4–6) — matrice di
> enforcement in `config/enforcement-config.json`.
> Qui si chiude la catena causale: il funnel deve **alimentare** le unit
> economics dello Stage 5 e reggere il confronto col SOM dello Stage 4
> (ciclo di conflitto).
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
  --project "<project>" --stage 06_go-to-market --phase ingress
```

Lo Stage 5 deve essere `approved*` e in `completed_stages`; una `COND-`
open dovuta produce exit 1 `condition_due`. Poi:

```bash
python "<skill_dir>/transaction/transaction_manager.py" governance-status \
  --project "<project>" \
  --updates '{"status": "in_progress", "current_task": "stage-6-go-to-market"}' \
  --reason "ingress Stage 6 autorizzato dai validator"
```

## Passo 2 — Metodologia on-demand

Leggi `methodology/go-to-market.md` ora. Il prezzo e il margine sono già
canonici: il funnel li **referenzia** (`pricing_ref` = lo stesso `ASS-*`
del business model), non li ridefinisce.

## Passo 3 — Subagent nel candidate workspace

Lancia `go-to-market-analyst` a runtime (contratto di
[`reference/architecture.md`](../reference/architecture.md) §11.2), unico
percorso
scrivibile:

```text
<project>/06_go-to-market/.working/<tx>/
```

Output attesi: `structured-output.json` (`sales_funnel` con `leads_ref`,
`stages[]` con un `rate_ref` per ogni tasso, `customers_out_ref`,
`spend_ref`, `cac_ref`, `churn_ref`, `capacity_revenue_ref`,
`pricing_ref`), `proposed-assumptions.json` (lead, tassi ratio in [0,1],
spesa S&M, CAC e capacità come `P-ASS-*` derivati con
`derivation.variables` esplicite), `research.md`, `analysis.md` (canali e
capacità reale), `section-draft.md`, `handoff.md`.

## Passo 4 — Validazione candidate

```bash
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/06_go-to-market/.working/<tx>" \
  --stage 06_go-to-market --phase candidate
```

## Passo 5 — QA di stage e criteri di completezza

`stage-qa.md` nel candidate, criteri:

1. funnel completo: lead → tassi per passaggio → clienti; ogni tasso è un
   `ASS-`/`P-ASS-` ratio in [0,1], `customers_out` = lead × Π(tassi);
2. **CAC con un funnel dietro**: `CAC = spend / customers_out`
   (EUR/count), mai un CAC dichiarato senza meccanica;
3. churn esplicito (mai ignorato: falsa retention e LTV);
4. capacità dei canali realistica: `capacity_revenue` =
   clienti sostenibili × valore annuo — è il numero che regge (o no) il
   SOM dello Stage 4;
5. stesso prezzo canonico dello Stage 5 (`pricing_ref` identico).

## Passo 6 — Egress e applicazione transazionale

Tutti i validator applicabili allo Stage 6 (matrice di enforcement in
`config/enforcement-config.json`):

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --candidate "<project>/06_go-to-market/.working/<tx>" \
  --stage 06_go-to-market --phase egress
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/06_go-to-market/.working/<tx>" \
  --stage 06_go-to-market --phase egress
python "<skill_dir>/validators/validate_market_arithmetic.py" \
  --project "<project>" --candidate "<project>/06_go-to-market/.working/<tx>" \
  --stage 06_go-to-market --phase egress
python "<skill_dir>/validators/validate_unit_economics.py" \
  --project "<project>" --candidate "<project>/06_go-to-market/.working/<tx>" \
  --stage 06_go-to-market --phase egress
python "<skill_dir>/validators/validate_funnel_arithmetic.py" \
  --project "<project>" --candidate "<project>/06_go-to-market/.working/<tx>" \
  --stage 06_go-to-market --phase egress
python "<skill_dir>/validators/validate_cross_stage_consistency.py" \
  --project "<project>" --candidate "<project>/06_go-to-market/.working/<tx>" \
  --stage 06_go-to-market --phase egress
```

Codici tipici di `validate_funnel_arithmetic`:
`funnel_product_mismatch`, `cac_mismatch`, `rate_out_of_bounds`,
`missing_required` (churn), `unit_mismatch`/`value_mismatch` (ricalcolo
DSL). Di `validate_cross_stage_consistency`: `price_divergence` (prezzo
diverso dallo Stage 5) e **`gtm_capacity_below_som`** — il detect del
ciclo di conflitto. Exit 1 → correggi il candidate e ripeti.

### Ciclo di conflitto — tensione SOM ↔ capacità GTM (mai riscrittura silenziosa)

Se `gtm_capacity_below_som`:

1. **BLOCK**: nessuna applicazione canonica (il transaction manager
   respinge); lo stage non avanza;
2. **conflict**: apri il conflitto sull'`ASS-*` del SOM (`INCOERENZA
   RILEVATA`) e porta lo stato a `conflict_awaiting_confirmation` via
   `governance-status`;
3. **confirm**: attendi la conferma esplicita dell'utente in un **turno
   successivo** (risposta ambigua/assente → resta in attesa; rifiuto →
   `needs_revision`, si corregge il funnel);
4. **history**: la modifica confermata passa dal **comando transazionale
   `update-assumption`**, mai da un edit dei registri e mai da una
   scrittura mediata dall'orchestratore. Procedura:

   a. leggi il record corrente e il suo fingerprint con
      `python "<skill_dir>/transaction/transaction_manager.py" show-assumption --project <project> --assumption ASS-nnn`
      (read-only, nessun lock): il campo `record_hash` è
      l'`expected_record_hash` del passo successivo;
   b. prepara **un solo** file `--changes` con l'`ASS-*` del SOM **e i suoi
      driver** nella stessa transazione (mai due transazioni separate):

      ```json
      {
        "operation_id": "<token opaco della conferma>",
        "reason": "CHANGE_CONFIRMED: capacita' GTM reale inferiore al SOM",
        "decision": {
          "decision_type": "assumption_update",
          "options_considered": "...", "motivation": "...",
          "impact": "...", "approver": "founder"
        },
        "changes": [
          {"assumption_id": "ASS-002",
           "expected_record_hash": "<da show-assumption>",
           "updates": {"value": 0.08}},
          {"assumption_id": "ASS-011",
           "expected_record_hash": "<da show-assumption>",
           "updates": {"value": 800000}}
        ]
      }
      ```

   c. esegui `python "<skill_dir>/transaction/transaction_manager.py"
      update-assumption --project <project> --changes <file>`.

   Il comando fa da solo, nella stessa transazione recuperabile: CAS sul
   record atteso (`stale_record_hash` se qualcuno l'ha cambiato nel
   frattempo), append di `previous_values`, allocazione del `DEC-*` dal
   `decisions-register`, riga derivata nel decision-log, risoluzione dello
   stato `conflict_awaiting_confirmation`, evento di audit e — punto 5 —
   la matrice impact **prima** del commit. `operation_id` rende il comando
   idempotente: un retry con lo stesso payload risponde `already_applied`
   senza scrivere due volte;
5. **impact**: **non va eseguita a mano**. `update-assumption`
   esegue la matrice `--phase impact` sulla finestra `4..current_stage` su
   una copia del progetto con i valori proposti, **prima** di toccare il
   canonico: se la catena resta rotta l'esito è `impact_validation_failed`
   e il canonico resta byte-identico. Un esito `applied` significa che la
   matrice era verde;
6. **resubmit**: riporta lo stato a `in_progress` e rivaluta il gate.

Tutti exit 0 → applica e avanza:

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage \
  --project "<project>" --stage 06_go-to-market \
  --candidate "<project>/06_go-to-market/.working/<tx>" \
  --gate-result approved
```

## Passo 7 — Verifica post-commit e handoff

Dopo `"result": "applied"`: `current_stage` = `07_operations-and-ip`,
`completed_stages` include `06_go-to-market`. Il funnel canonico (clienti,
CAC, churn, capacità dei canali) è il volume che l'operating model dello
Stage 7 dovrà reggere. Azione successiva: `workflows/08_operations-and-ip.md`
(Stage 7).

## Resume

Come per gli stage precedenti (`recover` → catena di ripresa di
[`reference/architecture.md`](../reference/architecture.md) §13.3 →
`next_action`).
Dopo qualunque modifica canonica confermata su SOM, prezzo o funnel,
riesegui la matrice `--phase impact` sugli Stage 4–6 prima di proseguire.
