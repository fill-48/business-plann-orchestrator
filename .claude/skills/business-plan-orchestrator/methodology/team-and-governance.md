# Metodologia — Team e governance (Stage 8)

> Caricare **solo** quando si lavora su `08_team-and-governance/` (workflow
> `09_team-and-governance.md`). Fonte:
> [`reference/architecture.md`](../reference/architecture.md) §10 (Stage 8).
> Enforcement: `validate_team_and_governance` +
> `validate_referential_integrity` + `validate_cross_stage_consistency`.
>
> La domanda dello stage non è «chi siamo», è **«perché questo team può
> eseguire questo modello di business»**. Una biografia non è una risposta.

## 1. Inventario del team (team inventory)

Parti da chi c'è **davvero oggi**: founder, soci operativi, dipendenti,
collaboratori continuativi, advisor con incarico. Per ciascuno registra il
tempo effettivamente dedicato (FTE), non quello dichiarato con ottimismo, e
la fonte dell'informazione. Competenze ed esperienze riferite dal founder
restano `founder_assumption` finché non c'è un documento: un CV citato non è
un `verified_fact`.

## 2. Architettura dei ruoli (role architecture)

Un **ruolo** è un `ROLE-` e non coincide con una persona: una persona può
ricoprire più ruoli, un ruolo può essere una **posizione aperta**
(`open_position`). Ogni ruolo dichiara `responsibilities[]` verificabili
(«garantisce il tempo di attivazione < 48h», non «segue il prodotto») e
`fte_ref` verso un `ASS-`/`P-ASS-` di FTE. Le unità FTE devono essere
omogenee fra i ruoli, altrimenti il fabbisogno totale non è sommabile
(`unit_mismatch`).

## 3. Matrice competenze × processi (capability matrix)

La matrice non è astratta: le colonne sono i **processi core** dello Stage 7
(`OPS-` con `entity_type: core_process`), le righe sono i ruoli.
`covers_processes[]` è la copertura dichiarata. Regola dura: **ogni processo
core ha almeno un ruolo che lo copre** (`core_process_unowned`). Un processo
`make` senza copertura è un buco di esecuzione, non una svista redazionale.
Attenzione al caso opposto: un solo ruolo che copre quasi tutti i processi
core è una **key person dependency** (warning `key_person_dependency`) —
dichiara backup, deleghe e documentazione del know-how.

## 4. Accountability e decision rights

Responsabilità di esecuzione e **diritto di decisione** sono cose diverse.
Ogni area decisionale (prezzo, prodotto, assunzioni, partnership, spesa oltre
soglia) ha **esattamente un** `owner_ref`: zero owner e due owner sono lo
stesso difetto, l'ambiguità (`decision_right_ambiguous`). I `consulted_refs`
sono consultati, non decisori. Se il founder è owner di ogni area, è un dato
di fatto da dichiarare, non da nascondere: diventa un rischio organizzativo
(`RISK-`) e spesso una `COND-`.

## 5. Founder-role fit

Per ogni founder confronta il ruolo assegnato con l'evidenza disponibile:
esperienza dimostrabile, risultati passati, tempo effettivo. Dove il fit è
debole, la risposta è una delle tre: **delega** (assunzione), **supporto**
(advisor/fractional) o **condizione** (`COND-` con validation_action e
scadenza). Un fit debole silenziato è la causa più frequente di un business
plan che regge sulla carta e non in esecuzione.

## 6. Gap di leadership e funzionali (capability gaps)

Un `capability_gap` si dichiara sempre, anche quando è scomodo. Ciò che il
gate richiede non è l'assenza di gap, ma che **ogni gap abbia una risposta**
verificabile: `addressed_by` = hiring pianificato, advisor con incarico
reale, o una `COND-` esistente.

La distinzione che regge il gate è fra **meccanismo** e **spiegazione**.
`addressed_by` porta il meccanismo in forma risolvibile — l'id della `COND-`,
il `ROLE-` da assumere (che deve avere la sua riga di `hiring_plan` con
`cost_driver_ref`), o il nome esatto di un advisor dichiarato in `advisors[]`
— mentre il perché e il come stanno in `notes`. Il validator risolve, non
interpreta: un gap indirizzato a una `COND-` che non esiste, a un ruolo che
nessuno ha budgetato o a un advisor mai ingaggiato resta scoperto
(`capability_gap_unaddressed`), e lo stesso vale per le formule che sembrano
una risposta senza esserlo («assumeremo qualcuno», «advisor da individuare»,
«supporto esterno»). Il formato esatto è nel workflow
[`workflows/09_team-and-governance.md`](../workflows/09_team-and-governance.md),
sezione «Come si indirizza un gap».

Un gap non indirizzato vieta l'`approved` pieno: al massimo
`approved_with_conditions`. Quando la risposta non esiste ancora, la forma
onesta è una `COND-` con `validation_action`, owner e scadenza — non una
frase che rassicura.

## 7. Build / hire / fractional / advisor / partner

Per ogni gap scegli esplicitamente la modalità di chiusura e motivala:

- **build** (formazione interna): lento, adatto a competenze non critiche;
- **hire** (assunzione): costo pieno, adatto ai processi core `make`;
- **fractional / contractor**: costo variabile, adatto a competenze
  specialistiche discontinue;
- **advisor**: accesso e credibilità, non capacità esecutiva — non copre da
  solo un processo core;
- **partner**: coerente con un processo core dichiarato `partner` allo
  Stage 7, mai con uno dichiarato `make`.

## 8. Tempi e priorità di chiusura (hiring plan)

Il `hiring_plan[]` associa a ogni posizione aperta un `period` e un
`cost_driver_ref` verso un `ASS-`/`P-ASS-`. **Ogni posizione aperta ha un
costo**: senza driver è `open_position_unbudgeted`, che diventa un errore
quando lo stage punta all'`approved` pieno. Priorità per rischio di
esecuzione: prima i ruoli che coprono processi core con collo di bottiglia,
poi quelli che coprono obblighi normativi o IP, poi il resto. I costi restano
**driver**, mai proiezioni: il piano finanziario è lo Stage 10.

## 9. Modello di governance

Dichiara l'assetto (`structure`): forma societaria, organi, soci, patti
parasociali. L'`equity_split[]` usa quote in `[0,1]` che sommano **al massimo
a 1** (`equity_sum_exceeds_one`); la somma esatta a 1 è ammessa. Un pool
opzioni non ancora assegnato si dichiara negli `incentives`, non come quota
di un titolare inesistente.

## 10. Escalation e logica di approvazione

Definisci come una decisione sale: soglie di spesa, conflitti fra owner,
decisioni straordinarie (nuovo socio, cambio di prezzo, cessione IP). Ogni
regola di escalation punta a un `ROLE-` o a un organo dichiarato in
`structure`. Una regola senza destinatario è una regola che non esiste.

## 11. Incentivi e allineamento

Vesting, cliff, bonus e pool opzioni servono ad allineare **orizzonte** e
**rischio**. Verifica la coerenza fra chi decide, chi risponde e chi guadagna:
se un ruolo è accountable su un risultato senza alcuna leva sul risultato,
l'incentivo è disallineato — è un `RISK-`, non un dettaglio contrattuale.

## 12. Qualità delle evidenze

Le sei classi valgono anche qui: un contratto firmato è `verified_fact`, una
lettera d'intenti con un advisor è `internal_evidence`, un benchmark
retributivo è `external_source`, un FTE stimato dal founder è
`founder_assumption`, un costo headcount calcolato è `model_estimate`, un
ruolo non ancora definito è `missing_information`. Nessuna promozione
silenziosa a fatto.

## 13. Assunzioni e condizioni

Gli FTE e i costi headcount vivono nel registro come `ASS-` (categoria
`team`), proposti nel candidate come `P-ASS-`. I gap che non si chiudono
entro lo stage diventano `COND-` con `validation_action`, `owner` e
`due_before_stage`; si chiudono **solo** con
`transaction_manager.py resolve-condition`, mai a mano.

## 14. Collegamento con i requisiti operativi

- Ogni processo core dello Stage 7 ha un owner (§3).
- Un processo `make` è coperto internamente; un processo `partner` può essere
  coperto da un ruolo di gestione del partner, non ignorato.
- I requisiti normativi e gli asset IP dello Stage 7 hanno un ruolo
  responsabile: la compliance senza owner non è compliance.
- Il fabbisogno FTE è coerente con la capacità operativa dichiarata: se la
  capacità presuppone persone che non esistono e non sono pianificate, la
  tensione va dichiarata, non arrotondata.

## 15. Criteri di completezza (gate dello stage)

1. Ogni processo core coperto da almeno un `ROLE-`.
2. Ogni ruolo con persona o posizione aperta, responsabilità e `fte_ref`.
3. Ogni capability gap con una risposta reale.
4. Ogni posizione aperta con un driver di costo.
5. Ogni area decisionale con esattamente un owner.
6. Equity in `[0,1]` con somma ≤ 1; incentivi coerenti con i ruoli.
7. Ogni rischio organizzativo registrato come `RISK-`.

## 16. Failure mode e anti-pattern

- **Organigramma dei sogni**: ruoli che nessuno ricopre e nessuno finanzia →
  `core_process_unowned` / `open_position_unbudgeted`.
- **Founder tuttofare non dichiarato**: un ruolo copre tutto e il piano non
  ne parla → `key_person_dependency` mai mitigata.
- **Gap verniciato**: «lo copriremo con un advisor» senza incarico né `COND-`
  → `capability_gap_unaddressed`.
- **Governance a due teste**: la stessa area decisionale con due owner →
  `decision_right_ambiguous`.
- **Equity oltre il 100%**: quote promesse più volte → `equity_sum_exceeds_one`.
- **Biografia come prova**: esperienze dichiarate promosse a `verified_fact`.
- **Costo headcount riscritto**: un driver duplicato invece che referenziato
  → il dato deve vivere una sola volta.
- **Roadmap anticipata**: milestone e `MIL-` creati qui — è lo Stage 9.
