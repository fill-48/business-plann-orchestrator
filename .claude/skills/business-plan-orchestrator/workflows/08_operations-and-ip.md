# Workflow 08 — Operations e IP (Stage 7, `07_operations-and-ip/`)

> Numerazione dei file: **Stage 7** → cartella `07_operations-and-ip/` → questo
> workflow (`08_operations-and-ip.md`). Metodologia on-demand:
> [`methodology/operations-and-ip.md`](../methodology/operations-and-ip.md) +
> [`methodology/evidence-framework.md`](../methodology/evidence-framework.md).
> Subagent: [`runtime-agents/operations-ip-analyst.md`](../runtime-agents/operations-ip-analyst.md).
>
> Da questo stage è attivo `validate_operations_feasibility` (egress solo
> allo Stage 7; a 8–9 gira in impact), oltre a `validate_stage_gate`,
> `validate_referential_integrity` e `validate_cross_stage_consistency`
> (stage 5–9) — matrice di enforcement in `config/enforcement-config.json`.
> Qui l'operating model deve **reggere i volumi**
> del GTM (Stage 6) e **referenziare** i costi (COGS Stage 5) e i prezzi
> (Stage 5): non li ridefinisce.
>
> Invarianti transazionali, semantica degli exit code e regole di conflitto:
> identiche a `02_problem-and-need.md` → «Invarianti transazionali». Qui non
> si ripetono. **Nessuna scrittura canonica
> manuale**: l'unico scrittore è `transaction/transaction_manager.py`; le
> assunzioni e le condizioni si aggiornano solo con i comandi del
> transaction manager (`update-assumption`, `resolve-condition`), mai a mano.
> **Nessuna anticipazione dello Stage 8** (team & governance): i ruoli
> (`ROLE-`) non esistono ancora e referenziarli qui è un `future_namespace_ref`.
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
  --project "<project>" --stage 07_operations-and-ip --phase ingress
```

Lo Stage 6 deve essere `approved*` e in `completed_stages`; nessuna `COND-`
open dovuta (altrimenti exit 1 `condition_due`); nessun conflitto pendente.
Poi apri lo stage (unica scrittura ammessa, via governance):

```bash
python "<skill_dir>/transaction/transaction_manager.py" governance-status \
  --project "<project>" \
  --updates '{"status": "in_progress", "current_task": "stage-7-operations-and-ip"}' \
  --reason "ingress Stage 7 autorizzato dai validator"
```

## Passo 2 — Metodologia on-demand

Leggi `methodology/operations-and-ip.md` ora. Prezzo, margine e COGS sono già
canonici (Stage 5): l'operating model **referenzia** i costi operativi
unitari (`unit_ops_cost_refs` → gli `ASS-` COGS dello Stage 5), non li
riscrive. La capacità operativa è un `ASS-` **derived** dai driver, mai un
numero a mano.

## Passo 3 — Subagent nel candidate workspace

Genera un transaction id (`<tx>`) e lancia `operations-ip-analyst` a runtime
(contratto di [`reference/architecture.md`](../reference/architecture.md)
§11.2), unico percorso scrivibile:

```text
<project>/07_operations-and-ip/.working/<tx>/
```

Output attesi: `structured-output.json` (`operations_model` con
`core_processes[]` (`OPS-`, `entity_type: core_process`, `make_buy_partner`,
`owner_hint`, `bottleneck`), `capacity_ref` (ASS- derived, unità coerente
con i volumi GTM), `unit_ops_cost_refs[]` (ref agli `ASS-` COGS Stage 5),
`critical_dependencies[]` (`OPS-`, `entity_type: dependency`, `category`,
`mitigation` **o** `none_identified`+`rationale`), `regulatory_requirements[]`
(valutati o `none_identified`+`rationale`), `ip_strategy` (`assets[]` con
`OPS-`, `entity_type: ip_asset`, `protection`, `rationale`), `risk_refs[]`
→ `RISK-`), `proposed-assumptions.json` (capacità e costi operativi come
`P-ASS-*` derivati con `derivation.variables` esplicite), `research.md`,
`analysis.md`, `section-draft.md`, `handoff.md`.

## Passo 4 — Validazione candidate

```bash
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/07_operations-and-ip/.working/<tx>" \
  --stage 07_operations-and-ip --phase candidate
```

`refint` risolve gli `OPS-` tipizzati, gli `ASS-`/`P-ASS-` e vieta i
riferimenti a namespace di stage futuri (`future_namespace_ref`).

## Passo 5 — QA di stage e criteri di completezza

`stage-qa.md` nel candidate, criteri:

1. ogni processo core con `make_buy_partner` (`make`/`buy`/`partner`) e owner;
2. capacità operativa = `ASS-` derived ricalcolabile, `>= customers_out` del
   GTM (altrimenti ciclo di capacità operativa);
3. ogni dipendenza critica valutata (mitigazione o `none_identified` motivato);
4. ogni requisito normativo valutato;
5. strategia IP esplicita: ogni asset core con `protection` dichiarata;
6. costi operativi unitari referenziati agli `ASS-` COGS dello Stage 5, mai
   duplicati con valore diverso (`ops_cost_divergence`).

## Passo 6 — Egress e applicazione transazionale

Tutti i validator applicabili allo Stage 7 (matrice di enforcement in
`config/enforcement-config.json`):

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --candidate "<project>/07_operations-and-ip/.working/<tx>" \
  --stage 07_operations-and-ip --phase egress
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/07_operations-and-ip/.working/<tx>" \
  --stage 07_operations-and-ip --phase egress
python "<skill_dir>/validators/validate_cross_stage_consistency.py" \
  --project "<project>" --candidate "<project>/07_operations-and-ip/.working/<tx>" \
  --stage 07_operations-and-ip --phase egress
python "<skill_dir>/validators/validate_operations_feasibility.py" \
  --project "<project>" --candidate "<project>/07_operations-and-ip/.working/<tx>" \
  --stage 07_operations-and-ip --phase egress
```

Codici tipici di `validate_operations_feasibility`: `capacity_not_derived`,
`value_mismatch`, `unit_mismatch`, `core_process_unsourced`,
`ops_cost_not_ref`, `dependency_category_not_assessed`,
`regulatory_not_assessed`, `ip_protection_missing`, `unresolved_ref` (RISK-),
`missing_required`. Di `validate_cross_stage_consistency`:
**`ops_capacity_below_gtm`** (capacità < volumi GTM — detect del ciclo di
capacità operativa)
e `ops_cost_divergence`. Exit 1 → correggi il candidate e ripeti.

### Ciclo di capacità operativa — tensione volumi GTM ↔ capacità operativa

Se `ops_capacity_below_gtm`:

1. **BLOCK**: nessuna applicazione canonica (il transaction manager
   respinge); lo stage non avanza;
2. **conflict**: apri il conflitto sull'`ASS-` di capacità (o sul driver dei
   volumi) e porta lo stato a `conflict_awaiting_confirmation` via
   `governance-status`;
3. **confirm**: attendi la conferma esplicita dell'utente in un **turno
   successivo** (risposta ambigua/assente → resta in attesa; rifiuto →
   `needs_revision`);
4. **history**: la modifica confermata passa dal comando transazionale
   `update-assumption` (mai da un edit dei registri, mai da una scrittura
   mediata dall'orchestratore). Leggi prima il fingerprint del record con
   `show-assumption` (`record_hash` = `expected_record_hash`), poi prepara un
   solo file `--changes` con `operation_id`, `decision`, e i change (con
   `expected_record_hash` per ogni `ASS-`); esegui `update-assumption`, che
   fa CAS, `previous_values`, allocazione `DEC-*`, riga nel decision-log,
   risoluzione dello stato e — punto 5 — la matrice impact **prima** del
   commit;
5. **impact**: eseguita dal comando su una copia del progetto; se la catena
   resta rotta → `impact_validation_failed` e canonico byte-identico;
6. **resubmit**: riporta lo stato a `in_progress` e rivaluta il gate.

Eventuali condizioni aperte si chiudono **solo** con
`transaction_manager.py resolve-condition`, mai a mano.

Tutti exit 0 → applica e avanza:

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage \
  --project "<project>" --stage 07_operations-and-ip \
  --candidate "<project>/07_operations-and-ip/.working/<tx>" \
  --gate-result approved
```

Il founder conferma esplicitamente: modello operativo sostenibile ai volumi
dichiarati, make/buy accettato, rischi operativi accettati o `COND-` aperte.
Gate `approved*` solo dopo conferma.

## Passo 7 — Verifica post-commit e handoff

Dopo `"result": "applied"`: `current_stage` = `08_team-and-governance`,
`completed_stages` include `07_operations-and-ip`.
`handoff.md`: processi core, capacità, dipendenze aperte, `COND-` create,
next stage. Azione successiva: `workflows/09_team-and-governance.md`
(Stage 8).

## Resume

Come per gli stage precedenti (`recover` → catena → `next_action`). Dopo
qualunque modifica canonica confermata su capacità, volumi o costi, la
matrice `--phase impact` sugli Stage 4–7 è rieseguita dal comando
`update-assumption` prima del commit.
