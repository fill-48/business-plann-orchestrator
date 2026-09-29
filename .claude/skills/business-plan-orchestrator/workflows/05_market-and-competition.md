# Workflow 05 — Mercato e concorrenza (Stage 4, `04_market-and-competition/`)

> Numerazione dei file: **Stage 4** → cartella `04_market-and-competition/` →
> questo workflow (`05_market-and-competition.md`). Metodologia on-demand:
> [`methodology/market-sizing-and-competition.md`](../methodology/market-sizing-and-competition.md) +
> [`methodology/evidence-framework.md`](../methodology/evidence-framework.md).
> Subagent: [`runtime-agents/market-competition-analyst.md`](../runtime-agents/market-competition-analyst.md)
> (esecuzione sequenziale).
>
> Da questo stage è attivo il validator di dominio
> `validate_market_arithmetic` (stage 4–6, fasi egress/impact — matrice di
> enforcement in `config/enforcement-config.json`).
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

## Passo 1 — Ingress gate (qui si sente il checkpoint evidenze)

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --stage 04_market-and-competition --phase ingress
```

Se lo Stage 3 è stato chiuso `approved_with_conditions`, una `COND-` open
con `due_before_stage: 04_market-and-competition` produce **exit 1
`condition_due`**: lo stage non si apre finché la condizione non è
`resolved`/`waived` con `DEC-` tracciata (e `evidence_ref` se risolta con
evidenza). La risoluzione passa da una transazione di governance, mai da un
edit manuale del registro. Poi:

```bash
python "<skill_dir>/transaction/transaction_manager.py" governance-status \
  --project "<project>" \
  --updates '{"status": "in_progress", "current_task": "stage-4-market"}' \
  --reason "ingress Stage 4 autorizzato dai validator"
```

## Passo 2 — Metodologia on-demand e runtime-check

Leggi `methodology/market-sizing-and-competition.md` ora. Esegui il
runtime-check della capability di ricerca web (SKILL.md): se assente,
dichiaralo — il sizing procede con le fonti fornite dall'utente e stime
`model_estimate` etichettate.

## Passo 3 — Subagent nel candidate workspace

Lancia `market-competition-analyst` a runtime (contratto di
[`reference/architecture.md`](../reference/architecture.md) §11.2), unico
percorso scrivibile:

```text
<project>/04_market-and-competition/.working/<tx>/
```

Output attesi: `structured-output.json` (`market_model` con
`tam_ref`/`sam_ref`/`som_ref` + `competitive_landscape` con le 6 categorie
e i `CMP-*` valutati o `none_identified` motivato),
`proposed-assumptions.json` (driver e stime come `P-ASS-*` con
`derivation.variables` esplicite: SOM `bottom_up`, stime per metodo,
pesi, riconciliazione dei metodi di sizing), `research.md`, `analysis.md`
(PESTEL/Porter),
`section-draft.md`, `handoff.md`.

## Passo 4 — Validazione candidate

```bash
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/04_market-and-competition/.working/<tx>" \
  --stage 04_market-and-competition --phase candidate
```

## Passo 5 — QA di stage e criteri di completezza

`stage-qa.md` nel candidate, criteri:

1. SOM `bottom_up` con driver espliciti e ricalcolabili;
2. `SOM ≤ SAM ≤ TAM`, stessa unità/valuta/periodo/geografia;
3. TAM/SAM con metodo indipendente; riconciliazione
   (`weighted_average`/`selected_ref`) se ≥2 metodi;
4. ogni categoria competitor valutata; `none_identified` solo con
   `research_notes` + `rationale`;
5. fonti nel `source-register` con qualità; stime etichettate.

SOM %-di-TAM nudo o categoria non valutata → `blocked`. Un valore di
mercato che contraddice un `ASS-*` canonico → `INCOERENZA RILEVATA`
(protocollo SKILL.md), nessuna scrittura.

## Passo 6 — Egress e applicazione transazionale

Tutti i validator applicabili allo Stage 4 (matrice di enforcement in
`config/enforcement-config.json`):

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --candidate "<project>/04_market-and-competition/.working/<tx>" \
  --stage 04_market-and-competition --phase egress
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/04_market-and-competition/.working/<tx>" \
  --stage 04_market-and-competition --phase egress
python "<skill_dir>/validators/validate_market_arithmetic.py" \
  --project "<project>" --candidate "<project>/04_market-and-competition/.working/<tx>" \
  --stage 04_market-and-competition --phase egress
```

Codici tipici di `validate_market_arithmetic`: `som_not_bottom_up`,
`market_ordering`, `triangulation_missing`, `reconciliation_missing`,
`reconciliation_invalid`, `value_mismatch`/`unit_mismatch` (ricalcolo DSL),
`category_not_evaluated`, `none_identified_unmotivated`. Exit 1 → correggi
il candidate e ripeti; mai ritoccare i registri canonici a mano.

Tutti exit 0 → applica e avanza (il transaction manager riesegue i
validator sullo snapshot, incluso il market validator per gli stage 4+):

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage \
  --project "<project>" --stage 04_market-and-competition \
  --candidate "<project>/04_market-and-competition/.working/<tx>" \
  --gate-result approved
```

(`approved_with_conditions` + `proposed-conditions.json` per gap tracciati,
es. TAM senza fonte indipendente ancora da validare.)

## Passo 7 — Verifica post-commit e handoff

Dopo `"result": "applied"`: `current_stage` = `05_business-model`,
`completed_stages` include `04_market-and-competition`; il SOM canonico
(`ASS-*` allocato) è il valore che gli Stage 5–6 dovranno referenziare —
qualunque tensione con la capacità GTM emersa allo Stage 6 passa dal ciclo
di conflitto (conflitto esplicito su quell'`ASS-*`, `--phase impact` sugli
stage 4–6 dopo la conferma), **mai** da una riscrittura silenziosa dello
Stage 4.

Azione successiva: `workflows/06_business-model.md` (Stage 5).

## Resume

Come per gli stage precedenti (`recover` → catena di ripresa di
[`reference/architecture.md`](../reference/architecture.md) §13.3 →
`next_action`).
In più: dopo qualunque modifica canonica confermata che tocca il mercato
(ciclo di conflitto), riesegui `validate_market_arithmetic --phase impact` su
`04_market-and-competition` prima di proseguire a valle.
