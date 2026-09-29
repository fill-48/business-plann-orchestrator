# Workflow 09 — Team e governance (Stage 8, `08_team-and-governance/`)

> Numerazione dei file: **Stage 8** → cartella `08_team-and-governance/` → questo
> workflow (`09_team-and-governance.md`). Metodologia on-demand:
> [`methodology/team-and-governance.md`](../methodology/team-and-governance.md) +
> [`methodology/evidence-framework.md`](../methodology/evidence-framework.md).
> Subagent: [`runtime-agents/team-governance-analyst.md`](../runtime-agents/team-governance-analyst.md).
>
> Da questo stage è attivo `validate_team_and_governance` (egress solo allo
> Stage 8; a 9 gira in impact), oltre a `validate_stage_gate`,
> `validate_referential_integrity`, `validate_cross_stage_consistency`
> (stage 5–9) e `validate_operations_feasibility` (in impact) — matrice di
> enforcement in `config/enforcement-config.json`.
> Qui l'organizzazione deve **coprire i processi core** dello Stage 7 e
> **referenziare** i driver di costo esistenti: non li ridefinisce.
>
> Invarianti transazionali, semantica degli exit code e regole di conflitto:
> identiche a `02_problem-and-need.md` → «Invarianti transazionali». Qui non
> si ripetono. **Nessuna scrittura canonica
> manuale**: l'unico scrittore è `transaction/transaction_manager.py`; le
> assunzioni e le condizioni si aggiornano solo con i comandi del
> transaction manager (`update-assumption`, `resolve-condition`), mai a mano.
> **Nessuna anticipazione dello Stage 9** (roadmap e milestone): le milestone
> (`MIL-`) non esistono ancora e referenziarle qui è un `future_namespace_ref`.
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
  --project "<project>" --stage 08_team-and-governance --phase ingress
```

Lo Stage 7 deve essere `approved*` e in `completed_stages`; nessuna `COND-`
open dovuta (altrimenti exit 1 `condition_due`); nessun conflitto pendente.
Poi apri lo stage (unica scrittura ammessa, via governance):

```bash
python "<skill_dir>/transaction/transaction_manager.py" governance-status \
  --project "<project>" \
  --updates '{"status": "in_progress", "current_task": "stage-8-team-and-governance"}' \
  --reason "ingress Stage 8 autorizzato dai validator"
```

## Passo 2 — Metodologia on-demand

Leggi `methodology/team-and-governance.md` ora. I processi core (`OPS-`), la
capacità operativa e i requisiti normativi sono già canonici (Stage 7):
l'organizzazione li **copre**, non li riscrive. FTE e costi headcount sono
`ASS-`/`P-ASS-` come **driver**, mai proiezioni finanziarie.

## Passo 3 — Subagent nel candidate workspace

Genera un transaction id (`<tx>`) e lancia `team-governance-analyst` a runtime
(contratto di [`reference/architecture.md`](../reference/architecture.md)
§11.2), unico percorso scrivibile:

```text
<project>/08_team-and-governance/.working/<tx>/
```

Output attesi: `structured-output.json` (`team_governance` con `roles[]`
(`ROLE-`, `person` **o** `open_position`, `responsibilities[]`,
`covers_processes[]` → gli `OPS-` con `entity_type: core_process` dello
Stage 7, `fte_ref` → `ASS-`/`P-ASS-`), `capability_gaps[]` (`gap`,
`addressed_by` → un **meccanismo** risolvibile, vedi «Come si indirizza un
gap»), `hiring_plan[]`
(`role_ref`, `period`, `cost_driver_ref`), `decision_rights[]` (`area`,
**un solo** `owner_ref`, eventuali `consulted_refs`), `governance`
(`structure`, `equity_split` con quote in `[0,1]` e somma ≤ 1, `vesting`,
`incentives`), `advisors[]`, `risk_refs[]` → `RISK-`),
`proposed-assumptions.json` (FTE e driver di costo headcount come `P-ASS-*`,
con `derivation.variables` esplicite per i derivati),
`proposed-conditions.json` se restano gap aperti, `research.md`,
`analysis.md`, `section-draft.md`, `handoff.md`.

## Passo 4 — Validazione candidate

```bash
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/08_team-and-governance/.working/<tx>" \
  --stage 08_team-and-governance --phase candidate
```

`refint` raccoglie le definizioni `ROLE-` (che vivono solo qui), risolve
`covers_processes[]` verso i soli `OPS-` di tipo `core_process`
(`covers_non_process` altrimenti), `owner_ref`/`role_ref` verso `ROLE-`
esistenti, gli `ASS-`/`P-ASS-`, e vieta i riferimenti a namespace di stage
futuri (`future_namespace_ref`, es. `MIL-`).

## Passo 5 — QA di stage e criteri di completezza

`stage-qa.md` nel candidate, criteri:

1. ogni processo core dello Stage 7 coperto da almeno un `ROLE-`;
2. ogni ruolo con `person` **o** `open_position`, responsabilità verificabili
   e `fte_ref`, con unità FTE omogenee fra i ruoli;
3. ogni `capability_gap` con `addressed_by` reale (hiring, advisor o `COND-`
   esistente);
4. ogni posizione aperta con una riga di `hiring_plan` e `cost_driver_ref`;
5. ogni area di `decision_rights` con **esattamente un** owner;
6. `equity_split` con quote in `[0,1]` e somma ≤ 1; incentivi coerenti;
7. ogni rischio organizzativo referenziato a un `RISK-` del risk-register.

## Passo 6 — Egress e applicazione transazionale

Tutti i validator applicabili allo Stage 8 (matrice di enforcement in
`config/enforcement-config.json`):

```bash
python "<skill_dir>/validators/validate_stage_gate.py" \
  --project "<project>" --candidate "<project>/08_team-and-governance/.working/<tx>" \
  --stage 08_team-and-governance --phase egress
python "<skill_dir>/validators/validate_referential_integrity.py" \
  --project "<project>" --candidate "<project>/08_team-and-governance/.working/<tx>" \
  --stage 08_team-and-governance --phase egress
python "<skill_dir>/validators/validate_cross_stage_consistency.py" \
  --project "<project>" --candidate "<project>/08_team-and-governance/.working/<tx>" \
  --stage 08_team-and-governance --phase egress
python "<skill_dir>/validators/validate_team_and_governance.py" \
  --project "<project>" --candidate "<project>/08_team-and-governance/.working/<tx>" \
  --stage 08_team-and-governance --phase egress
```

Codici tipici di `validate_team_and_governance`: **`core_process_unowned`**
(processo core dello Stage 7 senza alcun ruolo), **`capability_gap_unaddressed`**
(gap senza piano, o indirizzato a una `COND-` inesistente),
**`decision_right_ambiguous`** (zero o due owner sulla stessa area),
**`equity_sum_exceeds_one`**, `fte_not_ref` (driver letterale o non
risolvibile), `value_mismatch` (driver derivato che non torna al ricalcolo),
`unit_mismatch` (unità FTE disomogenee), `unresolved_ref` (`RISK-`),
`missing_required`. Warning: `key_person_dependency` e
**`open_position_unbudgeted`**, quest'ultimo **error** quando lo stage può
chiudere solo `approved` pieno (nessuna `COND-` canonica aperta e nessun
`proposed-conditions.json` nel candidate). Exit 1 → correggi il candidate e
ripeti.

### Come si indirizza un gap (`addressed_by`)

`addressed_by` porta il **meccanismo**, non la spiegazione: la prosa va in
`notes`. Il validator lo risolve per token, senza inferenza semantica, e
ammette tre forme:

| Meccanismo | Forma | Risolve se |
|---|---|---|
| Condizione | `COND-012`, `apre COND-012` | la `COND-` esiste nel `conditions-register` canonico **o** è proposta in `proposed-conditions.json` |
| Assunzione | `ROLE-004`, `hire ROLE-004` | il `ROLE-` ha `open_position` **e** una riga di `hiring_plan` intestata a quel ruolo **e** quella riga ha `cost_driver_ref` verso un `ASS-`/`P-ASS-` |
| Advisor | `Studio Legale Esempio`, `advisor: Studio Legale Esempio` | il nome coincide con un `advisors[].name` dopo trim, collasso degli spazi e case-fold (nessun fuzzy matching) |

**Ogni** id citato deve risolvere: un id fantasma accanto a uno buono resta
una promessa, non un piano. Una stringa priva di id vale solo come nome di
advisor — quindi `will hire someone later`, `advisor to be identified`,
`future CTO` o `external support` **non indirizzano nulla** e restano
`capability_gap_unaddressed`. Se il meccanismo non esiste ancora, la via è
una `COND-`, non una frase.

### Gap non indirizzati e gate

Un gate `approved` pieno con capability gap non indirizzati è **vietato**.
Le due sole vie sono:

1. **chiudere il gap nel candidate**: hiring pianificato con
   `cost_driver_ref`, advisor con incarico reale, oppure copertura del
   processo con un ruolo esistente;
2. **aprire una `COND-`** in `proposed-conditions.json` (con
   `validation_action`, `owner`, `due_before_stage`) e avanzare con
   `--gate-result approved_with_conditions`.

Le `COND-` così create si chiudono **solo** con
`transaction_manager.py resolve-condition`, mai a mano.

### Tensioni con lo Stage 7 e ciclo di capacità operativa

Se emerge che la capacità operativa canonica presuppone persone che non
esistono e non sono pianificate, **non** riscrivere lo Stage 7: apri il
conflitto sull'`ASS-` interessato (capacità o FTE), porta lo stato a
`conflict_awaiting_confirmation` via `governance-status`, attendi la conferma
esplicita dell'utente in un **turno successivo**, poi applica la modifica con
`show-assumption` (per l'`expected_record_hash`) e `update-assumption`
(`--changes` con `operation_id` e `decision`). Il comando esegue CAS,
`previous_values`, allocazione `DEC-*`, riga nel decision-log e la matrice
impact **prima** del commit; se la catena resta rotta →
`impact_validation_failed` e canonico byte-identico.

Tutti exit 0 → applica e avanza:

```bash
python "<skill_dir>/transaction/transaction_manager.py" advance-stage \
  --project "<project>" --stage 08_team-and-governance \
  --candidate "<project>/08_team-and-governance/.working/<tx>" \
  --gate-result approved
```

Il founder conferma esplicitamente: assegnazione dei ruoli, gap dichiarati,
equity e incentivi. Gate `approved*` solo dopo conferma; con gap aperti il
massimo è `approved_with_conditions`.

## Passo 7 — Verifica post-commit e handoff

Dopo `"result": "applied"`: `current_stage` = `09_roadmap-and-milestones`,
`completed_stages` include `08_team-and-governance`.
`handoff.md`: ruoli e owner dei processi core, gap aperti, driver di hiring,
`COND-` create, next stage. Azione successiva:
`workflows/10_roadmap-and-milestones.md` (Stage 9).

## Resume

Come per gli stage precedenti (`recover` → catena → `next_action`). Dopo
qualunque modifica canonica confermata su FTE, costi headcount, capacità o
volumi, la matrice `--phase impact` sugli Stage 4–8 è rieseguita dal comando
`update-assumption` prima del commit.
