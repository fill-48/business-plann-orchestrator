---
name: business-plan-orchestrator
description: "Orchestratore per trasformare un'idea di startup grezza in un business plan completo, coerente e verificabile: business plan, business plan startup, idea grezza, brainstorming strutturato, prompt contract, classificazione startup, problema e bisogno, customer segmentation, value proposition, mercato TAM SAM SOM, business model, go-to-market, operations e IP, team e governance, roadmap e milestone, financial plan, funding request, pitch deck, investitore, business angel, banca, bando pubblico, grant, data room, review loop. Attivare con /business-plan-orchestrator, oppure ogni volta che l'utente descrive un'idea di startup/prodotto e vuole strutturarla, validarla o portarla a un investitore/banca/bando — anche se non usa letteralmente le parole 'business plan': basta che stia raccontando un'idea imprenditoriale grezza e chieda aiuto a metterla in forma, capire se regge, o prepararla per raccogliere capitale."
argument-hint: [idea grezza o nome/slug del progetto da riprendere]
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Agent
---

# Business Plan Orchestrator — Controller

Trasforma un'idea imprenditoriale grezza in un business plan completo, coerente e
verificabile, governando un processo stage-based con subagent verticali lanciati
a runtime e artefatti persistenti come memoria del progetto.

**Questo file instrada. Non contiene il manuale metodologico** — quello vive
nei moduli di [`methodology/`](methodology/principles.md), caricati **solo
quando servono** (politica di caricamento del contesto, §20 della specifica
architetturale [`reference/architecture.md`](reference/architecture.md)).

Versione del pacchetto: **0.7.1** — Stage 0–13 implementati.

## Convenzioni di esecuzione

- `<skill_dir>` è la directory che contiene questo `SKILL.md` (con
  l'installazione standard: `~/.claude/skills/business-plan-orchestrator`).
  Tutti gli script si invocano con il path assoluto, per esempio
  `python "<skill_dir>/transaction/transaction_manager.py" governance-status --project <project> ...`.
- `<project>` è la cartella del progetto, creata nella **working directory
  corrente** dell'utente.
- Gli script richiedono **Python 3.12** e il pacchetto **`jsonschema`**
  (nessun'altra dipendenza di terze parti). Se `python` o `jsonschema` non
  sono disponibili, fermati e dillo all'utente: senza validator e
  transaction manager nessuno stage 1+ può essere chiuso.

## Principio guida (non negoziabile)

> Evidenze prima della narrativa. Driver prima delle percentuali. Cassa prima
> dell'utile. Milestone prima del funding. Executive summary per ultimo.

Dettaglio operativo di ciascun principio:
[`methodology/principles.md`](methodology/principles.md).

## Cosa fa l'orchestratore (in sintesi — dettaglio in `reference/architecture.md` §6)

Legge il contesto del progetto → identifica lo stage corrente → classifica la
startup → carica solo la metodologia rilevante → verifica prerequisiti/dipendenze
→ formula domande mirate → lancia uno o più subagent a runtime → valida gli output
contro lo schema → aggiorna i registri → rileva incoerenze → apre un decision gate
→ blocca lo stage se ci sono criticità materiali → crea l'handoff → avvia lo stage
successivo.

**Non fa:** scrivere direttamente tutte le sezioni, duplicare output dei subagent,
introdurre assunzioni non registrate, correggere in silenzio dati incoerenti,
caricare l'intero progetto in ogni prompt, lanciare tutti i subagent disponibili.

## Regola di posizione

I **progetti** si creano nella **working directory corrente** dell'utente,
**mai** dentro `<skill_dir>` né dentro un checkout del repository della skill.

## Stato corrente: stage → workflow → gate

| Stage | Cartella | Workflow | Runtime-agent | Gate (deve essere vero per chiudere) |
|---|---|---|---|---|
| 0 — Idea discovery | `00_idea-discovery/` | [`workflows/00_project-initialization.md`](workflows/00_project-initialization.md) poi [`workflows/01_idea-discovery.md`](workflows/01_idea-discovery.md) | `founder-interviewer` | Concept comprensibile, startup classificata, destinatario identificato, output definiti, assunzioni iniziali registrate, data gap espliciti, prompt contract approvato (`reference/architecture.md` §8.6) |
| 1 — Problema e bisogno | `01_problem-and-need/` | [`workflows/02_problem-and-need.md`](workflows/02_problem-and-need.md) | `customer-problem-analyst` | Problema misurabile e falsificabile; ≥1 evidenza classificata; percepito/dimostrato esplicito; validator egress exit 0; transazione `committed` |
| 2 — Customer segmentation | `02_customer-segmentation/` | [`workflows/03_customer-segmentation.md`](workflows/03_customer-segmentation.md) | `customer-problem-analyst` | ≥1 segmento (`SEG-`) ancorato al problema; ruoli user/buyer/DM separati; beachhead con criterio; validator egress exit 0 |
| 3 — Value proposition | `03_value-proposition/` | [`workflows/04_value-proposition.md`](workflows/04_value-proposition.md) | `value-proposition-strategist` | VPC mappato su Stage 1–2; ogni claim con proof o marcato assunzione; **checkpoint evidenze**: solo assunzioni ⇒ max `approved_with_conditions` con `COND-` (validation_action, owner, due_before_stage) |
| 4 — Mercato e concorrenza | `04_market-and-competition/` | [`workflows/05_market-and-competition.md`](workflows/05_market-and-competition.md) | `market-competition-analyst` | SOM bottom-up ricalcolabile; `SOM ≤ SAM ≤ TAM`; riconciliazione dei metodi di sizing se ≥2 metodi; ogni categoria competitor valutata (`none_identified` motivato); `validate_market_arithmetic` exit 0 |
| 5 — Business model | `05_business-model/` | [`workflows/06_business-model.md`](workflows/06_business-model.md) | `business-model-analyst` | Prezzo = un solo `ASS-` positivo; ricavo = formula di driver; contribution margin calcolato (pricing tra le `variables`); prezzo duplicato == ASS-pricing (`price_conflict` altrimenti); `validate_unit_economics` + `validate_cross_stage_consistency` exit 0 |
| 6 — Go-to-market | `06_go-to-market/` | [`workflows/07_go-to-market.md`](workflows/07_go-to-market.md) | `go-to-market-analyst` | Funnel completo ricalcolabile (`customers_out` = lead × Π(tassi)); `CAC = spend / customers_out`; churn esplicito; capacità GTM ≥ SOM o ciclo di conflitto aperto (`gtm_capacity_below_som`); stesso `pricing_ref` dello Stage 5; `validate_funnel_arithmetic` exit 0 |
| 7 — Operations e IP | `07_operations-and-ip/` | [`workflows/08_operations-and-ip.md`](workflows/08_operations-and-ip.md) | `operations-ip-analyst` | Processi core (`OPS-`) con make/buy/partner; capacità operativa (`ASS-` derived) ≥ `customers_out` GTM o ciclo di capacità operativa aperto (`ops_capacity_below_gtm`); costi operativi referenziati ai COGS Stage 5 (`ops_cost_divergence` altrimenti); dipendenze e requisiti normativi valutati; strategia IP esplicita; `validate_operations_feasibility` exit 0 |
| 8 — Team e governance | `08_team-and-governance/` | [`workflows/09_team-and-governance.md`](workflows/09_team-and-governance.md) | `team-governance-analyst` | Ogni processo core (`OPS-`) dello Stage 7 coperto da almeno un `ROLE-` (`core_process_unowned` altrimenti); ogni capability gap con una risposta reale — hiring, advisor o `COND-` esistente (`capability_gap_unaddressed`), altrimenti mai `approved` pieno; ogni area di decision right con **esattamente un** owner (`decision_right_ambiguous`); `equity_split` in `[0,1]` con somma ≤ 1 (`equity_sum_exceeds_one`); FTE e costi headcount come `ASS-` referenziati (`fte_not_ref`); `validate_team_and_governance` exit 0 |
| 9 — Roadmap e milestone | `09_roadmap-and-milestones/` | [`workflows/10_roadmap-and-milestones.md`](workflows/10_roadmap-and-milestones.md) | `milestone-planner` | Grafo `depends_on` aciclico e risolvibile (`milestone_cycle_detected`, `milestone_dependency_unresolved`); date ISO-8601 con `target ≥ start` e `start ≥ target` delle dipendenze, confine incluso (`milestone_date_incoherent`); ogni milestone con un solo `owner_ref` verso un `ROLE-` dello Stage 8 (`milestone_owner_unresolved`), `cost_ref` verso un driver esistente e mai un importo inline (`milestone_cost_unresolved`), criteri misurabili, go/no-go ed exit criteria (`milestone_criteria_missing`); tutte e quattro le categorie coperte (`milestone_category_not_assessed`); `financial_plan_inputs` completo e risolvibile (`financial_input_unresolved`); `validate_milestone_chain` exit 0 |
| 10 — Piano finanziario | `10_financial-plan/` | [`workflows/11_financial-plan.md`](workflows/11_financial-plan.md) | `financial-modeller` | Documento canonico conforme a `schemas/financial-plan.schema.json`; una sola fonte numerica di verità e nessun ricalcolo silenzioso; moduli e scenari completi o `NOT_APPLICABLE` con motivazione nominata; riconciliazioni `REC-*` chiuse; `validate_financial_output` exit 0 |
| 11 — Funding request | `11_funding-request/` | [`workflows/12_funding-request.md`](workflows/12_funding-request.md) | `funding-strategist` | Proiezione sul canonico dello Stage 10, mai un secondo motore: ingresso incompleto respinto prima di ogni scrittura (`fr_input_incomplete`); `requested_capital` riconciliato alla misura nominata da `modeled_need_ref` entro `EUR 0.01`; impieghi che sommano al capitale richiesto e percentuali a 100; `runway_to_zero` e `runway_to_buffer` mai collassati; `residual_gap_disclosed` vincolato a `true`; nessun termine finanziario inventato; `validate_funding_request` exit 0 |
| 12 — Data room | `12_data-room/` | [`workflows/13_data-room.md`](workflows/13_data-room.md) | `evidence-analyst` | Strato di evidenza dell'intero piano, non un contenitore di allegati: undici sezioni come partizione logica del manifest, nessuna cartella fisica; ogni documento indicizzato al proprio path esistente, mai copiato, spostato o riscritto (`data_room_source_mutated`); `DR-*` e `CLM-*` in forma canonica, `CLM-*` allocati solo qui per ogni claim materiale; claim senza evidenza probatoria esposti (`data_room_unsupported_claim`), lacune mai soppresse (`data_room_evidence_gap_suppressed`), evidenze opposte in `INCOERENZA RILEVATA` (`data_room_conflicting_evidence`); `validate_data_room` exit 0 |
| 13 — Document generation | `13_document-generation/` | [`workflows/14_document-generation.md`](workflows/14_document-generation.md) | `business-plan-writer` | Assemblatore, non nuovo ragionamento: diciassette capitoli in ordine fisso dai soli canonici JSON degli Stage 1–12 e dai registri; ogni carattere è verbatim canonico, modello costante senza cifre o letterale legato `BND-*` (`docgen_untraced_value`); ingressi byte-identici ai checksum della Data Room (`docgen_input_stale`), base finanziaria non stantia (`docgen_financial_basis_stale`), stesso legame per lo stesso numero ovunque (`docgen_binding_divergent`), etichetta epistemica su ogni valore di assunzione (`docgen_assumption_promoted`), disclosure mai soppresse (`docgen_disclosure_suppressed`); `validate_document_generation` exit 0. **Ultimo stage e `release_boundary`: l'`advance-stage` porta il progetto allo stato terminale** — predicato: `current_stage` = `13_document-generation` ∈ `completed_stages`, `status` `approved`, `current_task` `plan-complete`; poi `--publish` scrive `output/business-plan.md`. Nessuno Stage 14 |

Numerazione dei file: lo Stage 0 usa `00_project-initialization.md` e
`01_idea-discovery.md`; dallo Stage 1 in poi il workflow `NN_…` serve lo stage
`NN-1` (Stage 1 → `02_problem-and-need.md`, … Stage 9 →
`10_roadmap-and-milestones.md`, Stage 10 → `11_financial-plan.md`, Stage 11 →
`12_funding-request.md`, Stage 12 → `13_data-room.md`, Stage 13 →
`14_document-generation.md`).

**Avanzamento tra stage.** Ogni `advance-stage` committato dal transaction
manager aggiunge lo stage a `completed_stages`, porta `current_stage` allo
stage successivo con `status = not_started` e calcola `next_action` nella
stessa transazione: riprendi sempre da lì. Dallo Stage 9 si prosegue allo
Stage 10: `financial_plan_inputs` è il contratto di **sole referenze** con
cui la roadmap consegna milestone e driver al piano finanziario (nessun
calcolo allo Stage 9). Solo l'`advance-stage` dello Stage 13 porta il
progetto allo **stato terminale** del piano.

## Pipeline transazionale (vincolante per gli Stage 1+)

Ogni stage 1+ segue `candidate → validation → transaction manager`: i
subagent scrivono **solo** in `<stage_dir>/.working/<tx>/` (proposte
`P-ASS-*`); i validator eseguibili (`<skill_dir>/validators/`) girano nelle
fasi `ingress/candidate/egress/impact`; **l'unico scrittore canonico** è
`<skill_dir>/transaction/transaction_manager.py`
(`apply`/`advance-stage`/`recover`/`governance-status`/`update-assumption`/`resolve-condition`/`show-assumption`),
con journal in `shared/.tx/` e rollback/recovery. Validator exit ≠ 0 ⇒ stop:
nessuna scrittura canonica, solo aggiornamento di governance. Dettaglio
operativo nei workflow di stage.

**Mutazioni del canonico già scritto.** Due sole vie, mai un edit dei
registri:

- **aggiornare un `ASS-*` confermato** (ciclo di conflitto o revisione volontaria):
  `show-assumption` per leggere record e `record_hash`, poi
  `update-assumption --changes <file>` con `operation_id`, payload
  `decision` obbligatorio e `expected_record_hash` per ogni change. Il
  comando esegue da sé la matrice impact **prima** del commit: un esito
  `impact_validation_failed` lascia il canonico byte-identico;
- **chiudere una `COND-*`**: `resolve-condition` con `--operation-id` e
  `--decision` sempre obbligatori; `resolved` richiede anche
  `--evidence-ref`, `waived` lo vieta. La scrittura diretta del
  `conditions-register` da parte dell'orchestratore è **vietata**.

**Release boundary.** L'ultimo stage implementato è dichiarato in
`config/enforcement-config.json` (`release_boundary`) e in 0.7.1 coincide con
l'ultimo stage del processo, `13_document-generation`. Il transaction manager
risponde `stage_not_implemented` (exit 1) a qualunque operazione oltre quel
confine; non esiste uno Stage 14.

## Come rilevare lo stage corrente (nuova sessione o resume)

All'avvio, se esiste già un progetto nella cwd (`<slug>/shared/project-status.md`):

1. Leggi, in quest'ordine (`reference/architecture.md` §13.3): `shared/project-status.md` →
   `shared/project-config.json` → `shared/assumptions-register.json` →
   `shared/evidence-register.json` → `shared/decision-log.md` → l'ultimo
   `handoff.md` dello stage `current_stage` → gli output già prodotti nello stage.
2. **Non riaprire** stage già `approved` senza un motivo esplicito e senza
   creare un'issue.
3. Riprendi da `next_action` in `project-status.md`.

Se non esiste ancora un progetto: avvia
[`workflows/00_project-initialization.md`](workflows/00_project-initialization.md).

## Runtime-check delle capability esterne

Prima di invocare una capability, verificane la disponibilità reale. Se assente,
usa il fallback locale e **dichiaralo** all'utente — non fingere che la capability
esista.

| Capability | Invocazione preferita | Fallback locale |
|---|---|---|
| Step-back analysis | `/step-back-prompting` | [`fallbacks/step-back-prompting.md`](fallbacks/step-back-prompting.md) |
| Reverse prompting | `/reverse-prompting` | [`fallbacks/reverse-prompting.md`](fallbacks/reverse-prompting.md) |
| Prompt contract | `/prompt-contracts` | [`fallbacks/prompt-contracts.md`](fallbacks/prompt-contracts.md) |
Registra l'esito del check in `shared/project-config.json` → `capability_map`
(schema: [`schemas/project-config.schema.json`](schemas/project-config.schema.json)).
Le voci `goal`, `grant` e `skill_creator` della `capability_map` si
registrano come disponibilità osservata: in 0.7.1 **non** esiste un review
loop finale avversariale (§16–§18 della specifica non sono implementati) e
l'orchestratore non deve simularlo né annunciarlo. Al termine dello Stage 13
dichiara al founder che una revisione avversariale finale non è stata
eseguita.

## Sezione 0 — avvio rapido

Flow obbligatorio (dettaglio in
[`workflows/01_idea-discovery.md`](workflows/01_idea-discovery.md)):

```text
idea grezza → step-back → reverse-prompting → domande mirate (founder-interviewer)
→ classificazione startup → prompt-contract → concept consolidato
→ registri iniziali → gate → (solo se approvato) creazione sezioni 01–12 → handoff
```

Le sezioni successive **non vengono create** finché il `prompt-contract.md` non è
`approved` (`reference/architecture.md` §8.6). La cartella dello Stage 13
nasce quando lo stage si apre.

## Gestione delle incoerenze

**Regola obbligatoria — un solo registro autorevole, verifica sempre visibile:**
`shared/assumptions-register.json` è l'unica fonte da consultare per sapere
se un valore quantitativo è già stato fissato (Principio 2). Prima di
scrivere un valore quantitativo o un claim rilevante in **qualunque** file,
mostra esplicitamente nella tua risposta (non solo internamente) una riga
tipo `🔍 Verifica persistenza — variabile: <nome>` seguita dall'esito della
ricerca in `assumptions-register.json`. Se non trovi nulla, crea una nuova
voce e procedi. Se trovi una voce con valore diverso, **non scrivere né
propagare nulla**: mostra il blocco sotto usando l'**ID esistente** (mai un
ID nuovo per la stessa variabile) e attendi conferma esplicita dell'utente.
Quando citi un'assunzione in un messaggio, l'ID citato deve **sempre**
coincidere con quello effettivamente scritto/aggiornato in quel turno.
Dettaglio con esempio in
[`workflows/01_idea-discovery.md`](workflows/01_idea-discovery.md) →
"Regola di persistenza".

**Protocollo a stati vincolante:** applica il protocollo machine-readable in
[`checks/persistence-conflict-protocol.json`](checks/persistence-conflict-protocol.json)
ogni volta che un valore quantitativo o claim rilevante viene proposto,
precisato o sostituito. Gli stati operativi sono:

- `NO_CONFLICT`: valore non ancora persistito, stesso valore gia' persistito,
  o semplice precisazione non confliggente. Puoi scrivere normalmente dopo la
  verifica visibile.
- `CONFLICT_DETECTED_AWAITING_CONFIRMATION`: esiste un valore ufficiale
  persistito e l'utente propone un valore diverso. In questo stato sono vietate
  tutte le scritture e propagazioni del nuovo valore; mostra `INCOERENZA
  RILEVATA` e chiedi una conferma esplicita in un turno successivo.
- `CHANGE_REJECTED_OR_UNCONFIRMED`: risposta ambigua, non confermativa o
  rifiuto. Il valore persistito resta invariato; non scrivere decisioni finali.
- `CHANGE_CONFIRMED`: solo una conferma esplicita arrivata in un turno utente
  successivo autorizza l'aggiornamento della stessa voce `ASS-*`, la
  preservazione dello storico, il `decision-log.md` e la propagazione.

La proposta iniziale e la conferma valida non possono appartenere allo stesso
turno utente. Se l'utente scrive "portiamo il prezzo a 7,99" nello stesso
messaggio in cui formula la proposta, quello e' ancora il turno di proposta:
devi rilevare il conflitto e attendere un turno successivo prima di scrivere.

Quando rilevi un valore divergente per la stessa variabile in file diversi, usa
**sempre** questo formato (mai mediare, mai scegliere il più recente, mai
trattarlo come refuso):

```text
INCOERENZA RILEVATA

ID: ISSUE-<progressivo>
Variabile: <nome>
Valore A: <valore> (<file>)
Valore B: <valore> (<file>)
Impatto: <sezioni/registri coinvolti>
Severità: Critical | High | Medium | Low
Decisione richiesta: <opzioni>
File coinvolti: <lista>
```

## Classi di evidenza (mai silenziosamente promosse a fatto)

`verified_fact` · `internal_evidence` · `external_source` · `founder_assumption`
· `model_estimate` · `missing_information` — dettaglio in
[`methodology/evidence-framework.md`](methodology/evidence-framework.md).

## Riferimenti

- Specifica architetturale: [`reference/architecture.md`](reference/architecture.md)
- Moduli metodologici: [`methodology/principles.md`](methodology/principles.md),
  [`methodology/startup-classification.md`](methodology/startup-classification.md),
  [`methodology/evidence-framework.md`](methodology/evidence-framework.md) e un
  modulo per ciascuno stage in `methodology/`
- Template: [`templates/prompt-contract.md`](templates/prompt-contract.md),
  [`templates/section-handoff.md`](templates/section-handoff.md),
  [`templates/discovery-questionnaire.md`](templates/discovery-questionnaire.md),
  [`templates/brainstorming-log.md`](templates/brainstorming-log.md)
- Runtime agent: un file per ruolo in `runtime-agents/` (colonna "Runtime-agent" della tabella)
- Schemi di validazione: `schemas/*.schema.json`
- Configurazione di enforcement: [`config/enforcement-config.json`](config/enforcement-config.json)
