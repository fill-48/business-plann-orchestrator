# Changelog

Tutte le modifiche rilevanti del prodotto sono documentate in questo file.
Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e il
versionamento [Semantic Versioning](https://semver.org/lang/it/).

## [0.7.1] - 2026-09-29

**Prima release pubblica.** Deriva dalla versione 0.7.0 (baseline di
sviluppo, commit `73d15b4cc46533de46ce54ee0a96f2e9caf3d96e`, non pubblicata
come tale) con una correzione funzionale e l'hardening necessario alla
pubblicazione. Il processo copre l'intero percorso dall'idea grezza al
business plan finale (Stage 0–13).

### Fixed

- **Project-location guard dello Stage 10.** I generatori dello Stage 10
  (`output/build_canonical_output.py`, `output/render_financial_plan.py`,
  `output/export_financial_model.py`) e `validators/validate_financial_output.py`
  rifiutavano ogni progetto collocato sotto una cartella `projects/` accanto
  alla cartella `.claude/` che contiene la skill: con l'installazione standard
  questo significava `~/projects/**`, dove lo Stage 10 non poteva essere
  completato. La guardia ora rifiuta **solo** i progetti collocati dentro la
  directory della skill; il codice di esito `real_project_write_forbidden` è
  invariato e nessun modulo calcola più path sopra il proprio pacchetto.
- Il workflow dello Stage 11 invocava `validate_stage_gate`, che copre solo
  gli Stage 1–9 e rispondeva con un errore d'uso: il passo è sostituito da una
  verifica delle precondizioni.
- L'handoff generato dallo Stage 12 indicava lo stage successivo come non
  implementato: ora indica l'avvio dello Stage 13.
- Testi di diagnostica e di output che descrivevano confini di release
  superati sono stati riallineati al comportamento reale.
- Installer: due backup creati nello stesso secondo non collidono più.

### Changed

- La specifica architetturale è distribuita dentro il pacchetto
  (`reference/architecture.md`): la skill installata non dipende da file
  esterni al proprio pacchetto.
- I workflow invocano gli script tramite `<skill_dir>`, la directory che
  contiene `SKILL.md`, invece di path relativi al repository.
- Gli installer escludono le cache Python, verificano il numero di file
  copiati e segnalano l'assenza di Python 3.12 o di `jsonschema`.

### Added

- Documentazione utente e contributor: installazione, uso, workflow,
  metodologia, architettura, troubleshooting, privacy e trattamento dei dati.
- Esempio completamente fittizio in `examples/fictional-startup/`.
- Suite di test pubblica: smoke test (installazione in una home temporanea,
  autosufficienza della skill installata, link interni, publication boundary,
  scansione di segreti e path locali) e test di integrazione del runtime.
- Workflow GitHub Actions per Linux e Windows.
- `requirements.txt` con l'unica dipendenza di terze parti (`jsonschema`).

## [0.7.0] - 2026-09-29

Baseline di sviluppo da cui deriva la release pubblica 0.7.1; non pubblicata
come tale.

### Added

- Stage 13 — Document generation: assemblaggio deterministico del business
  plan in diciassette capitoli dai soli canonici degli Stage 1–12, con
  tracciabilità di ogni valore, etichette epistemiche sulle assunzioni e
  pubblicazione di `output/business-plan.md`
  (validator `validate_document_generation`).

## [0.6.0]

### Added

- Stage 12 — Data room: indice delle evidenze dell'intero piano, allocazione
  dei claim `CLM-*`, tracciabilità claim → evidenza, rilevazione di lacune e
  conflitti, indice derivato `data-room-index.md`
  (validator `validate_data_room`).

## [0.5.0]

### Added

- Stage 11 — Funding request: proiezione del canonico finanziario dello
  Stage 10 in una richiesta di capitale riconciliata con il fabbisogno, gli
  impieghi e il runway, senza termini finanziari inventati
  (validator `validate_funding_request`).

## [0.4.0]

### Added

- Stage 10 — Piano finanziario: binding dei driver sugli input governati,
  motore finanziario deterministico, tre scenari, riconciliazioni, documento
  canonico, capitolo `financial-plan.md` e workbook `financial-model.xlsx`
  generati senza librerie di terze parti
  (validator `validate_financial_binding`, `validate_financial_engine`,
  `validate_financial_reconciliation`, `validate_financial_output`).

## [0.3.0]

### Added

- Stage 7 — Operations e IP, Stage 8 — Team e governance, Stage 9 — Roadmap
  e milestone, con i rispettivi schemi e validator.
- Comandi transazionali `update-assumption`, `resolve-condition` e
  `show-assumption`; registro strutturato delle decisioni.

## [0.2.0]

### Added

- Stage 1–6: problema e bisogno, customer segmentation, value proposition,
  mercato e concorrenza, business model, go-to-market.
- Transaction manager come unico scrittore canonico, con journal, rollback e
  recovery; validator eseguibili per fasi `ingress`, `candidate`, `egress` e
  `impact`.

## [0.1.0]

### Added

- Skill orchestratrice `business-plan-orchestrator`, Stage 0 (idea discovery,
  prompt contract, classificazione della startup, registri iniziali),
  installer per Windows e Unix.
- Protocollo di persistenza dei valori: un valore già registrato non viene
  mai sovrascritto senza conferma esplicita dell'utente in un turno
  successivo (`INCOERENZA RILEVATA`).

[0.7.1]: https://github.com/fill-48/business-plann-orchestrator/releases/tag/v0.7.1
