# Workflow 10 — Roadmap e milestone (Stage 9, `09_roadmap-and-milestones/`)

> Numerazione dei file: **Stage 9** → cartella `09_roadmap-and-milestones/` → questo
> workflow (`10_roadmap-and-milestones.md`). Metodologia on-demand:
> [`methodology/roadmap-and-milestones.md`](../methodology/roadmap-and-milestones.md) +
> [`methodology/evidence-framework.md`](../methodology/evidence-framework.md).
> Subagent: [`runtime-agents/milestone-planner.md`](../runtime-agents/milestone-planner.md).
>
> Da questo stage è attivo `validate_milestone_chain` (egress solo allo
> Stage 9), oltre a `validate_stage_gate`, `validate_referential_integrity`,
> `validate_cross_stage_consistency` (stage 5–9), `validate_operations_feasibility`
> e `validate_team_and_governance` (entrambi pass-through in egress qui, attivi
> in impact) — matrice di enforcement in `config/enforcement-config.json`.
> Qui la roadmap deve **rendere eseguibile** ciò che gli Stage 6–8 hanno
> dichiarato: ogni milestone ha un owner reale, un costo referenziato, un
> criterio misurabile e una regola go/no-go.
>
> Invarianti transazionali, semantica degli exit code e regole di conflitto:
> identiche a `02_problem-and-need.md` → «Invarianti transazionali». Qui non
> si ripetono. **Nessuna scrittura canonica manuale**: l'unico scrittore è
> `transaction/transaction_manager.py`; le assunzioni e le condizioni si
> aggiornano solo con i comandi del transaction manager (`update-assumption`,
> `resolve-condition`), mai a mano.
>
> **Contratto `financial_plan_inputs`.** È un contratto di **sole
> referenze** verso lo Stage 10: nessun calcolo, nessuna proiezione, nessun
> conto economico. Questo stage non contiene
> **nessuna implementazione dello Stage 10**: il piano finanziario è
> costruito dallo Stage 10 con il proprio workflow
> (`11_financial-plan.md`), e la roadmap non crea `10_financial-plan/` né
> alcun suo artefatto. Vale comunque il **release boundary** dichiarato in
> `config/enforcement-config.json` (`13_document-generation`, l'ultimo stage
> di `stage_order`): uno stage oltre il confine è respinto dal transaction
> manager con `stage_not_implemented` (exit 1), e nessuno stage del piano lo
> supera.
>
> `<skill_dir>` = directory che contiene `SKILL.md` (normalmente
> `~/.claude/skills/business-plan-orchestrator`); `<project>` = cartella del
> progetto nella working directory dell'utente.

## Passo 0 — Recovery preventivo

```bash
python "<skill_dir>/transaction/transaction_manager.py" recover --project "<project>"
```

## Passo 1 — Ingress gate

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --stage 09_roadmap-and-milestones --phase ingress
```

Lo Stage 8 deve essere `approved*` e in `completed_stages`; nessuna `COND-`
open dovuta (altrimenti exit 1 `condition_due`); nessun conflitto pendente.
Poi apri lo stage (unica scrittura ammessa, via governance):

```bash
python "<skill_dir>/transaction/transaction_manager.py" governance-status \
  --project "<project>" \
  --updates '{"status": "in_progress", "current_task": "stage-9-roadmap-and-milestones"}' \
  --reason "ingress Stage 9 autorizzato dai validator"
```

## Passo 2 — Metodologia on-demand

Leggi `methodology/roadmap-and-milestones.md` ora. I `ROLE-` (Stage 8), i
processi core e la capacità operativa (Stage 7), i volumi e il funnel
(Stage 6) sono già canonici: la roadmap li **sequenzia**, non li riscrive.
I costi delle milestone sono `ASS-`/`P-ASS-` come **driver**, mai proiezioni
finanziarie.

## Passo 3 — Subagent nel candidate workspace

Genera un transaction id (`<tx>`) e lancia `milestone-planner` a runtime
(contratto di [`reference/architecture.md`](../reference/architecture.md)
§11.2), unico percorso scrivibile:

```text
<project>/09_roadmap-and-milestones/.working/<tx>/
```

Output attesi: `structured-output.json` (`milestone_plan` con `milestones[]`
(`MIL-`, `title`, `category` ∈ {technical, commercial, operational,
organizational}, `owner_ref` → un `ROLE-` dello Stage 8, `depends_on[]` →
altre `MIL-`, `start_date`/`target_date` ISO-8601 `YYYY-MM-DD`, `cost_ref` →
`ASS-`/`P-ASS-`, `success_criteria[]` non vuoti e misurabili,
`go_no_go_rule`, `exit_criteria`, `risk_refs[]` → `RISK-`) e
`financial_plan_inputs` (contratto `financial_plan_inputs`: `pricing_ref`,
`cogs_refs[]`,
`funnel_customers_ref`, `churn_ref`, `ops_capacity_ref`,
`headcount_driver_refs[]`, `milestone_cost_refs[]`, `som_ref` — **solo
referenze**)), `proposed-assumptions.json` (costi e driver temporali delle
milestone come `P-ASS-*`), `proposed-conditions.json` se restano condizioni
aperte, `research.md`, `analysis.md`, `section-draft.md`, `handoff.md`.

## Passo 4 — Validazione candidate

```bash
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/09_roadmap-and-milestones/.working/<tx>" \
  --stage 09_roadmap-and-milestones --phase candidate
```

`refint` raccoglie le definizioni `MIL-` (che vivono solo qui), risolve
`owner_ref` verso i `ROLE-` dello Stage 8, `depends_on[]` verso le `MIL-` del
piano — la **forward reference** dentro lo stesso array è legittima, perché la
risoluzione avviene dopo la raccolta completa — e gli `ASS-`/`P-ASS-`.

## Passo 5 — QA di stage e criteri di completezza

`stage-qa.md` nel candidate, criteri:

1. il grafo `depends_on` è un **DAG**: nessun ciclo, nessuna auto-dipendenza,
   nessuna dipendenza verso una `MIL-` inesistente;
2. `target_date ≥ start_date` e `start_date ≥ target_date` di ogni
   dipendenza (confine incluso: partire il giorno stesso in cui chiude il
   prerequisito è ammesso);
3. ogni milestone con `owner_ref` verso un `ROLE-` **esistente** dello
   Stage 8;
4. ogni milestone con `cost_ref` verso un `ASS-`/`P-ASS-` esistente, mai un
   importo scritto in chiaro;
5. ogni milestone con `success_criteria[]` misurabili, `go_no_go_rule` e
   `exit_criteria`;
6. tutte e quattro le categorie valutate con almeno una milestone;
7. `financial_plan_inputs` completo e interamente risolvibile, compresi i
   costi di **tutte** le milestone del piano;
8. ogni rischio referenziato a un `RISK-` del risk-register.

## Passo 6 — Egress e applicazione transazionale

Tutti i validator applicabili allo Stage 9 (matrice di enforcement in
`config/enforcement-config.json`):

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --candidate "<project>/09_roadmap-and-milestones/.working/<tx>" \
  --stage 09_roadmap-and-milestones --phase egress
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/09_roadmap-and-milestones/.working/<tx>" \
  --stage 09_roadmap-and-milestones --phase egress
python "<skill_dir>/validators/validate_cross_stage_consistency.py" \
  --project "<project>" --candidate "<project>/09_roadmap-and-milestones/.working/<tx>" \
  --stage 09_roadmap-and-milestones --phase egress
python "<skill_dir>/validators/validate_milestone_chain.py" \
  --project "<project>" --candidate "<project>/09_roadmap-and-milestones/.working/<tx>" \
  --stage 09_roadmap-and-milestones --phase egress
```

Codici tipici di `validate_milestone_chain`: **`milestone_cycle_detected`**
(dipendenze circolari, auto-dipendenza inclusa),
`milestone_dependency_unresolved` (`depends_on` verso una `MIL-` inesistente),
**`milestone_date_incoherent`** (`target_date` prima di `start_date`, oppure
avvio prima della chiusura di una dipendenza), `invalid` (data non ISO-8601),
**`milestone_owner_unresolved`** (owner assente o non fra i `ROLE-`
canonici), **`milestone_cost_unresolved`** (costo letterale o riferimento non
risolvibile), `milestone_criteria_missing` (criteri, go/no-go o exit
mancanti), `milestone_category_not_assessed` (categoria in bianco, fuori
vocabolario, oppure mai coperta dalla roadmap), **`financial_input_unresolved`**
(interfaccia `financial_plan_inputs` assente, incompleta o non risolvibile),
`missing_required`. Warning: `milestone_target_above_capacity` (segnale del
ciclo di capacità operativa) e `long_gap_between_milestones`. Exit 1 →
correggi il candidate e ripeti.

`validate_cross_stage_consistency` resta attivo e può produrre qui
**`headcount_capacity_incoherent`** (un processo core `make` senza alcun ruolo
con headcount reale), `ops_capacity_below_gtm` e `ops_cost_divergence`: sono
difetti **upstream** e non si correggono riscrivendo la roadmap.

### Tensioni con gli Stage 6–8 e ciclo di capacità operativa

Se la roadmap rivela che un target commerciale non regge la capacità
operativa o il funnel canonici, **non** riscrivere gli stage approvati: apri
il conflitto sull'`ASS-` interessato, porta lo stato a
`conflict_awaiting_confirmation` via `governance-status`, attendi la conferma
esplicita dell'utente in un **turno successivo**, poi applica la modifica con
`show-assumption` (per l'`expected_record_hash`) e `update-assumption`
(`--changes` con `operation_id` e `decision`). Il comando esegue CAS,
`previous_values`, allocazione `DEC-*`, riga nel decision-log e la matrice
impact **prima** del commit; se la catena resta rotta →
`impact_validation_failed` e canonico byte-identico. Le condizioni residue si
chiudono **solo** con `resolve-condition`, mai a mano.

Tutti exit 0 → applica e avanza:

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage \
  --project "<project>" --stage 09_roadmap-and-milestones \
  --candidate "<project>/09_roadmap-and-milestones/.working/<tx>" \
  --gate-result approved
```

Il founder conferma esplicitamente: sequenza delle milestone, owner, costi e
regole go/no-go. La roadmap è **l'impegno che il funding request citerà**:
un'approvazione affrettata qui diventa una promessa non mantenuta davanti a
un investitore. Con condizioni aperte il massimo è
`approved_with_conditions`.

## Passo 7 — Verifica post-commit, handoff e passaggio allo Stage 10

Dopo `"result": "applied"`: `completed_stages` include
`09_roadmap-and-milestones`, `current_stage` diventa `10_financial-plan` con
`status = not_started` e `next_action` — calcolato dal transaction manager
nella stessa transazione — indica di avviarlo. Lo Stage 9 **non** è lo
stadio finale: il business plan prosegue con gli Stage 10–13.

`handoff.md`: milestone e loro sequenza, critical path, owner, costi
referenziati, condizioni aperte, e il contenuto di `financial_plan_inputs`
come consegna verso lo Stage 10.

La roadmap resta un contratto di sole referenze: non creare qui
`10_financial-plan/`, `11_funding-request/` o `12_data-room/`, non produrre
proiezioni finanziarie né richieste di funding: ogni stage successivo segue
il proprio workflow e i propri validator. Azione successiva:
[`workflows/11_financial-plan.md`](11_financial-plan.md) (Stage 10), che
legge `financial_plan_inputs` come ingresso referenziale.

## Resume

Come per gli stage precedenti (`recover` → catena → `next_action`). Dopo
qualunque modifica canonica confermata su volumi, capacità, costi o organico,
la matrice `--phase impact` sugli Stage 4–9 è rieseguita dal comando
`update-assumption` prima del commit — mai oltre il release boundary.
