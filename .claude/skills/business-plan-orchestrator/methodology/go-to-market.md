# Metodologia — Go-to-market (Stage 6)

> Caricare **solo** quando si lavora su `06_go-to-market/` (workflow
> `07_go-to-market.md`). Fonte:
> [`reference/architecture.md`](../reference/architecture.md) §10.
> Enforcement: `validate_funnel_arithmetic` +
> `validate_cross_stage_consistency`.

## Funnel completo (mai un CAC senza funnel dietro)

Il funnel è la meccanica che trasforma spesa in clienti:

```text
leads → tasso₁ → tasso₂ → … → customers_out
customers_out = leads × Π(tassi)
CAC = sm_spend / customers_out          (EUR / count = EUR/count)
```

- Ogni **tasso di conversione** è un `ASS-`/`P-ASS-` con `unit: "ratio"`
  e valore **in [0,1]** (frazione decimale, mai percentuale nuda):
  `rate_out_of_bounds` altrimenti — un funnel non amplifica i lead.
- `customers_out` è un derivato; il validator ricalcola il **prodotto**
  indipendentemente dalla formula dichiarata (`funnel_product_mismatch`).
- Il **CAC** è coerente con `spend / customers_out` (`cac_mismatch`) e ha
  unità `EUR/count`: un CAC dichiarato senza funnel dietro non passa.
- I tassi vengono da evidenze classificate (benchmark di canale =
  `external_source`; ipotesi = `founder_assumption` destinata al test).

## Churn esplicito (mai ignorato)

`churn_ref` è **dovuto** a Stage 6 (`missing_required` se assente):
ratio in [0,1] per il periodo dichiarato. Ignorare il churn falsa
retention e LTV; il confronto LTV/CAC usa il contribution margin dello
Stage 5 e la ricorrenza — con churn alto il CAC va ripagato prima.

## Canali e capacità reale

- Per ogni canale: costo, tasso atteso, **capacità** (quanti clienti/anno
  può davvero produrre con il team e il budget dichiarati — capacità
  commerciale reale, non desiderio).
- `capacity_revenue_ref` = clienti sostenibili × valore annuo per cliente
  (EUR): è il numero che regge — o no — il SOM dello Stage 4.

## Tensione SOM ↔ capacità GTM (ciclo di conflitto)

`validate_cross_stage_consistency` confronta la capacità GTM col SOM
canonico: `capacity < SOM` → **`gtm_capacity_below_som`**. Da lì il ciclo
è formalizzato: BLOCK dello Stage 6 → conflitto esplicito sull'`ASS-*`
del SOM (`INCOERENZA RILEVATA`, `conflict_awaiting_confirmation`) →
conferma utente in un turno successivo → update con `previous_values` +
`DEC-` (anche dei driver del SOM) → `--phase impact` sugli Stage 4–6 →
resubmit del gate. **Mai** riscrivere lo Stage 4 in silenzio, mai mediare.

## Prezzo unico cross-stage

Il funnel referenzia lo **stesso** `ASS-` di prezzo del business model
(`pricing_ref` identico): `price_divergence` altrimenti. Una variabile,
un solo `ASS-`.

## Contratto dell'output strutturato (Stage 6)

```json
{
  "sales_funnel": {
    "leads_ref": "P-ASS-001",
    "stages": [
      { "name": "mql_to_sql", "rate_ref": "P-ASS-002" },
      { "name": "sql_to_win", "rate_ref": "P-ASS-003" }
    ],
    "customers_out_ref": "P-ASS-004",
    "spend_ref": "P-ASS-005",
    "cac_ref": "P-ASS-006",
    "churn_ref": "P-ASS-007",
    "capacity_revenue_ref": "P-ASS-008",
    "pricing_ref": "ASS-012"
  }
}
```

## Criteri di completezza (gate dello stage)

1. Funnel completo e ricalcolabile che **alimenta** le unit economics
   dello Stage 5.
2. CAC = spend / customers_out, con funnel dietro.
3. Churn esplicito.
4. Capacità canali ≥ SOM, oppure ciclo di conflitto aperto (mai ignorato).
5. Stesso prezzo canonico dello Stage 5.

## Failure mode tipici

- CAC dichiarato senza meccanica → `cac_mismatch` o funnel assente.
- Tasso al 25 invece di 0.25 → `rate_out_of_bounds` (percentuali come
  frazione).
- Churn ignorato → `missing_required`.
- Capacità < SOM trattata come refuso → è un conflitto da gestire con il
  ciclo di conflitto, con storico.
