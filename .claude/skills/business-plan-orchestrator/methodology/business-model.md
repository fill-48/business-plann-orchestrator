# Metodologia — Business model (Stage 5)

> Caricare **solo** quando si lavora su `05_business-model/` (workflow
> `06_business-model.md`). Fonte:
> [`reference/architecture.md`](../reference/architecture.md) §10.
> Enforcement: `validate_unit_economics` +
> `validate_cross_stage_consistency`. **Niente proiezioni finanziarie**:
> qui si fissano i driver, il financial plan è lo Stage 10.

## Prezzo (un solo ASS-, mai due valori)

- Il **prezzo netto** vive una sola volta come `ASS-`/`P-ASS-` di
  categoria pricing (`pricing_ref`), unità `EUR/count` (per cliente/unità
  venduta), **strettamente positivo**.
- Composizione esplicita: listino, sconti medi, resi — ciò che resta è il
  prezzo netto. Se il prezzo è emerso a Stage 3–4, si **referenzia**
  l'`ASS-*` esistente; un valore diverso è un'`INCOERENZA RILEVATA`
  (protocollo SKILL.md), mai una media o un aggiornamento silenzioso.
- Il campo `price` eventualmente duplicato nello structured-output deve
  coincidere con l'ASS-pricing (`price_conflict` altrimenti — T-PRICE).

## Ricavo come formula di driver (mai un numero a mano)

`revenue_ref` è un derivato con `derivation.variables` esplicite:

```text
revenue_y1 = units_y1 * price_net        (count × EUR/count = EUR)
```

I driver (volumi, frequenza d'acquisto, ricorrenza) sono a loro volta
`ASS-` classificati (`founder_assumption`/`model_estimate`). La
**ricorrenza** (one-off, abbonamento mensile/annuale, transazionale) è la
meccanica di monetizzazione: senza meccanica non c'è modello di ricavo.

## Unit economics: contribution margin calcolato

```text
contribution_margin_unit = price_net − Σ(costi variabili unitari)
```

- `contribution_margin_ref` è un derivato con il **pricing tra le
  `variables`** (`margin_missing_price` altrimenti); i costi variabili
  unitari (COGS, supporto, transazione, canale) sono `ASS-` distinti.
- Il validator **ricalcola** il margine dalla DSL: un margine "a parole"
  o un numero scritto a mano è `margin_not_derived`/`value_mismatch`.
- Un margine **negativo** ma aritmeticamente coerente non è un errore di
  calcolo: è un warning `negative_margin` — un rosso metodologico che va
  motivato al gate (quando e come il margine diventa positivo).
- Il **CAC non si fissa qui**: è dovuto a Stage 6 col funnel dietro
  (`not_yet_required` a Stage 5). Qui si prepara il margine che il CAC
  dovrà ripagare (LTV/CAC arriverà con churn e ricorrenza).

## Canale e coerenza a valle

Il canale di vendita dichiarato qui vincola lo Stage 6: prezzi e margini
devono reggere i costi di acquisizione del canale scelto. Il funnel dello
Stage 6 referenzia lo **stesso** `ASS-` di prezzo (`price_divergence`
altrimenti).

## Contratto dell'output strutturato (Stage 5)

```json
{
  "business_model": {
    "pricing_ref": "P-ASS-001",
    "price": 100,
    "revenue_ref": "P-ASS-006",
    "contribution_margin_ref": "P-ASS-004",
    "recurrence": "annual",
    "channel": "direct"
  }
}
```

## Criteri di completezza (gate dello stage)

1. Prezzo = un solo `ASS-` positivo con composizione esplicita.
2. Ricavo = formula di driver ricalcolabile (mai un numero nudo).
3. Contribution margin calcolato, col pricing tra le variables.
4. Ricorrenza e canale espliciti.
5. Nessuna proiezione pluriennale (driver come assunzioni; il financial plan
   è lo Stage 10).

## Failure mode tipici

- Margine "a parole" ("circa il 60%") senza formula → `margin_not_derived`.
- Prezzo diverso tra structured-output e registro → `price_conflict`
  (conflitto, nessuna scrittura).
- Monetizzazione dichiarata senza meccanica (chi paga, quando, quanto).
- Prezzo che non regge i costi del canale scelto: emergerà a Stage 6 —
  non "aggiustare" il margine per anticiparlo senza evidenza.
