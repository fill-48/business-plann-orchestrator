# Workflow — Stage 10 `10_financial-plan`

> **Numerazione dei file.** Il workflow `NN_…` serve lo stage `NN-1`: questo
> file, `11_financial-plan.md`, è il workflow dello **Stage 10**
> (`10_financial-plan`), non dello Stage 11. Metodologia on-demand:
> [`methodology/financial-plan.md`](../methodology/financial-plan.md).
> Subagent: [`runtime-agents/financial-modeller.md`](../runtime-agents/financial-modeller.md).

> **Posizione nella catena.** Lo Stage 10 segue lo Stage 9
> `09_roadmap-and-milestones` e precede lo Stage 11 `11_funding-request`.
> Il `release_boundary` dichiarato in `config/enforcement-config.json` è
> `13_document-generation`, l'ultimo stage di `stage_order`: lo Stage 10 è
> dentro il confine ed è pienamente operativo. Il rifiuto
> `stage_not_implemented` (exit 1, **prima** di lock, journal e qualunque
> I/O) resta la risposta del transaction manager a uno stage oltre il release
> boundary, e nessuno stage del piano lo supera. Questo stage non produce
> alcun artefatto, chiave o comportamento degli Stage 11 e 12.

## Divieto fondamentale — nessuna scrittura canonica diretta

**Nessuna scrittura canonica diretta.** Nessun passo di questo workflow scrive
un artefatto canonico di progetto. Lo scrittore canonico è
`transaction/transaction_manager.py`, e nessun altro. Il costruttore
`output/build_canonical_output.py` scrive **esclusivamente** dentro
`<project>/10_financial-plan/.working/<tx>/`, che è il **candidate**, non il
canonico. `resolve_output_target()` di `validators/validate_financial_engine.py`
**non è rilassata**: il motore continua a non scrivere alcun path di progetto.

## I dieci passi della sequenza di runtime

1. **PREFLIGHT** — `release_boundary >= 10_financial-plan`; `current_stage`
   coerente; `09_roadmap-and-milestones` in `completed_stages`;
   `validate_canonical_state`; ogni `COND-*` con `due_before_stage <= 10`
   chiusa; lock acquisito. Fuori dal release boundary il passo respinge con
   `stage_not_implemented`.
2. **BINDING** — `validators/validate_financial_binding.py`, fase `egress`.
   Risolve i `DRV-*` sugli input governati e produce `driver_bindings[]`.
3. **MOTORE** — `validators/validate_financial_engine.py`, fase `egress`.
   È l'**unica** autorità su ogni numero calcolato.
4. **SCENARI e RICONCILIAZIONI** — inclusi nel passo 3. Tre motori
   indipendenti, non tre etichette; `REC-*` riportate sempre, anche quando
   passano.
5. **COSTRUZIONE** — `output/build_canonical_output.py` proietta il payload
   intermedio sul documento canonico `structured-output.json` e sul
   `handoff.md`, dentro `.working/<tx>/`. Non ricalcola nulla.
6. **VALIDAZIONE** — `validators/validate_financial_output.py`, fase `egress`.
   Valida schema, profilo attivo, governance, prontezza e grammatica dei
   warning. La voce è dichiarata in `config/enforcement-config.json` ed è in
   `egress_required`: il transaction manager la riesegue sullo snapshot del
   candidate prima del commit.
7. **RENDERING MD** — `output/render_financial_plan.py`.
8. **EXPORT XLSX** — `output/export_financial_model.py`.
9. **COERENZA DEI DERIVATI** — `output/derived_consistency.py`,
   riconciliazioni cross-artefatto `XREC-02`…`XREC-06`.
10. **MANIFEST** — aggiornato **solo dopo** che tutti i gate sono passati.

I passi 1, 6 e 10 appartengono al protocollo transazionale comune a tutti gli
stage e sono eseguiti dal transaction manager: il preflight e la validazione
di egress girano durante `advance-stage`, il manifest si aggiorna solo a gate
superati. Gli altri passi sono i moduli propri dello Stage 10.

## I tre gate, mai confusi

- **gate 1 — transazione canonica.** Verifica che il candidate sia valido, che
  i validator di `egress` siano verdi e che il write-set sia verificato. Un
  fallimento produce **nessuna scrittura canonica** e lascia il candidate
  intatto. Si valuta **prima** del commit.
- **gate 2 — completezza dei derivati.** Verifica che i due derivati
  obbligatori esistano, siano completi, freschi e numericamente coerenti col
  canonico. Un fallimento rende lo **Stage 10 non completo**; il canonico
  committato **resta valido e intatto** e non è oggetto di rollback. Si valuta
  **dopo** il commit.
- **gate 3 — revisione umana.** Il founder rivede il capitolo
  `financial-plan.md` e il workbook `financial-model.xlsx` e conferma
  esplicitamente il piano finanziario. Nessun validator sostituisce questa
  revisione: un piano che il founder non ha rivisto non va presentato come
  accettato.

Nessuno stato canonico parziale è mai presentato come completo: il documento
canonico è scritto **per intero e atomicamente** oppure non è scritto.

## Politica di timing — dichiarata, non dedotta

La politica selezionata è il **clipping ancorato allo `start`**.

1. a muoversi è lo **start** della finestra; l'**end dichiarato** resta quello
   del binding;
2. la **durata** cambia di conseguenza: uno start ritardato **accorcia** la
   finestra, uno anticipato la **allunga**. Questo è il clipping, ed è
   dichiarato;
3. su `timing_rule` **puntuale** — `one_off`, `milestone_start`,
   `milestone_end` — start ed end si muovono insieme e la distinzione fra
   traslazione e clipping non esiste;
4. un estremo `< 0` rende la terna **inutilizzabile**: il driver **non** è
   coperto ed è **nominato** in `results.scenarios.coverage.uncovered_driver_refs`;
5. un estremo `>= horizon_periods` ha lo **stesso** esito del punto 4;
6. `start > end` con **entrambi** gli estremi in orizzonte produce una
   **finestra vuota**, resa esplicita dal solo obbligo del **warning
   attribuito** `timing_window_empty`;
7. l'output canonico **non pubblica mai in silenzio** una finestra svuotata.

La **traslazione a durata conservata non è ammessa**: sotto di essa i tre
scenari della fixture `F-1` produrrebbero `10/10/10` periodi contro `10/8/12`,
cancellando la differenza di durata fra scenari che il clipping deve
esprimere.

Il warning ha **una sola** forma ammessa: codice `timing_window_empty`,
severità **WARNING portata dall'appartenenza** a
`financial_plan.validation.warnings[]` — nessun campo `severity` esiste e
nessuno è aggiunto — `message` in prosa **descrittiva** che **non** porta
attribuzione, e `affected_refs[]` con **esattamente tre** token tipizzati: un
`DRV-*`, un `module:<module-id>` e uno `scenario:<scenario-id>`.
Un'attribuzione messa in prosa nel `message` invece che nel token tipizzato è
**respinta**.

## Trattamento della copertura di scenario parziale e nulla

La copertura di scenario è misurata sui **soli driver richiesti dal profilo
attivo** e assume tre livelli:

- **piena** — i tre scenari sono prodotti e portano checksum distinti;
- **parziale** — i driver privi di terna sono **nominati** uno per uno in
  `uncovered_driver_refs`, e lo stato **non** è riassorbibile in un `PASS`;
- **nulla** — Downside e Upside **non** sono prodotti e **non** sono
  etichettati: portano `status: NOT_APPLICABLE` con `not_applicable_reason`
  nominata. L'esito è `approved_with_conditions`, mai un'approvazione piena, e
  la condizione `COND-S10-SCENARIO-COVERAGE` resta **aperta**. Tre serie
  identiche con tre etichette diverse sono un difetto, non una
  semplificazione.

## Che cosa questo stage NON produce

Importo richiesto, strumento selezionato, valutazione, dimensione del round,
ownership, diluizione e termini appartengono allo Stage 11. Lo Stage 10 si
ferma al **fabbisogno**. `use_of_proceeds_candidates` sono **categorie
eleggibili**, mai un'allocazione: nessun importo è associato a una categoria e
la loro somma non è un `ask`.

## Passaggio allo Stage 11

Dopo il commit dell'`advance-stage`, `completed_stages` include
`10_financial-plan`, `current_stage` diventa `11_funding-request` con
`status` `not_started`, e `next_action` — calcolato dal transaction manager
nella stessa transazione — indica di avviarlo. Prima di proseguire servono
anche il gate 2 (derivati completi) e il gate 3 (revisione del founder): lo
Stage 11 legge i tre artefatti dello Stage 10 come unica sorgente numerica e
si ferma con `fr_input_incomplete` se uno solo manca o non è validato.
Azione successiva: [`workflows/12_funding-request.md`](12_funding-request.md)
(Stage 11).
