# Specifica architetturale — Business Plan Orchestrator

## Business Plan Orchestrator for Claude Code

**Versione del pacchetto:** 0.7.1
**Natura del documento:** specifica di progetto (intento architetturale e principi)
**Architettura:** skill unica orchestratrice + subagent specialistici a runtime

> **Come leggere questo documento.** È la specifica di progetto da cui il
> pacchetto è stato costruito. I principi (§3), la sequenza causale (§4), la
> Sezione 0 (§8), il contratto dei subagent (§11), gli artefatti condivisi
> (§12), l'handoff (§13), i decision gate (§14) e la gestione delle
> incoerenze (§15) sono vincolanti. Dove questa specifica descrive file,
> output o funzioni che differiscono dall'implementazione, **prevalgono**
> `SKILL.md`, `workflows/`, `schemas/` e `config/enforcement-config.json`.
> Lo stato di implementazione della versione 0.7.1 è riassunto in §23.

---

## 1. Scopo del sistema

Il progetto deve implementare un agente orchestratore per Claude Code capace di trasformare un'idea imprenditoriale grezza in un business plan completo, coerente e verificabile.

Il sistema non deve limitarsi a generare testo. Deve costruire progressivamente un modello di business fondato su:

- evidenze;
- assunzioni esplicite;
- driver operativi;
- coerenza strategica;
- sostenibilità economico-finanziaria;
- roadmap milestone-based;
- funding request riconciliata con il fabbisogno di cassa;
- controlli di qualità e revisione avversariale.

Il principio architetturale centrale è:

> evidenze prima della narrativa, driver prima delle percentuali, cassa prima dell'utile, milestone prima del funding.

La metodologia operativa è articolata nei moduli di `methodology/` (un modulo per ciascuno stage, più principi, classificazione ed evidenze). Questo file definisce come la metodologia è implementata attraverso skill, workflow, subagent, artefatti persistenti, controlli e handoff.

---

## 2. Decisione architetturale

### 2.1 Modello scelto

Adottare:

> **una sola skill orchestratrice persistente, denominata `business-plan-orchestrator`, che lancia subagent verticali a runtime tramite Agent tool.**

Non creare, nella prima versione:

- una rete di agent definition persistenti in `.claude/agents/`;
- dodici skill autonome associate rigidamente ai capitoli del business plan;
- un agente monolitico che esegue tutte le attività nello stesso contesto;
- una relazione rigida del tipo `una cartella = un subagent`.

### 2.2 Razionale

Questa architettura è adeguata perché:

- il sistema sarà utilizzato inizialmente con frequenza limitata;
- il workflow deve essere ancora validato;
- la repository deve restare leggibile e pubblicabile su GitHub;
- i ruoli specialistici potranno evolvere senza modificare il controller;
- i subagent devono ricevere solo il contesto necessario;
- metodologia, workflow e output devono essere versionabili separatamente;
- gli agenti più maturi potranno essere promossi successivamente a definizioni persistenti.

### 2.3 Separazione dei livelli

Il sistema deve mantenere separati quattro livelli:

1. **Metodologia**  
   Regole e framework per costruire il business plan.

2. **Workflow**  
   Ordine degli stage, dipendenze, gate decisionali e criteri di completamento.

3. **Subagent**  
   Ruoli specialistici temporanei lanciati dall'orchestratore.

4. **Artefatti persistenti**  
   Registri, decisioni, assunzioni, evidenze, output intermedi, handoff e controlli.

---

## 3. Principi non negoziabili

### 3.1 Evidenze prima della narrativa

Ogni affermazione rilevante deve essere classificata come una delle seguenti categorie:

- `verified_fact`
- `internal_evidence`
- `external_source`
- `founder_assumption`
- `model_estimate`
- `missing_information`

Nessun subagent può trasformare silenziosamente un'ipotesi in un fatto.

### 3.2 Un solo set ufficiale di assunzioni

Tutto il sistema deve utilizzare un unico `assumptions-register.json`.

È vietato:

- introdurre assunzioni direttamente nei capitoli;
- modificare numeri senza aggiornare il registro;
- usare valori diversi in sezioni differenti;
- correggere incoerenze senza registrare la decisione.

### 3.3 Driver prima delle percentuali

Ricavi, costi e crescita devono derivare da driver espliciti.

Esempio commerciale:

```text
Ricavi
= clienti attivi
× ordini medi per cliente
× prezzo medio netto
```

Esempio SaaS:

```text
MRR finale
= MRR iniziale
+ new MRR
+ expansion MRR
- churned MRR
```

Esempio deep-tech:

```text
Fabbisogno di cassa
= costo milestone
+ overhead
+ contingency
- funding secured
```

### 3.4 Cassa prima dell'utile

Il sistema deve dare priorità a:

- burn mensile;
- runway;
- capitale circolante;
- timing degli incassi;
- timing dei pagamenti;
- capex;
- funding gap;
- fabbisogno di cassa cumulato.

Un risultato economico positivo non può essere considerato sufficiente se la cassa diventa negativa.

### 3.5 Milestone prima del funding

La funding request deve essere derivata nel seguente ordine:

```text
Milestone
→ attività
→ risorse
→ costi
→ timing dei flussi
→ fabbisogno di cassa
→ funding request
```

Non deve essere consentito il processo inverso.

### 3.6 Executive summary per ultimo

L'executive summary deve essere generato solo quando:

- tutte le sezioni sono complete;
- il financial model è validato;
- il funding request è riconciliato;
- il red-team review non rileva criticità bloccanti.

### 3.7 Scenari obbligatori

Il financial plan deve includere almeno:

- `base_case`
- `downside_case`
- `upside_case`

### 3.8 Revisione avversariale

Il sistema deve cercare attivamente:

- incoerenze numeriche;
- assunzioni non supportate;
- claim senza fonte;
- ricavi non riconciliati;
- market sizing debole;
- funding non allineato alla roadmap;
- cassa negativa non evidenziata;
- working capital ignorato;
- rischi non mitigati;
- contraddizioni tra capitoli.

---

## 4. Sequenza causale del business plan

Il workflow deve seguire la seguente catena logica:

```mermaid
flowchart LR
    A[Idea grezza] --> B[Problema reale]
    B --> C[Segmento prioritario]
    C --> D[Proposta di valore]
    D --> E[Evidenze]
    E --> F[Mercato e concorrenza]
    F --> G[Business model]
    G --> H[Go-to-market]
    H --> I[Operations e IP]
    I --> J[Team e governance]
    J --> K[Roadmap e milestone]
    K --> L[Financial plan]
    L --> M[Funding request]
    M --> N[Executive summary]
    N --> O[Red-team review]
    O --> P[Output finale]
```

L'orchestratore deve impedire che una sezione a valle venga considerata definitiva quando le dipendenze a monte sono ancora instabili.

---

## 5. Struttura del pacchetto installato

Il pacchetto si installa in `~/.claude/skills/business-plan-orchestrator/`
ed è autosufficiente: non dipende dal repository da cui è stato installato.

```text
business-plan-orchestrator/
├── SKILL.md                  controller: instrada, non contiene il manuale
├── reference/
│   └── architecture.md       questa specifica
├── workflows/                un workflow per stage (00–14, vedi SKILL.md)
├── methodology/              principi, classificazione, evidenze, un modulo per stage
├── runtime-agents/           prompt template dei subagent (§11.2)
├── templates/                prompt contract, handoff, questionario, brainstorming log
├── fallbacks/                fallback locali di step-back, reverse prompting, prompt contract
├── schemas/                  JSON Schema (Draft 2020-12) di registri e output canonici
├── config/
│   └── enforcement-config.json   ordine degli stage, matrice stage × fase × validator, tolleranze
├── checks/
│   └── persistence-conflict-protocol.json
├── profiles/                 profili del modello finanziario (generic_startup, subscription_saas)
├── transaction/
│   └── transaction_manager.py    unico scrittore canonico (journal, rollback, recovery)
├── validators/               validator deterministici eseguibili (Python)
└── output/                   costruttore del canonico finanziario, capitolo MD, export XLSX, coerenza dei derivati
```

---

## 6. Responsabilità della skill orchestratrice

Il file `SKILL.md` deve operare come controller del sistema.

Non deve contenere integralmente il manuale metodologico. Deve:

1. leggere il contesto del progetto;
2. identificare lo stage corrente;
3. classificare la startup;
4. selezionare i moduli applicabili;
5. caricare solo la metodologia rilevante;
6. verificare prerequisiti e dipendenze;
7. formulare domande mirate;
8. lanciare uno o più subagent a runtime;
9. passare a ogni subagent esclusivamente i file necessari;
10. validare gli output rispetto allo schema previsto;
11. aggiornare registri e stato del progetto;
12. rilevare incoerenze;
13. aprire decision gate;
14. bloccare lo stage se esistono criticità materiali;
15. creare l'handoff;
16. avviare lo stage successivo;
17. generare gli output finali;
18. lanciare il review loop;
19. produrre il QA report finale.

L'orchestratore non deve:

- scrivere direttamente tutte le sezioni;
- duplicare gli output dei subagent;
- introdurre assunzioni non registrate;
- correggere in silenzio dati incoerenti;
- caricare l'intero progetto in ogni prompt;
- lanciare automaticamente tutti i subagent disponibili.

---

## 7. Classificazione iniziale della startup

All'avvio, il sistema deve classificare il progetto almeno lungo queste dimensioni:

```yaml
startup_type:
  - commercial
  - saas
  - marketplace
  - consumer
  - foodtech
  - industrial
  - hardware
  - deeptech
  - biotech
  - medtech
  - service
  - hybrid

development_stage:
  - idea
  - concept
  - mvp
  - pilot
  - early_revenue
  - growth
  - preclinical
  - clinical
  - pre_seed
  - seed

primary_reader:
  - founder_internal
  - business_angel
  - venture_capital
  - corporate_partner
  - bank
  - public_grant
  - incubator
  - mixed

funding_type:
  - equity
  - debt
  - grant
  - bootstrapping
  - mixed

time_horizon:
  - 12_months
  - 24_months
  - 36_months
  - 5_years
  - custom
```

La classificazione deve modificare dinamicamente il workflow.

Esempi:

- SaaS: MRR, ARR, churn, NRR, CAC, LTV, payback.
- Marketplace: GMV, take rate, liquidity, domanda/offerta, network effects.
- Industriale: capex, capacità produttiva, supply chain, working capital.
- Foodtech: shelf life, capacità, compliance, scarti, distribuzione, riordino.
- Biotech: IP, PoC, GLP, GMP, regulatory path, burn per milestone, licensing.
- Banca: DSCR, piano di ammortamento, garanzie, covenant, scenario downside.
- Grant: eleggibilità, innovatività, impatto, work package, deliverable, TRL.

---

## 8. Sezione 0 — Idea discovery e brainstorming strutturato

### 8.1 Obiettivo

La sezione 0 deve trasformare un'idea grezza in un concept sufficientemente strutturato da poter avviare il business planning.

### 8.2 Flow obbligatorio

```text
Idea grezza
→ step-back analysis
→ reverse prompting
→ domande mirate
→ classificazione startup
→ prompt contract
→ concept consolidato
→ registri iniziali
→ piano di progetto
→ creazione cartelle
```

### 8.3 Utilizzo delle skill o dei fallback

Il sistema può usare:

- `/step-back-prompting`
- `/reverse-prompting`
- `/prompt-contracts`

Prima dell'invocazione deve verificare che la capability sia realmente disponibile.

Se non è disponibile, deve utilizzare il fallback locale corrispondente:

```yaml
required_capabilities:
  step_back_prompting:
    preferred_invocation: /step-back-prompting
    fallback: fallbacks/step-back-prompting.md

  reverse_prompting:
    preferred_invocation: /reverse-prompting
    fallback: fallbacks/reverse-prompting.md

  prompt_contracts:
    preferred_invocation: /prompt-contracts
    fallback: fallbacks/prompt-contracts.md
```

Non deve simulare una skill assente senza dichiararlo.

### 8.4 Output della sezione 0

```text
00_idea-discovery/
├── raw-idea.md
├── brainstorming-log.md
├── founder-answers.md
├── startup-concept.md
├── prompt-contract.md
├── stage-qa.md
└── handoff.md
```

File condivisi inizializzati:

```text
shared/
├── project-config.json
├── startup-profile.json
├── assumptions-register.json
├── evidence-register.json
├── source-register.json
├── risk-register.json
├── decision-log.md
├── open-questions.md
└── project-status.md
```

### 8.5 Prompt contract

Il `prompt-contract.md` deve definire almeno:

- obiettivo del progetto;
- destinatario primario;
- output richiesti;
- perimetro;
- esclusioni;
- orizzonte temporale;
- standard metodologico;
- livello di dettaglio;
- regole sulle fonti;
- regole sulle assunzioni;
- strumenti utilizzabili;
- formato degli output;
- criteri di approvazione;
- condizioni di blocco;
- responsabilità dell'utente;
- responsabilità dell'orchestratore.

### 8.6 Decision gate della sezione 0

La sezione può essere chiusa solo se:

- il concept è comprensibile;
- la tipologia di startup è classificata;
- il destinatario del piano è identificato;
- gli output sono definiti;
- le assunzioni iniziali sono registrate;
- i principali data gap sono espliciti;
- il prompt contract è approvato.

Solo dopo questo gate devono essere create le directory delle sezioni successive.

---

## 9. Struttura standard del progetto

Il progetto si crea nella working directory corrente dell'utente, mai dentro
la directory della skill.

```text
<working-directory>/
└── <project-slug>/
    ├── 00_idea-discovery/
    ├── 01_problem-and-need/
    ├── 02_customer-segmentation/
    ├── 03_value-proposition/
    ├── 04_market-and-competition/
    ├── 05_business-model/
    ├── 06_go-to-market/
    ├── 07_operations-and-ip/
    ├── 08_team-and-governance/
    ├── 09_roadmap-and-milestones/
    ├── 10_financial-plan/
    ├── 11_funding-request/
    ├── 12_data-room/
    ├── 13_document-generation/
    ├── review/
    ├── shared/
    └── output/
```

Ogni sezione deve poter contenere:

```text
<section>/
├── input.md
├── research.md
├── analysis.md
├── structured-output.json
├── section-draft.md
├── stage-qa.md
└── handoff.md
```

Non tutti i file sono obbligatori per ogni sezione. L'orchestratore deve creare solo quelli pertinenti.

---

## 10. Workflow stage-based

> Gli elenchi di output di questa sezione descrivono l'intento di progetto. I
> file effettivamente prodotti e validati da ciascuno stage (in particolare
> `structured-output.json`, `section-draft.md`, `handoff.md` e i derivati dello
> Stage 10) sono definiti dai workflow e dagli schemi del pacchetto.

### Stage 0 — Project initialization e idea discovery

**Subagent principali**

- `founder-interviewer`
- eventuale `evidence-analyst`

**Output**

- project config;
- startup profile;
- concept consolidato;
- prompt contract;
- registri iniziali;
- project status.

**Gate**

Il perimetro è sufficientemente chiaro?

---

### Stage 1 — Problema e bisogno

**Subagent**

- `customer-problem-analyst`
- eventuale `evidence-analyst`

**Obiettivi**

- formulare il problema come costo, rischio, inefficienza, perdita o unmet need;
- distinguere problema percepito e problema dimostrato;
- identificare alternative e status quo;
- stabilire priorità e intensità.

**Output**

```text
01_problem-and-need/
├── problem-definition.md
├── evidence-map.json
├── problem-hypotheses.json
├── section-draft.md
├── stage-qa.md
└── handoff.md
```

**Gate**

Il problema è rilevante, misurabile e supportato da evidenze sufficienti?

---

### Stage 2 — Customer segmentation

**Subagent**

- `customer-problem-analyst`
- eventuale `market-researcher`

**Obiettivi**

Distinguere:

- user;
- buyer;
- decision maker;
- influencer;
- beneficiary;
- payer;
- gatekeeper.

**Output**

- customer segments;
- segment prioritization;
- initial beachhead;
- buying process;
- customer evidence gaps.

**Gate**

Esiste un segmento prioritario coerente con problema, soluzione e capacità iniziale?

---

### Stage 3 — Proposta di valore

**Subagent**

- `business-model-analyst`
- `customer-problem-analyst`

**Obiettivi**

Definire:

- jobs;
- pains;
- gains;
- pain relievers;
- gain creators;
- alternative;
- switching rationale;
- value metrics;
- proof points.

**Gate**

La value proposition è verificabile e collegata a metriche concrete?

---

### Stage 4 — Mercato e concorrenza

**Subagent**

- `market-researcher`
- `market-sizing-analyst`
- `competitive-strategist`
- eventuale `evidence-analyst`

**Output**

```text
04_market-and-competition/
├── market-sources.md
├── market-model.json
├── tam-sam-som.md
├── competitive-landscape.md
├── strategic-frameworks.md
├── market-risks.md
├── section-draft.md
├── stage-qa.md
└── handoff.md
```

**Requisiti**

Il market sizing deve includere:

- approccio top-down;
- approccio bottom-up;
- riconciliazione;
- geografia;
- periodo;
- unità di misura;
- fonti;
- formule;
- assunzioni;
- sensitivity.

Il SOM non può essere una percentuale arbitraria del TAM. Deve derivare da:

- canali;
- capacità commerciale;
- capacità produttiva;
- sales cycle;
- geografie;
- risorse disponibili;
- roadmap.

La concorrenza deve includere:

- competitor diretti;
- competitor indiretti;
- sostituti;
- soluzioni interne;
- non-consumo;
- status quo.

**Gate**

Il mercato raggiungibile è coerente con risorse, canali e orizzonte temporale?

---

### Stage 5 — Business model

**Subagent**

- `business-model-analyst`
- eventuale `financial-modeller`

**Obiettivi**

Definire:

- chi paga;
- per cosa paga;
- prezzo;
- frequenza;
- contratto;
- ricorrenza;
- rinnovo;
- margine;
- canale;
- unità economica;
- logica di monetizzazione;
- eventuale licensing.

**Output**

- business model;
- pricing model;
- revenue logic;
- unit of economics;
- monetization assumptions.

**Gate**

Il modello di ricavo è traducibile in formule e driver osservabili?

---

### Stage 6 — Go-to-market

**Subagent**

- `go-to-market-analyst`
- `market-researcher`
- eventuale `financial-modeller`

**Flow minimo**

```text
lead generation
→ qualification
→ conversion
→ onboarding
→ activation
→ purchase
→ retention
→ reorder
→ upsell
→ churn
```

**Output**

- canali;
- funnel;
- sales cycle;
- CAC logic;
- retention logic;
- conversion assumptions;
- commercial organization;
- channel economics.

**Gate**

Il go-to-market può alimentare direttamente revenue engine e unit economics?

---

### Stage 7 — Operations e IP

**Subagent**

- `operations-ip-analyst`
- eventuale `risk-analyst`

**Obiettivi**

Analizzare:

- attività chiave;
- risorse chiave;
- partner;
- supply chain;
- capacità;
- make-or-buy;
- tecnologia;
- qualità;
- compliance;
- logistica;
- scalabilità;
- IP;
- know-how;
- dipendenze operative.

**Gate**

Il modello operativo può sostenere i volumi e le milestone dichiarate?

---

### Stage 8 — Team e governance

**Subagent**

- `team-governance-analyst`

**Obiettivi**

Definire:

- ruoli;
- responsabilità;
- competenze;
- commitment;
- gap;
- hiring plan;
- incentivi;
- governance;
- decision rights;
- advisory needs.

Il sistema deve dichiarare esplicitamente ciò che manca al team.

**Gate**

Il team attuale e pianificato è coerente con roadmap e budget?

---

### Stage 9 — Roadmap, milestone e rischi

**Subagent**

- `milestone-planner`
- `risk-analyst`
- eventuali specialisti di settore

**Schema milestone**

```yaml
id:
objective:
key_results:
start_date:
target_date:
owner:
dependencies:
required_resources:
estimated_cost:
success_criteria:
go_no_go_rule:
risks:
mitigations:
status:
```

**Requisiti**

Ogni milestone deve contenere:

- output;
- scadenza;
- responsabile;
- costo;
- criterio di successo;
- dipendenze;
- rischio;
- regola go/no-go.

**Gate**

La roadmap è finanziabile, verificabile e coerente con il modello operativo?

---

### Stage 10 — Financial plan

**Subagent**

- `financial-modeller`
- `bankability-analyst`, se applicabile

**Ordine obbligatorio**

```text
Assumptions
→ Revenue engine
→ Cost engine
→ Headcount plan
→ Capex
→ Depreciation
→ Working capital
→ P&L
→ Balance sheet
→ Cash flow
→ Funding schedule
→ Scenarios
→ KPI
→ Checks
```

**Output**

```text
10_financial-plan/
├── model-specification.md
├── financial-assumptions.json
├── revenue-engine.json
├── cost-engine.json
├── headcount-plan.json
├── capex-plan.json
├── working-capital.json
├── funding-schedule.json
├── scenario-model.json
├── kpi-model.json
├── financial-model.xlsx
├── financial-qa.md
└── handoff.md
```

**Contenuti minimi**

- conto economico;
- stato patrimoniale;
- cash flow;
- burn;
- runway;
- break-even;
- base case;
- downside case;
- upside case;
- sensitivity analysis;
- KPI;
- controlli automatici.

**Modulo banca**

Se `primary_reader = bank` oppure `funding_type` include debito, aggiungere:

- DSCR;
- PFN/EBITDA;
- interest coverage;
- current ratio;
- piano di ammortamento;
- garanzie;
- covenant;
- debt-service downside test.

**Gate**

Il modello finanziario riconcilia strategia, operations, roadmap e cassa?

---

### Stage 11 — Funding request

**Subagent**

- `funding-strategist`
- `bankability-analyst`, se applicabile
- eventuale `grant-readiness-reviewer`

**Classificazione delle fonti**

- `secured`
- `applied`
- `target`
- `alternative`

**Output**

- use of proceeds;
- funding request;
- runway acquistata;
- milestone finanziate;
- contingency;
- fallback scenario;
- funding roadmap alignment.

**Gate**

L'importo richiesto deriva realmente dal fabbisogno di cassa e dalle milestone?

---

### Stage 12 — Data room

**Subagent**

- orchestratore;
- eventuale `evidence-analyst`

**Obiettivi**

Creare un indice delle prove:

- fonti;
- interviste;
- contratti;
- LOI;
- brevetti;
- CV;
- offerte fornitori;
- comparables;
- ricerche;
- test;
- modelli;
- cap table;
- documenti societari;
- autorizzazioni;
- modello Excel.

---

### Stage 13 — Document generation

**Subagent**

- `business-plan-writer`

Il writer deve trasformare output già approvati in un documento coerente.

Non deve:

- inventare dati;
- aggiungere assunzioni;
- cambiare numeri;
- sostituire stime;
- ignorare il registro delle fonti;
- correggere incoerenze strutturali.

**Struttura finale**

```text
1. Executive summary
2. Company and project overview
3. Problem and customer need
4. Customer segmentation
5. Solution and value proposition
6. Market analysis
7. Competitive landscape
8. Business model
9. Go-to-market
10. Operations and technology
11. IP and defensibility
12. Team and governance
13. Roadmap and milestones
14. Risk analysis
15. Financial plan
16. Funding request and use of proceeds
17. Appendix and data room index
```

L'executive summary deve essere scritto per ultimo.

---

## 11. Subagent runtime

### 11.1 Regola generale

I subagent non devono essere associati rigidamente alle cartelle.

L'orchestratore seleziona uno o più subagent in funzione di:

- task;
- stage;
- dati mancanti;
- tipo di startup;
- destinatario;
- criticità rilevate;
- strumenti necessari.

### 11.2 Prompt template

Ogni file nella cartella `runtime-agents/` deve specificare:

```yaml
role:
objective:
scope:
required_inputs:
optional_inputs:
methodology_files:
allowed_tools:
forbidden_actions:
expected_output:
output_schema:
quality_checks:
escalation_conditions:
```

### 11.3 Contratto di esecuzione

Ogni subagent deve ricevere:

1. obiettivo;
2. perimetro;
3. file di input;
4. metodologia rilevante;
5. output schema;
6. criteri di qualità;
7. assunzioni utilizzabili;
8. vincoli;
9. condizioni di escalation.

### 11.4 Divieti

I subagent non devono:

- comunicare direttamente tra loro;
- modificare file fuori dal perimetro assegnato;
- sovrascrivere registri condivisi senza validazione;
- introdurre nuove assunzioni senza proposta esplicita;
- trattare fonti target come finanziamenti secured;
- riscrivere sezioni già approvate senza apertura di issue.

Tutti gli scambi devono passare dall'orchestratore e dagli artefatti persistenti.

---

## 12. Artefatti persistenti condivisi

### 12.1 `project-status.md`

```yaml
project_name:
current_stage:
current_task:
completed_stages:
pending_stages:
approved_decisions:
open_questions:
critical_assumptions:
blocking_issues:
last_updated:
next_action:
```

### 12.2 `assumptions-register.json`

Ogni assunzione deve contenere:

```yaml
id:
category:
statement:
value:
unit:
base_case:
downside_case:
upside_case:
source:
owner:
confidence:
validation_status:
affected_sections:
last_updated:
```

### 12.3 `evidence-register.json`

```yaml
id:
statement:
classification:
evidence_type:
source:
date:
confidence:
relevance:
affected_assumptions:
affected_sections:
validation_action:
status:
```

### 12.4 `source-register.json`

```yaml
id:
title:
publisher:
url_or_path:
publication_date:
access_date:
source_type:
quality_rating:
used_for:
notes:
```

### 12.5 `risk-register.json`

```yaml
id:
category:
risk:
probability:
impact:
severity:
early_warning_indicator:
mitigation:
contingency:
owner:
status:
```

### 12.6 `decision-log.md`

Ogni decisione deve riportare:

- data;
- decisione;
- opzioni valutate;
- motivazione;
- impatto;
- file modificati;
- approvatore.

---

## 13. Handoff tra sessioni

### 13.1 Obiettivo

Ogni sessione deve terminare con un `handoff.md`.

L'handoff non deve essere la trascrizione della sessione. Deve essere una sintesi operativa.

### 13.2 Template

```markdown
# Section Handoff

## Stato
Completed / In review / Blocked

## Obiettivo della sessione
...

## Attività completate
- ...

## Decisioni consolidate
- DEC-...

## Assunzioni utilizzate o modificate
- ASS-...

## Evidenze e fonti utilizzate
- EVD-...
- SRC-...

## Output prodotti
- ...

## Criticità
- ...

## Questioni aperte
- ...

## Dipendenze per le sezioni successive
- ...

## Azione successiva
- ...

## File da leggere nella prossima sessione
1. ...
2. ...
3. ...
```

### 13.3 Ripresa della sessione

Ogni nuova sessione deve iniziare leggendo:

1. `shared/project-status.md`;
2. `shared/project-config.json`;
3. `shared/assumptions-register.json`;
4. `shared/evidence-register.json`;
5. `shared/decision-log.md`;
6. l'ultimo `handoff.md`;
7. gli output dello stage corrente.

---

## 14. Decision gate

Ogni stage deve terminare con uno dei seguenti stati:

- `approved`
- `approved_with_conditions`
- `needs_revision`
- `blocked`
- `not_applicable`

Un gate deve riportare:

```yaml
stage:
status:
criteria_checked:
critical_issues:
conditions:
required_user_decisions:
approved_outputs:
next_stage:
```

L'orchestratore deve chiedere conferma all'utente quando la decisione:

- modifica un'assunzione critica;
- cambia il business model;
- cambia il target;
- modifica il funding request;
- introduce una fonte di finanziamento non secured;
- richiede una scelta tra scenari alternativi;
- implica la riscrittura di sezioni approvate.

---

## 15. Gestione delle incoerenze

Quando rileva un'incoerenza, l'orchestratore deve usare un formato esplicito.

```text
INCOERENZA RILEVATA

ID: ISSUE-001
Variabile: prezzo medio netto

Valore A:
€90 nel business model

Valore B:
€120 nel revenue engine

Impatto:
- ricavi
- gross margin
- cash flow
- funding need

Severità:
Critical

Decisione richiesta:
1. scegliere il valore ufficiale;
2. definire due canali distinti;
3. ricostruire il pricing model.

File coinvolti:
- ...
```

Non deve:

- mediare automaticamente i valori;
- scegliere il dato più recente senza validazione;
- trattare la divergenza come refuso;
- continuare il financial model con dati incompatibili.

---

## 16. Review loop finale

> **Non implementato in 0.7.1.** Il review loop descritto in §16, il
> red-team reviewer (§17) e la QA scorecard (§18) sono intento di progetto:
> la versione 0.7.1 non li esegue e l'orchestratore non deve simularli. Le
> verifiche deterministiche di coerenza sono svolte dai validator di ciascuno
> stage.

### 16.1 Obiettivo

Dopo il completamento delle sezioni, il sistema deve avviare un review loop finalizzato a valutare coerenza strategica, logica, finanziaria e documentale.

### 16.2 Numero massimo di iterazioni

Il loop deve prevedere:

> massimo quattro revisioni.

Non è obbligatorio effettuare quattro cicli. Il loop deve fermarsi prima se non restano criticità materiali.

### 16.3 Sequenza delle revisioni

#### Review 1 — Coerenza strategica

Valutare:

- problema;
- target;
- value proposition;
- mercato;
- business model;
- go-to-market;
- vantaggio competitivo;
- strategia.

#### Review 2 — Coerenza tra assunzioni, evidenze e numeri

Valutare:

- assunzioni duplicate;
- assunzioni senza fonte;
- numeri divergenti;
- claim non supportati;
- driver mancanti;
- SOM non riconciliato;
- pricing incoerente.

#### Review 3 — Coerenza finanziaria e funding

Valutare:

- revenue engine;
- cost engine;
- capex;
- working capital;
- cash flow;
- burn;
- runway;
- scenari;
- funding gap;
- use of proceeds;
- milestone financing;
- eventuale DSCR.

#### Review 4 — Red-team finale ed editoriale

Valutare:

- investibilità;
- chiarezza;
- completezza;
- leggibilità;
- coerenza tra testo e tabelle;
- executive summary;
- rischi;
- appendici;
- qualità delle fonti.

### 16.4 Utilizzo di `/goal` e `/grant`

Il sistema può usare:

- `/goal`
- `/grant`

Prima deve verificarne l'effettiva disponibilità.

Fallback:

```yaml
goal_review:
  preferred_invocation: /goal
  fallback: fallbacks/goal-review.md

grant_review:
  preferred_invocation: /grant
  fallback: fallbacks/grant-readiness-review.md
```

### 16.5 Regole del loop

Ogni ciclo deve:

1. leggere gli output consolidati;
2. generare una issue list;
3. classificare le issue per severità;
4. distinguere errori oggettivi da decisioni manageriali;
5. proporre correzioni;
6. correggere automaticamente solo errori deterministici;
7. richiedere approvazione per modifiche strategiche;
8. aggiornare il change log;
9. rieseguire i check impattati;
10. fermarsi se non restano issue `critical` o `high`.

---

## 17. Revisore red-team

Il `red-team-reviewer` deve comportarsi come:

- investitore scettico;
- consulente senior;
- analista finanziario;
- valutatore di bando, se applicabile;
- credit analyst, se applicabile.

Deve cercare almeno:

- market sizing puramente top-down;
- SOM irrealistico;
- customer problem non dimostrato;
- buyer e user confusi;
- pricing non validato;
- vantaggio competitivo non difendibile;
- CAC senza funnel;
- churn ignorato;
- margine calcolato in modo errato;
- capex omesso;
- working capital omesso;
- headcount non collegato alla roadmap;
- utile positivo ma cassa negativa;
- grant target trattati come secured;
- milestone non misurabili;
- funding request arbitraria;
- rischi senza mitigazioni;
- dipendenze non dichiarate;
- testo non coerente con il modello Excel.

---

## 18. QA scorecard finale

Il report deve valutare almeno:

```yaml
problem_quality:
customer_evidence:
customer_segmentation:
value_proposition:
market_quality:
competitive_analysis:
business_model:
go_to_market:
operations:
ip_and_defensibility:
team:
governance:
milestones:
risk_management:
financial_model:
cash_sustainability:
funding_request:
source_quality:
internal_consistency:
document_quality:
overall_investability:
```

Per ogni criterio:

```yaml
score:
max_score:
rationale:
critical_issues:
recommended_actions:
status:
```

---

## 19. Output finale

> **In 0.7.1** gli output effettivamente generati sono: il documento
> `output/business-plan.md` (Stage 13, diciassette capitoli), il capitolo
> `10_financial-plan/financial-plan.md` e il workbook
> `10_financial-plan/financial-model.xlsx` (Stage 10), `11_funding-request/funding-request.md`
> (Stage 11) e l'indice `12_data-room/data-room-index.md`
> (Stage 12). PDF, executive summary separato, pitch outline e QA report finale
> non sono generati.

Intento di progetto — la cartella `output/` deve contenere almeno:

```text
output/
├── business-plan.md
├── executive-summary.md
├── business-plan.pdf
├── financial-model.xlsx
├── investor-pitch-outline.md
├── data-room-index.md
├── assumptions-summary.md
├── source-register.md
├── final-qa-report.md
└── version-manifest.md
```

Il file Markdown finale deve includere:

- front matter;
- titolo;
- versione;
- data;
- indice;
- numerazione delle sezioni;
- tabelle coerenti;
- riferimenti alle fonti;
- richiami agli allegati;
- appendice;
- disclaimer sulle assunzioni;
- stato dei dati.

La generazione del PDF può essere prevista come step separato. Il Markdown resta la fonte primaria versionabile.

---

## 20. Politica di caricamento del contesto

Per limitare token, rumore e perdita di precisione:

- caricare solo il capitolo metodologico pertinente;
- caricare solo i registri necessari;
- non includere l'intero manuale in ogni prompt;
- passare ai subagent solo file rilevanti;
- usare JSON, YAML o CSV per dati strutturati;
- generare prosa solo nella fase documentale;
- usare identificativi stabili per assunzioni, evidenze, fonti e decisioni;
- sintetizzare gli output lunghi prima dello stage successivo.

---

## 21. Sicurezza metodologica

Il sistema deve distinguere chiaramente:

- ciò che sa;
- ciò che ha trovato;
- ciò che stima;
- ciò che assume;
- ciò che manca;
- ciò che richiede decisione dell'utente.

Quando non dispone di dati sufficienti deve:

1. dichiarare il gap;
2. valutare l'impatto;
3. proporre una modalità di validazione;
4. eventualmente utilizzare una stima prudenziale;
5. etichettare la stima;
6. includerla nello scenario downside.

---

## 22. Evoluzione futura

I runtime agent potranno essere promossi a definizioni persistenti in:

```text
.claude/agents/
```

Solo quando:

- il prompt è stabile;
- il ruolo è utilizzato frequentemente;
- l'output schema è maturo;
- gli strumenti necessari sono definiti;
- le responsabilità sono delimitate;
- il ruolo è riutilizzabile autonomamente;
- esistono test e metriche di qualità.

I primi candidati probabili sono:

- `financial-modeller`
- `market-researcher`
- `red-team-reviewer`

---

## 23. Stato di implementazione (0.7.1)

Implementato:

- Stage 0 — idea discovery, prompt contract, classificazione, registri iniziali;
- Stage 1–6 — problema, segmentazione, value proposition, mercato e
  concorrenza, business model, go-to-market;
- Stage 7–9 — operations e IP, team e governance, roadmap e milestone;
- Stage 10 — piano finanziario deterministico (binding dei driver, motore,
  scenari, riconciliazioni, capitolo Markdown e workbook XLSX);
- Stage 11 — funding request come proiezione del canonico finanziario;
- Stage 12 — data room come indice delle evidenze e tracciabilità dei claim;
- Stage 13 — generazione del business plan finale in Markdown;
- transaction manager con journal, rollback, recovery, aggiornamento delle
  assunzioni e chiusura delle condizioni.

Non implementato: review loop finale (§16), red-team reviewer (§17), QA
scorecard (§18), PDF/DOCX, riapertura di uno stage terminale.

---

## 24. Test

Il repository pubblico del prodotto include una suite di test deterministica
(installazione, struttura, transaction manager, validator, motore
finanziario, data room, document generation). La suite non fa parte del
pacchetto installato.

---

## 25. Criteri di completamento del sistema

Il sistema è considerato operativo quando è in grado di eseguire il seguente flusso:

```text
idea grezza
→ brainstorming strutturato
→ prompt contract
→ classificazione
→ registri iniziali
→ problema
→ cliente
→ value proposition
→ mercato
→ business model
→ go-to-market
→ operations
→ team
→ roadmap
→ financial plan
→ funding request
→ data room
→ business plan
```

Il sistema è considerato qualitativamente valido quando:

- ogni numero rilevante è riconducibile a un driver;
- ogni claim rilevante è riconducibile a una fonte o assunzione;
- ogni milestone è collegata a costo e criterio di successo;
- il funding request è collegato al cash flow;
- il business plan e il modello finanziario non si contraddicono;
- la memoria del progetto sopravvive tra sessioni.
