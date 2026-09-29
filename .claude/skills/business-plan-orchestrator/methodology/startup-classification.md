# Classificazione della startup

> Fonte: [`reference/architecture.md`](../reference/architecture.md) §7. Caricare durante `workflows/01_idea-discovery.md`
> per compilare `shared/startup-profile.json` (schema:
> `schemas/startup-profile.schema.json`).

La classificazione avviene lungo 5 dimensioni indipendenti. Ogni dimensione
modifica dinamicamente il workflow (quali domande condizionali fare, quali
metriche diventano centrali negli stage successivi).

## Le 5 dimensioni

```yaml
startup_type:
  - commercial | saas | marketplace | consumer | foodtech
  - industrial | hardware | deeptech | biotech | medtech
  - service | hybrid

development_stage:
  - idea | concept | mvp | pilot | early_revenue | growth
  - preclinical | clinical | pre_seed | seed

primary_reader:
  - founder_internal | business_angel | venture_capital
  - corporate_partner | bank | public_grant | incubator | mixed

funding_type:
  - equity | debt | grant | bootstrapping | mixed

time_horizon:
  - 12_months | 24_months | 36_months | 5_years | custom
```

## Tipo di startup → metriche/leve dominanti

| startup_type | Metriche/leve dominanti |
|---|---|
| `saas` | MRR, ARR, churn, NRR, CAC, LTV, payback |
| `marketplace` | GMV, take rate, liquidity, equilibrio domanda/offerta, network effects |
| `industrial` / `hardware` | capex, capacità produttiva, supply chain, working capital |
| `foodtech` | shelf life, capacità, compliance, scarti, distribuzione, riordino |
| `biotech` / `medtech` / `deeptech` | IP, PoC, GLP, GMP, regulatory path, burn per milestone, licensing |
| `commercial` / `consumer` / `service` | funnel, conversion, retention, unit economics per cliente |

## Destinatario → enfasi aggiuntiva

| primary_reader | Enfasi aggiuntiva nel piano |
|---|---|
| `bank` | DSCR, piano di ammortamento, garanzie, covenant, scenario downside |
| `public_grant` | eleggibilità, innovatività, impatto, work package, deliverable, TRL |
| `business_angel` / `venture_capital` | traction, team, mercato, upside, exit logic |
| `corporate_partner` | fit strategico, sinergie, exclusivity/licensing |

## Come compilare `startup-profile.json`

1. Deriva `startup_type` e `development_stage` dalle risposte della batteria CORE
   + condizionale in `templates/discovery-questionnaire.md`.
2. Deriva `primary_reader` e `funding_type` esplicitamente (domanda 10 della
   batteria CORE) — non indovinare se l'utente non lo dice.
3. Popola `dominant_metrics` con la riga della tabella sopra corrispondente a
   `startup_type`.
4. Marca `classification_confidence: low` se una qualunque delle 5 dimensioni è
   dedotta anziché dichiarata esplicitamente dall'utente, e registra il gap in
   `open-questions.md`.

La classificazione **non è definitiva alla prima passata**: se emergono
informazioni che la contraddicono più avanti, apri un'issue — non sovrascrivere
silenziosamente `startup-profile.json`.
