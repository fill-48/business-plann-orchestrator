# Metodologia — Roadmap e milestone (Stage 9)

> Caricare **solo** quando si lavora su `09_roadmap-and-milestones/` (workflow
> `10_roadmap-and-milestones.md`). Fonte:
> [`reference/architecture.md`](../reference/architecture.md) §10 (Stage 9).
> Enforcement: `validate_milestone_chain` +
> `validate_referential_integrity` + `validate_cross_stage_consistency`.
>
> La domanda dello stage non è «quando faremo le cose», è **«qual è la
> sequenza di impegni verificabili che rende eseguibile questo business
> model»**. Un calendario non è una risposta.

## 1. Inventario delle milestone

Parti dagli impegni che gli Stage 6–8 hanno già reso obbligatori: i processi
core da attivare (Stage 7), i ruoli da coprire e le assunzioni pianificate
(Stage 8), i volumi e i canali da aprire (Stage 6). Ogni impegno che richiede
tempo, denaro e una decisione di andare avanti o fermarsi è una milestone
(`MIL-`). Ciò che non richiede una decisione non è una milestone: è
un'attività, e le attività non stanno in questo piano.

## 2. Milestone di esito, non di attività

Una milestone dichiara un **esito osservabile**, non uno sforzo. «Sviluppare
il modulo di provisioning» è un'attività; «provisioning attivo su 10 clienti
pilota con lead time < 48h» è un esito. La differenza è operativa, non
stilistica: solo un esito può essere verificato, e solo ciò che è verificabile
può reggere un go/no-go. Il test è semplice: se non riesci a scrivere come
sapresti che è successo, non è una milestone.

## 3. Categorie

Il vocabolario canonico è chiuso: `technical`, `commercial`, `operational`,
`organizational`. Le **categorie** non sono un'etichetta redazionale, sono una
lista di controllo: una roadmap che ha solo milestone tecniche sta dicendo
che il prodotto è l'unico rischio, il che è quasi sempre falso. Ogni categoria
deve essere coperta da almeno una milestone
(`milestone_category_not_assessed`). A differenza delle dipendenze critiche
dello Stage 7, **non esiste** una forma di categoria dichiarata assente con
motivazione: lo schema non la prevede, quindi un vuoto qui è un difetto di
pianificazione da risolvere, non da documentare.

## 4. Il grafo delle dipendenze (DAG)

`depends_on[]` descrive un vincolo **reale** di precedenza: B dipende da A
solo se B non può iniziare finché A non ha prodotto il proprio esito. Non è
un promemoria di priorità e non è un'abitudine di calendario.

Il grafo che ne risulta dev'essere un **DAG**: aciclico. Un ciclo — anche a
due nodi, anche l'auto-dipendenza — significa che nessuna delle milestone
coinvolte può mai iniziare (`milestone_cycle_detected`). Un grafo
**disconnesso** è invece legittimo: due filoni indipendenti sono la norma in
una startup che porta avanti prodotto e canale in parallelo. Anche il
riferimento in avanti dentro l'array è legittimo, perché la risoluzione
avviene dopo la raccolta completa delle definizioni; un riferimento a una
`MIL-` che non esiste, no (`milestone_dependency_unresolved`).

## 5. Critical path

Il **critical path** è la catena di dipendenze più lunga: la sequenza che
determina la data di arrivo e su cui ogni slittamento si propaga interamente.
Dichiaralo esplicitamente in `analysis.md` e per ogni anello indica che cosa
succede se slitta di un mese. Una roadmap senza critical path dichiarato è
una roadmap in cui nessuno sa quale ritardo è tollerabile e quale no. Se il
critical path non lascia margine su nessun anello, il piano slitta al primo
imprevisto: dichiaralo, non arrotondarlo.

## 6. Logica delle date

Le date sono ISO-8601 nella forma estesa `YYYY-MM-DD`, l'unica ammessa: una
data non interpretabile non è una data (`invalid`). Due regole dure
(`milestone_date_incoherent`):

- `target_date ≥ start_date` — una milestone non chiude prima di aprire;
- `start_date ≥ target_date` di **ogni** dipendenza — nessuna milestone
  inizia prima che il proprio prerequisito sia chiuso. Il **confine è
  incluso**: partire il giorno stesso in cui chiude il prerequisito è
  ammesso, ed è anzi il caso normale di una staffetta ben pianificata.

Un buco molto lungo fra la chiusura di una dipendenza e l'avvio di chi ne
dipende è segnalato (`long_gap_between_milestones`): non è un errore, ma è
quasi sempre o un'attività non dichiarata o un mese di cassa che nessuno ha
messo a piano.

## 7. Owner e accountability

Ogni milestone ha **un solo** `owner_ref`, ed è un `ROLE-` dichiarato allo
Stage 8 (`milestone_owner_unresolved`). Non un nome di persona, non un team,
non «il founder»: il ruolo, perché è il ruolo che lo Stage 8 ha finanziato e
di cui ha dichiarato l'FTE. Una milestone assegnata a un `ROLE-` che allo
Stage 8 è una posizione aperta non ancora finanziata è una milestone la cui
data è **condizionata**: va detto, non nascosto.

## 8. Risorse e driver di costo

Il costo di una milestone è un **riferimento** (`cost_ref` → `ASS-`/`P-ASS-`),
mai un importo scritto in chiaro (`milestone_cost_unresolved`). Il dato vive
una sola volta nel registro delle assunzioni, con la sua classe di evidenza:
un costo stimato è `model_estimate`, non un fatto. Questo non è formalismo
contabile: è ciò che permette a un aggiornamento confermato di propagarsi a
tutta la catena invece di lasciare copie divergenti sparse nel piano.

## 9. Criteri di successo

`success_criteria[]` non è mai vuoto e non è mai generico
(`milestone_criteria_missing`). Un criterio è misurabile quando contiene una
grandezza, una soglia e un orizzonte: «CAC ≤ 250 EUR per due mesi
consecutivi», non «acquisizione efficiente». Dove possibile il criterio
referenzia gli stessi driver del funnel e delle operations, così che il
successo della milestone e la coerenza del modello siano la stessa cosa.

## 10. Regole go/no-go

`go_no_go_rule` è la regola con cui si decide se **proseguire, correggere o
fermarsi** quando la milestone arriva a scadenza. Deve contenere una soglia
decidibile da chiunque, non un giudizio: «Go se la retention pilota ≥ 70%,
altrimenti riprogettazione dell'onboarding prima di aprire il canale». Una
regola senza soglia è un'intenzione di guardare i numeri.

## 11. Exit criteria

`exit_criteria` dichiara quando la milestone è **chiusa**, ed è distinto sia
dall'obiettivo sia dai criteri di successo: descrive lo stato stabile che
consente alle milestone dipendenti di partire («runbook operativo approvato e
collaudato», non «provisioning industrializzato»). Ripetere l'obiettivo qui è
il modo più comune di lasciare una milestone aperta per sempre.

## 12. Qualità delle evidenze

Le sei classi valgono anche qui. Un contratto con una data è
`verified_fact`; una data proposta dal founder è `founder_assumption`; un
costo calcolato dai driver è `model_estimate`; una durata presa da un
benchmark di settore è `external_source`; una milestone di cui non si sa
ancora stimare la durata è `missing_information` — e va dichiarata come tale,
non tirata a indovinare. Nessuna promozione silenziosa a fatto.

## 13. Incertezza e condizioni aperte

Quando un vincolo non è risolvibile entro lo stage (un'autorizzazione
regolatoria, un socio da deliberare, un budget da confermare) la forma onesta
è una `COND-` con `validation_action`, `owner` e `due_before_stage`, non una
data ottimistica. Una `COND-` aperta la cui scadenza cade dentro la finestra
di una milestone è un **vincolo di sequenza** e va dichiarato. Le condizioni
si chiudono **solo** con `transaction_manager.py resolve-condition`, mai a
mano.

## 14. Conflitti retrogradi con Stage 6, 7 e 8

La roadmap è il punto in cui le promesse degli stage precedenti diventano
verificabili, quindi è anche il punto in cui le loro incoerenze emergono:

- un target commerciale oltre la capacità operativa o i volumi del funnel →
  segnale `milestone_target_above_capacity` qui, detect bloccante
  `ops_capacity_below_gtm` nel cross-stage;
- una milestone che presuppone persone che lo Stage 8 non ha né assegnate né
  finanziate → `headcount_capacity_incoherent` sul processo core interessato;
- un costo di milestone che duplica un costo già a registro con valore
  diverso → il dato deve vivere una sola volta.

In tutti i casi vale il ciclo di capacità operativa (ciclo di conflitto
sull'`ASS-`): **mai** riscrivere uno stage approvato.
Si apre il conflitto sull'`ASS-` interessato, si attende la conferma
esplicita dell'utente in un turno successivo, si applica con
`update-assumption` (che esegue CAS, storico, `DEC-` e matrice impact prima
del commit) e si risottomette.

## 15. `financial_plan_inputs` — l'interfaccia verso lo Stage 10

`financial_plan_inputs` è un **contratto di sole referenze** (contratto
`financial_plan_inputs`):
`pricing_ref`, `cogs_refs[]`, `funnel_customers_ref`, `churn_ref`,
`ops_capacity_ref`, `headcount_driver_refs[]`, `milestone_cost_refs[]`,
`som_ref`. Ogni chiave deve risolvere a un `ASS-`/`P-ASS-` esistente e
`milestone_cost_refs[]` deve includere il costo di **ogni** milestone del
piano, altrimenti quel costo resterebbe invisibile al piano finanziario
(`financial_input_unresolved`).

Che cosa **non** contiene, deliberatamente: nessun valore numerico
duplicato, nessuna formula, nessuna proiezione, nessun conto economico,
nessun flusso di cassa, nessuna richiesta di funding. La roadmap consegna i
driver, non i risultati: il piano finanziario che li usa è lo Stage 10
`10_financial-plan`.

## 16. Criteri di completezza (gate dello stage)

1. Grafo `depends_on` aciclico e interamente risolvibile.
2. Date ISO-8601 coerenti internamente e con le dipendenze.
3. Ogni milestone con un solo `owner_ref` verso un `ROLE-` esistente.
4. Ogni milestone con `cost_ref` verso un driver esistente.
5. Ogni milestone con criteri misurabili, go/no-go ed exit criteria.
6. Tutte e quattro le categorie coperte.
7. `financial_plan_inputs` completo e risolvibile.
8. Ogni rischio referenziato a un `RISK-` del risk-register.

## 17. Failure mode e anti-pattern

- **Roadmap circolare**: A dipende da B che dipende da A — nessuna delle due
  può iniziare → `milestone_cycle_detected`.
- **Milestone orfana**: nessun owner, o un owner che non è un `ROLE-` dello
  Stage 8 → `milestone_owner_unresolved`.
- **Date incompatibili con le dipendenze**: una milestone che parte prima che
  il proprio prerequisito chiuda → `milestone_date_incoherent`.
- **Costo scritto a mano**: un importo inline invece di un `cost_ref` → il
  dato vive due volte e diverge alla prima revisione
  (`milestone_cost_unresolved`).
- **Milestone senza esito misurabile**: criteri generici, go/no-go senza
  soglia, exit criteria che ripete l'obiettivo →
  `milestone_criteria_missing`.
- **Piano finanziario anticipato**: proiezioni, conto economico o cash flow
  dentro lo Stage 9 — è lo Stage 10.
- **Date ottimistiche non sostenute**: target che presuppongono capacità
  operativa o organico che nessuno ha dichiarato né finanziato →
  `milestone_target_above_capacity`, `headcount_capacity_incoherent`.
- **Categorie omesse o dichiarate senza valutazione**: una roadmap tutta
  tecnica che tace su canale, operations e organizzazione →
  `milestone_category_not_assessed`.
- **Interfaccia incompleta**: `financial_plan_inputs` che dimentica un driver
  o il costo di una milestone → `financial_input_unresolved`.
- **Attività travestite da milestone**: un elenco di lavori senza decisione
  associata; la roadmap diventa un diario e il go/no-go sparisce.
