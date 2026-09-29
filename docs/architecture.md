# Architettura

La specifica completa è distribuita con la skill:
[`reference/architecture.md`](../.claude/skills/business-plan-orchestrator/reference/architecture.md).
Questa pagina ne dà una vista d'insieme per chi contribuisce.

## Una skill, subagent a runtime

- **`SKILL.md`** è un controller magro: legge lo stato del progetto,
  identifica lo stage, carica solo la metodologia pertinente, lancia i
  subagent e applica i gate. Non contiene il manuale.
- **Subagent a runtime.** Ogni ruolo (`founder-interviewer`,
  `financial-modeller`, `evidence-analyst`, …) è un prompt template in
  `runtime-agents/`, lanciato con l'Agent tool quando serve. Non esistono
  agent definition persistenti né sub-skill per capitolo.
- **Workflow e metodologia** sono file Markdown separati, versionabili
  indipendentemente dal controller.

## Artefatti persistenti

Il progetto è la memoria tra sessioni:

```text
<progetto>/
├── 00_idea-discovery/ … 13_document-generation/   uno per stage
│   ├── structured-output.json    canonico validato (Stage 1+)
│   ├── handoff.md                sintesi operativa per la sessione successiva
│   └── .working/<tx>/            candidate delle transazioni (temporaneo)
├── shared/
│   ├── project-status.md         stato, stage corrente, next_action
│   ├── project-config.json       configurazione e capability rilevate
│   ├── assumptions-register.json unico registro delle assunzioni (ASS-*)
│   ├── evidence-register.json    evidenze (EVD-*)
│   ├── source-register.json      fonti (SRC-*)
│   ├── risk-register.json        rischi (RISK-*)
│   ├── decisions-register.json   decisioni (DEC-*)
│   ├── conditions-register.json  condizioni dei gate (COND-*)
│   └── .tx/                      journal e lock del transaction manager
└── output/business-plan.md
```

## Pipeline transazionale

```text
subagent → candidate → validator (ingress / candidate / egress) → transaction manager → canonico
                                                                      ↘ journal + recovery
```

- Il **transaction manager** è l'unico scrittore canonico. Ogni commit è
  atomico: o tutto il write-set viene applicato, o nulla. Un'interruzione a
  metà viene recuperata con `recover`.
- Le **mutazioni** di dati già canonici passano da comandi dedicati:
  `update-assumption` (con controllo d'impatto prima del commit) e
  `resolve-condition`. Nessun registro si modifica a mano.
- I **validator** sono deterministici: nessun orologio, rete o casualità.
  La matrice stage × fase × validator, l'ordine degli stage e le tolleranze
  numeriche sono in `config/enforcement-config.json`.

## Stage 10: il motore finanziario

```text
financial_plan_inputs (Stage 9) + registri
→ binding dei driver → motore (scenari, riconciliazioni REC-*)
→ documento canonico → capitolo Markdown + workbook XLSX → coerenza dei derivati
```

Il documento canonico è l'unica fonte numerica: capitolo e workbook ne sono
derivati e vengono verificati per coerenza (checksum e riconciliazioni
incrociate). Il workbook è un pacchetto OOXML deterministico generato con la
sola libreria standard.

## Stage 11–13: proiezioni, non nuovi calcoli

- **Funding request** proietta il canonico finanziario.
- **Data room** indicizza evidenze e claim senza copiare o modificare file.
- **Document generation** assembla i canonici in diciassette capitoli; ogni
  valore è verbatim o legato alla sua foglia sorgente, e l'egress
  ricostruisce il documento byte per byte.

## Struttura del repository

```text
.claude/skills/business-plan-orchestrator/   pacchetto installabile (autosufficiente)
docs/                                        documentazione
examples/fictional-startup/                  esempio fittizio (anche fixture dei test)
tests/smoke/                                 installazione, struttura, publication boundary
tests/integration/                           runtime: transazioni, validator, finanza, data room, document generation
install.sh, install.ps1                      installer
```
