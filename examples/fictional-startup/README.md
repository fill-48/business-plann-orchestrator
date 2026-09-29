> **Esempio completamente fittizio.** Azienda, persone, interviste, numeri e fonti sono inventati a scopo dimostrativo; ogni riferimento a realtà esistenti è casuale.

# Esempio: TurniDemo (startup fittizia)

TurniDemo è una startup inventata: un SaaS per la pianificazione dei turni del
personale nelle piccole catene retail e di ristorazione (5-50 punti vendita),
che oggi organizzano i turni a mano. Il progetto mostra come
`business-plan-orchestrator` porta un'idea grezza, stage dopo stage, fino a
un piano con registri coerenti e numeri ricalcolabili.

## Stato

Gli Stage 0–9 sono completati. Il progetto è fermo all'inizio dello Stage 10
(Financial plan): `shared/project-status.md` riporta
`current_stage: 10_financial-plan`, `status: not_started` e
`next_action: avviare 10_financial-plan`. Gli Stage 10–13 (financial plan,
funding request, data room, generazione del documento) non sono ancora stati
eseguiti.

## Contenuto delle cartelle

| Cartella | Contenuto |
|---|---|
| `00_idea-discovery/` | Idea grezza, brainstorming, risposte del founder, concept, prompt contract, QA e handoff della Sezione 0 |
| `01_problem-and-need/` | Problema e bisogno: bozza di sezione, output strutturato, handoff |
| `02_customer-segmentation/` | Segmenti di clientela, ruoli (user/buyer/decision maker) e beachhead |
| `03_value-proposition/` | Value proposition, mappa pain/gain e proof point |
| `04_market-and-competition/` | TAM/SAM/SOM riconciliati e landscape competitivo |
| `05_business-model/` | Prezzo, ricavo come formula di driver, contribution margin |
| `06_go-to-market/` | Funnel commerciale, CAC, churn e capacità commerciale |
| `07_operations-and-ip/` | Processi core, dipendenze critiche, requisiti normativi, strategia IP |
| `08_team-and-governance/` | Ruoli, gap di competenze, piano assunzioni, governance e cap table |
| `09_roadmap-and-milestones/` | Milestone con criteri go/no-go e input per il financial plan |
| `shared/` | Stato del progetto, configurazione, registri di assunzioni, evidenze, fonti, rischi, decisioni e condizioni, decision log e domande aperte |

## Come usarlo

1. Copia la cartella `fictional-startup/` in una directory di lavoro a tua
   scelta, fuori da questo repository.
2. Apri Claude Code in quella directory, con la skill installata.
3. Invoca `/business-plan-orchestrator`: la skill legge
   `shared/project-status.md` e riprende dallo Stage 10.

Lavora sempre su una copia: nel repository la cartella è anche un fixture in
sola lettura usato dai test di integrazione, quindi non va modificata.

## Avvertenza

Esempio fittizio a scopo dimostrativo. Non è un caso aziendale reale, non è
una consulenza finanziaria, legale o fiscale e i suoi numeri non vanno usati
per decisioni di investimento.
