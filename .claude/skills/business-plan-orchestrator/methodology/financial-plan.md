# Metodologia — piano finanziario (Stage 10)

Metodologia dello Stage 10 `10_financial-plan`.
Descrive la **catena causale**, i **sei livelli** della fonte unica di verità,
i **nove divieti** normativi, la **tassonomia di validazione** e la
**governance delle assunzioni**. Non contiene alcun numero, alcuna soglia e
alcun valore di progetto: è il manuale del metodo, non un modello.

## Catena causale — l'ordine non è negoziabile

Milestone → attività → risorse → costi → timing → **fabbisogno** → *poi*
richiesta di funding. Lo Stage 10 si ferma al fabbisogno. Invertire l'ordine
— partire dall'importo che si vuole chiedere e costruire i costi che lo
giustificano — è il difetto che l'intera catena esiste per impedire.

Prima delle percentuali vengono i **driver**; prima dell'utile viene la
**cassa**; prima del funding vengono le **milestone**.

## I sei livelli, distinti e non confondibili

1. **Input finanziari governati** — `ASS-*`, `EVD-*`, `SRC-*`, `DEC-*`,
   `MIL-*` e `financial_config`, prodotti dagli Stage 0-9 e dal Transaction
   Manager. Hanno autorità sugli **input**: valore, unità, stato di
   validazione, owner, classe di evidenza.
2. **Calcolo del motore accettato** — il `financial_payload` intermedio,
   prodotto da `validators/validate_financial_engine.py`. Ha autorità su
   **ogni numero calcolato**.
3. **Proiezione di governance non canonica** — `governance_projection`. Ha
   autorità **su nulla**: porta **solo stato e riferimenti**.
4. **Output canonico** — `10_financial-plan/structured-output.json`, prodotto
   dal costruttore canonico. È l'**unica verità pubblicata**, ed è una
   **proiezione** dei livelli 2 e 3, mai un ricalcolo.
5. **Resa Markdown** — il capitolo. Autorità **su nulla**: seleziona, formatta
   e interpreta in prosa.
6. **Resa workbook** — il modello. Autorità **su nulla**: seleziona, formatta
   e aggrega con formule di presentazione.

Il grafo di derivazione è **chiuso**: ogni numero del canonico esiste nel
payload del motore, allo stesso path logico e con lo stesso valore
serializzato; ogni numero del capitolo e ogni valore ufficiale del workbook
esistono nel canonico. Nient'altro entra.

## I nove divieti normativi

- **D-01** — nessun **ricalcolo finanziario indipendente** nella generazione
  dell'output canonico. Non è una regola di stile: il costruttore è una
  funzione di proiezione totale, e il divieto è misurato da una scansione
  statica che vieta al suo sorgente ogni operatore aritmetico e ogni import del
  motore.
- **D-02** — nessun ricalcolo di policy indipendente nel Markdown.
- **D-03** — nessun ricalcolo di policy indipendente nel workbook.
- **D-04** — nessuna **verità numerica finanziaria** dentro strutture di sola
  governance. La sezione `financial_plan.governance` non dichiara alcun tipo
  numerico a nessuna profondità, e un caso negativo comportamentale ne
  verifica il rifiuto sul validator di produzione.
- **D-05** — nessun **valore copiato non tracciabile**: ogni numero porta
  path canonico, scenario, periodo o regola di aggregazione dichiarata, unità
  e checksum.
- **D-06** — nessuna **politica di formula non dichiarata**.
- **D-07** — nessuna **costante silenziosa** dove sono attesi valori derivati
  dal motore.
- **D-08** — nessuna **assunzione silenziosa**: un caveat non è mai
  riassorbito in un esito più pulito del vero.
- **D-09** — nessun **cambiamento di presentazione che alteri la semantica**.

## Tassonomia di validazione

`validation.result` assume `PASS`, `WARNING` o `FAIL`. Gli esiti del calcolo
canonico usano l'enumerazione chiusa `PASS`, `UNRESOLVED_INPUT`, `WARNING`,
`FAIL`, `NOT_APPLICABLE`: `STRUCTURE_PRESENT` e `RUNTIME_REQUIRED` sono
strutturalmente esclusi dal canonico, perché lì tutto è calcolato e la loro
presenza significherebbe che il motore non ha calcolato ciò che dichiarava.

La presenza di una formula non è **mai** sufficiente per un `PASS`.

### Le tre prontezze restano distinte

- **computazionale** — `validation.result` più
  `calculation_metadata.output_checksums.base`: dice che l'aritmetica chiude;
- **di completamento** — `driver_registry.unbound_required_roles == []`,
  nessun modulo `NOT_APPLICABLE` privo di motivazione, copertura di scenario
  diversa da `none`: dice che il perimetro è completo;
- **investor-ready** — `validation.investor_readiness`: dice se il piano è
  presentabile a un terzo.

Collassarle è il difetto. La regola di prontezza è **congiuntiva e
conservativa**: `ready` se e solo se `result == PASS`, `propagated_status ==
confirmed`, nessun ruolo richiesto non legato, copertura di scenario diversa
da `none`, nessuna riconciliazione con severità `FAIL` e stato `FAIL`, e
`governance.plan.propagated_status == confirmed`. Altrimenti `not_ready`, con
`blocking_reasons[]` **tipizzate e attribuite**, mai prosa. La regola non può
produrre un falso `ready`: può solo bloccare più del dovuto, che è la
direzione fail-closed.

## Governance delle assunzioni

Lo stato di un driver è prodotto da una mappatura **totale e fail-closed** e
vive nell'enumerazione chiusa `unresolved < placeholder < inferred <
confirmed`. Nessuna formula, nessun default, nessun arrotondamento, nessuna
aggregazione e nessuna scelta di scenario può **promuovere** un `placeholder`
o un `unresolved`.

Lo **stato propagato** è il **minimo** degli stati degli input **dichiarati e
consumati**, richiesti **e** opzionali: l'asse richiesto/opzionale non è
l'asse della propagazione.

Le classi di evidenza sono quelle canoniche e non se ne coniano altre:
`verified_fact`, `internal_evidence`, `external_source`, `founder_assumption`,
`model_estimate`, `missing_information`. Nessuna assunzione è trasformata in
fatto in silenzio.

La **materialità** è **portata, non fissata**: `driver_entry.materiality` è un
portatore opzionale con dominio `low | medium | high`; **nessuna soglia
numerica** è fissata, dedotta o inferita, e `materiality_basis` dichiara su
che cosa il giudizio è stato espresso. Dove il campo è **assente** la resa è
«non dichiarata»: mai «bassa», mai vuota, mai dedotta. Nessun percorso usa la
materialità per decidere la prontezza.

## Politica di timing

La politica dichiarata è il **clipping ancorato allo `start`**: a muoversi è
lo **start** della finestra, l'**end** dichiarato resta quello del binding, e
la **durata** cambia di conseguenza. Uno start ritardato oltre l'end produce
una **finestra vuota**, che non è mai pubblicata in silenzio: porta un warning
`timing_window_empty` **attribuito** con tre token tipizzati — driver, modulo
consumatore e scenario. Un estremo fuori orizzonte rende la terna
inutilizzabile e il driver **non** coperto, nominato uno per uno.

## Incoerenze

Un'incoerenza fra due fonti governate si dichiara nel formato
`INCOERENZA RILEVATA`. Non si media fra i valori, non si sceglie il più
recente e non si tratta come refuso: si nomina la divergenza, si nominano le
due fonti e si richiede una decisione.
