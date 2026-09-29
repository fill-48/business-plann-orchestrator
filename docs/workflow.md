# Workflow e stage

Il business plan si costruisce in quattordici stage (0–13), in una sequenza
causale: ogni stage usa solo ciò che gli stage precedenti hanno già
approvato. Le istruzioni operative dettagliate che Claude segue a runtime
sono in [`workflows/`](../.claude/skills/business-plan-orchestrator/workflows/)
dentro il pacchetto della skill; questa pagina ne è la sintesi per l'utente.

## Schema comune degli stage 1–13

```text
precondizioni → proposta del subagent nel candidate (<stage>/.working/<tx>/)
→ validator (fasi ingress / candidate / egress) → decision gate
→ commit del transaction manager → handoff → stage successivo
```

- **Candidate.** I subagent propongono; non scrivono mai i file canonici.
- **Validator.** Script deterministici in `validators/`: exit 0 = valido,
  1 = candidate non valido, 2 = errore d'uso, 3 = stato canonico non valido.
  La matrice stage × fase × validator è in
  `config/enforcement-config.json`.
- **Transaction manager.** `transaction/transaction_manager.py` è l'unico
  scrittore canonico: applica il candidate in modo atomico, registra un
  journal in `shared/.tx/` e sa recuperare un'operazione interrotta
  (`recover`).
- **Decision gate.** `approved`, `approved_with_conditions` (con condizioni
  `COND-*` da chiudere prima di uno stage indicato), `needs_revision`,
  `blocked`.
- **Fase impact.** Dopo il commit, e quando un'assunzione confermata cambia,
  i validator rileggono il progetto per verificare che nulla di già approvato
  sia stato rotto.

## Gli stage

### Stage 0 — Idea discovery (`00_idea-discovery/`)

Runtime-agent `founder-interviewer`. Idea verbatim, step-back, reverse
prompting, domande mirate, classificazione della startup, prompt contract,
concept consolidato, registri iniziali in `shared/`.
**Gate:** concept comprensibile, startup classificata, destinatario
identificato, output definiti, assunzioni iniziali registrate, data gap
espliciti, prompt contract approvato.

### Stage 1 — Problema e bisogno (`01_problem-and-need/`)

Runtime-agent `customer-problem-analyst`. Problema formulato come costo,
rischio, inefficienza o bisogno non servito; distinzione tra percepito e
dimostrato. **Gate:** problema misurabile e falsificabile, almeno
un'evidenza classificata.

### Stage 2 — Customer segmentation (`02_customer-segmentation/`)

Runtime-agent `customer-problem-analyst`. Segmenti `SEG-*` ancorati al
problema, ruoli user/buyer/decision maker separati, beachhead motivato.

### Stage 3 — Value proposition (`03_value-proposition/`)

Runtime-agent `value-proposition-strategist`. Value proposition canvas su
Stage 1–2; ogni claim ha una prova o è marcato come assunzione.
**Checkpoint evidenze:** se il supporto è fatto solo di assunzioni, lo stage
può chiudersi al massimo `approved_with_conditions`, con una condizione di
validazione.

### Stage 4 — Mercato e concorrenza (`04_market-and-competition/`)

Runtime-agent `market-competition-analyst`, validator
`validate_market_arithmetic`. TAM/SAM/SOM ricalcolabili con SOM bottom-up e
`SOM ≤ SAM ≤ TAM`; riconciliazione se si usano più metodi; ogni categoria di
concorrenza valutata.

### Stage 5 — Business model (`05_business-model/`)

Runtime-agent `business-model-analyst`, validator `validate_unit_economics`
e `validate_cross_stage_consistency`. Un solo prezzo registrato come
assunzione, ricavi come formula di driver, contribution margin calcolato.

### Stage 6 — Go-to-market (`06_go-to-market/`)

Runtime-agent `go-to-market-analyst`, validator `validate_funnel_arithmetic`.
Funnel ricalcolabile, `CAC = spend / clienti acquisiti`, churn esplicito;
se la capacità commerciale è inferiore al SOM si apre un ciclo di conflitto.

### Stage 7 — Operations e IP (`07_operations-and-ip/`)

Runtime-agent `operations-ip-analyst`, validator
`validate_operations_feasibility`. Processi core `OPS-*` con scelta
make/buy/partner, capacità operativa, dipendenze, requisiti normativi,
strategia IP.

### Stage 8 — Team e governance (`08_team-and-governance/`)

Runtime-agent `team-governance-analyst`, validator
`validate_team_and_governance`. Ogni processo core coperto da un ruolo
`ROLE-*`, ogni gap di competenze con una risposta reale, un solo owner per
ogni area di decisione, equity coerente, costi del personale come driver.

### Stage 9 — Roadmap e milestone (`09_roadmap-and-milestones/`)

Runtime-agent `milestone-planner`, validator `validate_milestone_chain`.
Milestone `MIL-*` con dipendenze acicliche, date coerenti, owner, costo come
riferimento a un driver, criteri misurabili e regole go/no-go. Consegna allo
Stage 10 il contratto `financial_plan_inputs` (solo riferimenti, nessun
calcolo).

### Stage 10 — Piano finanziario (`10_financial-plan/`)

Runtime-agent `financial-modeller`. Pipeline deterministica: binding dei
driver sugli input governati (`validate_financial_binding`), motore
finanziario (`validate_financial_engine`) con scenari base/downside/upside e
riconciliazioni `REC-*`, documento canonico validato
(`validate_financial_output`), capitolo `financial-plan.md` e workbook
`financial-model.xlsx` generati dal canonico e verificati per coerenza.
Lo stage si ferma al **fabbisogno**: importo richiesto, strumento e termini
appartengono allo Stage 11.

### Stage 11 — Funding request (`11_funding-request/`)

Runtime-agent `funding-strategist`, validator `validate_funding_request`.
Proiezione del canonico finanziario, mai un secondo motore: capitale
richiesto riconciliato con il fabbisogno modellato, impieghi che sommano al
capitale richiesto, runway prima e dopo il finanziamento, gap residuo sempre
dichiarato, nessun termine finanziario inventato (valutazione, diluizione,
strumento restano decisioni esplicite).

### Stage 12 — Data room (`12_data-room/`)

Runtime-agent `evidence-analyst`, validator `validate_data_room`. Indice
delle evidenze dell'intero piano: ogni documento indicizzato al suo path,
mai copiato né modificato; ogni claim materiale `CLM-*` collegato alle sue
evidenze; claim non supportati, lacune e conflitti sempre esposti.

### Stage 13 — Document generation (`13_document-generation/`)

Runtime-agent `business-plan-writer`, validator
`validate_document_generation`. Assembla il business plan in diciassette
capitoli dai soli canonici: nessuna prosa nuova, nessun ricalcolo, ogni
valore tracciato, etichette epistemiche sulle assunzioni, disclosure mai
soppresse. Il commit porta il progetto allo stato terminale; la
pubblicazione scrive `output/business-plan.md`.

## Che cosa non fa la versione 0.7.1

- non esegue un review loop finale avversariale;
- non genera PDF o DOCX;
- non prevede un protocollo per riaprire un piano già completato (stato
  terminale dello Stage 13).
