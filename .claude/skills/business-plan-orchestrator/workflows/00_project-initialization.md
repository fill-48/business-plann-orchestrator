# Workflow 00 — Project initialization

> Eseguito quando non esiste ancora un progetto nella working directory
> corrente (nessun `<slug>/shared/project-status.md` trovato). Precede
> `01_idea-discovery.md`.

## 1. Runtime-check delle capability

Prima di qualunque altra cosa, verifica la disponibilità reale di ciascuna
capability della tabella in `SKILL.md` → "Runtime-check delle capability
esterne". Per ognuna:

- Se disponibile: `mode: "native"` (per `/goal`) o `"skill"` (per le altre).
- Se assente: `mode: "fallback"`, e userai il file corrispondente in `fallbacks/`.
- Per `/goal` specificamente: verifica anche la versione di Claude Code
  (richiesta ≥ 2.1.139) e che il workspace sia trusted con hooks abilitati. Non
  invocarlo mai internamente: è un comando nativo che solo l'utente esegue.

Il risultato di questo check alimenta `capability_map` in
`shared/project-config.json` (vedi passo 4).

## 2. Determinare `project_slug` e `cwd_path`

1. Se l'utente ha già indicato un nome di progetto, derivane uno slug
   (`lowercase`, spazi → `-`, solo `[a-z0-9-]`, conforme al pattern
   `^[a-z0-9][a-z0-9-]*$` di `schemas/project-config.schema.json`).
2. Se non l'ha indicato, chiedilo esplicitamente prima di creare qualunque
   cartella — non inventare un nome.
3. `cwd_path` = la working directory corrente da cui l'orchestratore è stato
   invocato (mai una cartella dentro il repo della skill).

## 3. Creare **solo** le cartelle della Sezione 0

**Importante:** in questo stage si creano **esclusivamente**:

```
<project_slug>/
├── 00_idea-discovery/
└── shared/
```

Le cartelle `01_…`–`12_…`, `review/` e `output/` **non** vengono create qui: la
loro creazione è condizionata al superamento del decision gate di
`01_idea-discovery.md`
([`reference/architecture.md`](../reference/architecture.md) §8.6). Crearle
prima violerebbe il vincolo del gate.

## 4. Inizializzare i file di `shared/`

Crea i 9 file con contenuto **valido e vuoto** (non placeholder informi — dati
minimi ma conformi allo schema):

- `project-config.json` — conforme a `schemas/project-config.schema.json`:
  ```json
  {
    "project_name": "<nome leggibile>",
    "project_slug": "<slug>",
    "created_at": "<ISO date>",
    "cwd_path": "<path>",
    "methodology_version": "0.1.0",
    "release_scope": "0.1",
    "capability_map": {
      "step_back": { "available": false, "mode": "fallback", "checked_at": "<ISO date>" },
      "reverse_prompting": { "available": false, "mode": "fallback", "checked_at": "<ISO date>" },
      "prompt_contracts": { "available": false, "mode": "fallback", "checked_at": "<ISO date>" },
      "goal": { "available": false, "mode": "unavailable", "checked_at": "<ISO date>" },
      "grant": { "available": false, "mode": "unavailable", "checked_at": "<ISO date>" },
      "skill_creator": { "available": false, "mode": "unavailable", "checked_at": "<ISO date>" }
    }
  }
  ```
  (valorizza i campi `available`/`mode` con l'esito reale del passo 1 — questi
  sono solo valori di default prima del check).
- `startup-profile.json` — array/oggetto vuoto **non** valido finché non
  compilato: crealo come bozza minima già conforme
  (`schemas/startup-profile.schema.json`) non appena la classificazione emerge
  in `01_idea-discovery.md`. In questo stage può non esistere ancora.
- `assumptions-register.json` → `[]`
- `evidence-register.json` → `[]`
- `source-register.json` → `[]`
- `risk-register.json` → `[]`
- `decision-log.md` → intestazione + tabella vuota (colonne: data, decisione,
  opzioni valutate, motivazione, impatto, file modificati, approvatore).
- `open-questions.md` → intestazione + lista vuota.
- `project-status.md` — conforme a `schemas/project-status.schema.json`,
  reso come front-matter YAML + prosa:
  ```yaml
  ---
  project_name: <nome>
  current_stage: "00_idea-discovery"
  current_task: "raw-idea"
  status: "in_progress"
  completed_stages: []
  pending_stages: ["00_idea-discovery"]
  approved_decisions: []
  open_questions: []
  critical_assumptions: []
  blocking_issues: []
  last_updated: "<ISO date>"
  next_action: "Raccogliere l'idea grezza dall'utente (raw-idea.md)"
  ---
  ```

## 5. Passaggio allo stage successivo

Una volta creata la struttura minima, passa immediatamente a
`01_idea-discovery.md` — non chiedere conferma per questo passaggio interno: è
lo stesso stage logico (Sezione 0), solo diviso in due file per chiarezza.
