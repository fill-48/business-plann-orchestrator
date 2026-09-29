# Metodologia — Operations e IP (Stage 7)

> Caricare **solo** quando si lavora su `07_operations-and-ip/` (workflow
> `08_operations-and-ip.md`). Fonte:
> [`reference/architecture.md`](../reference/architecture.md) §10 (Stage 7).
> Enforcement: `validate_operations_feasibility` +
> `validate_cross_stage_consistency`.

## Operating model e processi core (process decomposition)

Scomponi il business nel **processo end-to-end** di produzione/delivery del
valore: dalla richiesta del cliente alla consegna e all'assistenza. Ogni
**processo core** è un `OPS-` (`entity_type: core_process`) con:

- `make_buy_partner`: la scelta esplicita se il processo è svolto
  internamente (`make`), acquistato (`buy`) o affidato a un partner
  (`partner`) — la make/buy/partner analysis è obbligatoria, mai implicita;
- `owner_hint`: chi ne risponde (aggancio al team di Stage 8, senza
  anticiparlo con `ROLE-`);
- `bottleneck`: se è un collo di bottiglia della capacità.

## Capacità operativa e colli di bottiglia (capacity logic)

La **capacità** è quanti clienti/unità il sistema può servire davvero con il
team e le risorse dichiarate — non un desiderio. È un `ASS-` **derived**,
ricalcolabile dalla Formula DSL (es. `installed_capacity * utilization`),
mai un numero a mano (`capacity_not_derived` altrimenti). L'unità dev'essere
**coerente coi volumi GTM**: la capacità deve reggere i `customers_out` dello
Stage 6, altrimenti scatta `ops_capacity_below_gtm` (ciclo di capacità
operativa). Il collo di
bottiglia è il processo che fissa il tetto: dichiaralo e mitigalo.

## Dipendenze critiche (critical dependency mapping)

Mappa i fornitori e le dipendenze che, se saltano, fermano il business. Ogni
dipendenza è un `OPS-` (`entity_type: dependency`) con una `category` e una
**valutazione**: una `mitigation`, oppure `none_identified` + `rationale`.
Una dipendenza **single-source** senza mitigazione è un rischio
di concentrazione (warning `single_source_dependency`): dichiara il piano di
uscita o il secondo fornitore.

## Costi operativi (operating cost drivers)

I costi operativi unitari **vivono una sola volta**: `unit_ops_cost_refs`
referenzia gli `ASS-` COGS dello Stage 5, non li riscrive. Duplicare un costo
con un valore diverso è un conflitto (`ops_cost_divergence`): una variabile,
un solo `ASS-`. I costi come driver restano assunzioni, non un modello
finanziario (il financial plan è lo Stage 10): nessuna proiezione qui.

## Requisiti normativi (regulatory constraints)

Elenca i requisiti regolatori applicabili (licenze, privacy/GDPR,
certificazioni, sicurezza). Ognuno è **valutato** (`assessment`) oppure
dichiarato non applicabile con `none_identified` + `rationale`. Il silenzio
non è una valutazione (`regulatory_not_assessed`).

## Strategia IP e protezione del know-how (IP identification and protection)

Identifica gli **asset IP** — algoritmi, dataset, marchi, know-how — come
`OPS-` (`entity_type: ip_asset`) con una `protection` esplicita
(`patent`/`trademark`/`copyright`/`trade_secret`/`contractual`/`none`) e la
sua `rationale`. La strategia IP dev'essere esplicita: ogni asset core
dichiara come è protetto (`ip_protection_missing` altrimenti). Il know-how
non brevettabile si protegge con segreto, NDA e segregazione degli accessi.

## Rischi operativi ed evidenze (evidence and assumption handling)

Ogni rischio operativo (capacità, fornitori, regolatorio, IP) è un `RISK-`
del risk-register, referenziato da `risk_refs`. Distingui sempre **fatti**,
**assunzioni** (`ASS-`/`P-ASS-`), **ipotesi** (da testare) e **condizioni
aperte** (`COND-`): una capacità stimata è `model_estimate`, non un dato.

## Coerenza con gli stage precedenti

- La capacità regge i volumi GTM (Stage 6) e il SOM (Stage 4).
- I costi operativi referenziano i COGS (Stage 5), senza duplicati.
- Il prezzo resta quello canonico dello Stage 5 (nessuna ridefinizione).

## Criteri di completezza (gate dello stage)

1. Processi core tipizzati, ciascuno con make/buy/partner e owner.
2. Capacità derivata e ricalcolabile, `>= customers_out` del GTM.
3. Ogni dipendenza critica e ogni requisito normativo valutati.
4. Strategia IP esplicita: ogni asset core con protezione.
5. Costi operativi referenziati, senza divergenze.

## Failure mode tipici

- Capacità dichiarata a mano → `capacity_not_derived`.
- Capacità < volumi GTM trattata come refuso → è il ciclo di capacità
  operativa, con storico.
- Costo operativo duplicato con valore diverso → `ops_cost_divergence`.
- Dipendenza o requisito normativo non valutati → `*_not_assessed`.
- Asset IP senza protezione → `ip_protection_missing`.
