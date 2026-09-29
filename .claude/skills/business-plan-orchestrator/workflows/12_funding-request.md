# Workflow — Stage 11 · `11_funding-request`

> **Numerazione dei file.** Il workflow `NN_…` serve lo stage `NN-1`: questo
> file, `12_funding-request.md`, è il workflow dello **Stage 11**, non dello
> Stage 12. È la stessa convenzione per cui `workflows/11_financial-plan.md`
> serve lo Stage 10. Il prefisso `12_` non rende questo file un artefatto
> dello Stage 12 `12_data-room`, servito da `workflows/13_data-room.md`.

Stage: `11_funding-request` · Runtime-agent: `funding-strategist` ·
Metodologia: [`methodology/funding-request.md`](../methodology/funding-request.md) ·
Schema: [`schemas/funding-request.schema.json`](../schemas/funding-request.schema.json)

La funding request è una **proiezione sul canonico accettato dello Stage 10**,
non un secondo motore finanziario. Legge
`10_financial-plan/structured-output.json` come **unica sorgente numerica** e
non ricalcola nulla in silenzio.

`<skill_dir>` è la directory che contiene `SKILL.md` (normalmente
`~/.claude/skills/business-plan-orchestrator`); `<project>` è la cartella del
progetto nella working directory dell'utente; `<tx>` è l'identificatore della
transazione.

---

## Passo 1 — Gate di ingresso: rifiuto **prima** di qualunque scrittura

Verifica che **tutti e tre** gli artefatti dello Stage 10 esistano, non siano
vuoti e siano validati:

```text
10_financial-plan/structured-output.json     canonico, radice financial_plan
10_financial-plan/financial-plan.md          capitolo
10_financial-plan/financial-model.xlsx       workbook, pacchetto OOXML
```

Se **uno solo** manca o non è validato, lo stage si ferma con
`fr_input_incomplete`, exit `1`, e **zero file scritti**: il rifiuto precede
lock, journal e qualunque I/O. Non si costruisce una funding request su un
piano finanziario incompleto, e non si surroga l'artefatto mancante.

```bash
python "<skill_dir>/validators/validate_funding_request.py" \
  --build --project <project> --tx <tx>
```

## Passo 2 — Precondizioni di governance

Lo Stage 10 deve essere in `completed_stages` con stato `approved` o
`approved_with_conditions`, e `current_stage` deve essere
`11_funding-request`. Verificalo leggendo `shared/project-status.md`: **non**
invocare `validate_stage_gate` né `validate_referential_integrity` su questo
stage, perché quei validator coprono solo gli Stage 1–9 e su ogni altro stage
rispondono con un errore d'uso (exit 2). Il gate d'ingresso dei dati è il
costruttore del Passo 1.

Uno stato `approved_with_conditions` **non è un ostacolo**: è
un'informazione che il documento **propaga** e non lava.

## Passo 3 — Proiezione, non calcolo

Il costruttore legge e **copia**; dove deriva, lo **dichiara**:

| Grandezza | Path canonico | Regola |
|---|---|---|
| fabbisogno modellato | `funding_gap.metrics.funding_gap_to_buffer` | **primaria** |
| fabbisogno modellato | `funding_gap.metrics.funding_gap_to_zero` | **fallback**, solo e soltanto se la primaria vale `NOT_APPLICABLE` |
| buffer | `cash_buffer.metrics.threshold` | **già incluso** nella base: esposto, mai sommato |
| contingency | — | **assente** e dichiarata |
| arrotondamento | — | **nessuno** e dichiarato |
| runway ante | `runway.metrics.runway_to_zero`, `runway.metrics.runway_to_buffer` | **due** grandezze distinte, mai collassate |
| runway post | `cash_flow.series` | ricostruito periodo per periodo, tolleranza `count` esatta |
| impieghi | `funding_gap.use_of_proceeds_candidates` | ogni categoria risale a un `category_id` e ai suoi `driver_refs` |
| milestone | `milestone_coverage.milestones`, `calendar.out_of_horizon_milestones` | una milestone fuori orizzonte **non** riceve una data plausibile |
| scenari | `results.scenarios` | con `coverage.level == "none"` restano `NOT_APPLICABLE` con motivazione nominata |

`capital_requirement.modeled_need_ref` **nomina per esteso** il path
effettivamente usato. Quando scatta il fallback, il documento dichiara che la
soglia di buffer non era applicabile: nasconderlo sarebbe materiale.

## Passo 4 — Ciò che non si inventa

```text
valutazione · diluizione · strumento · prezzo · round · quota · termini
                                                     MAI INVENTATI
funding_type · primary_reader · development_stage    LETTI da
                                                     shared/startup-profile.json
tranche e schedule di finanziamento                  not_supported finché non
                                                     esiste un portatore canonico
capex · depreciation · working capital · tax
financing                                            NOT_SUPPORTED dichiarato
scenari downside/upside senza copertura              NOT_APPLICABLE dichiarato
```

Un termine ignoto assume lo stato dichiarato
`dependencies_and_assumptions.decision_needed[] {code, question, blocking}`,
**mai** un valore plausibile.

## Passo 5 — `--phase egress`

```bash
python "<skill_dir>/validators/validate_funding_request.py" \
  --project <project> --candidate <project>/11_funding-request/.working/<tx> \
  --stage 11_funding-request --phase egress
```

Exit `≠ 0` ⇒ **stop**: nessuna scrittura canonica, solo governance. Il
transaction manager applica il candidate solo su egress verde:

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage \
  --project <project> --stage 11_funding-request \
  --candidate <project>/11_funding-request/.working/<tx> --gate-result approved
```

## Passo 6 — Avanzamento allo Stage 12

Dopo `"result": "applied"`, `completed_stages` include `11_funding-request`,
`current_stage` diventa `12_data-room` con `status` `not_started`, e
`next_action` — calcolato dal transaction manager nella stessa transazione —
indica di avviarlo. Azione successiva:
[`workflows/13_data-room.md`](13_data-room.md) (Stage 12).

`release_boundary`, dichiarato in `config/enforcement-config.json`, vale
`13_document-generation`, l'ultimo stage di `stage_order`: lo Stage 12 è
dentro il confine. Il transaction manager risponde `stage_not_implemented`
(exit `1`) solo a uno stage oltre il confine, e nessuno stage del piano lo
supera.

---

## Anti-pattern

- ricalcolare `funding_gap_to_zero` dal `cash_flow` invece di leggerlo;
- sommare il buffer alla base che lo contiene già;
- presentare tre serie identiche come tre scenari;
- chiedere capitale «a cassa zero» quando esiste una `cash_buffer_policy`;
- far sparire un gap residuo perché il documento «suona meglio»;
- dichiarare chiuso un debito perché esiste un artefatto nuovo.
