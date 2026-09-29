# CLAUDE.md — regole per lavorare su questo repository

Questo repository sviluppa la skill **`business-plan-orchestrator`** per
Claude Code. Prima di modificarla leggi
[`CONTRIBUTING.md`](CONTRIBUTING.md) e la specifica
[`reference/architecture.md`](.claude/skills/business-plan-orchestrator/reference/architecture.md).

## Architettura (non negoziabile)

- **Una sola** skill orchestratrice che lancia subagent verticali **a
  runtime** tramite l'Agent tool.
- **Non** creare agent definition persistenti in `.claude/agents/` né
  sub-skill autonome per i capitoli del business plan.
- `SKILL.md` è un **controller magro**: instrada, non contiene il manuale.
- Il pacchetto `.claude/skills/business-plan-orchestrator/` deve restare
  **autosufficiente**: nessun riferimento a file del repository esterni al
  pacchetto, nessun path calcolato sopra la radice del pacchetto.
- Nei workflow gli script si invocano come
  `python "<skill_dir>/validators/<nome>.py" ...`.

## Principi metodologici

1. Evidenze prima della narrativa.
2. Un solo `assumptions-register.json` ufficiale.
3. Driver prima delle percentuali.
4. Cassa prima dell'utile.
5. Milestone prima del funding.
6. Executive summary per ultimo.

## Regole operative

- I progetti degli utenti vivono nella loro working directory, **mai** in
  questo repository. L'unico progetto versionato è l'esempio fittizio in
  `examples/fictional-startup/`.
- Classi di evidenza esatte: `verified_fact`, `internal_evidence`,
  `external_source`, `founder_assumption`, `model_estimate`,
  `missing_information`.
- Incoerenze: formato `INCOERENZA RILEVATA`; mai mediare i valori.
- Il transaction manager è l'unico scrittore dei file canonici.
- Solo dati fittizi in test, fixture ed esempi.
- Lingua: prosa in italiano; chiavi JSON, identificatori e nomi di file in
  inglese.

## Test

```bash
bash tests/run-tests.sh            # oppure: pwsh -File tests/run-tests.ps1
```

I test non devono scrivere nel checkout: usa directory temporanee.
