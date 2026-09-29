# Metodologia — Mercato e concorrenza (Stage 4)

> Caricare **solo** quando si lavora su `04_market-and-competition/`
> (workflow `05_market-and-competition.md`). Fonte:
> [`reference/architecture.md`](../reference/architecture.md) §10.
> Enforcement: `validate_market_arithmetic`.

## Sizing: TAM / SAM / SOM (mai percentuali nude)

| Grandezza | Obbligo metodologico |
|---|---|
| **TAM** | ≥1 stima **top-down o triangolazione indipendente**; con ≥2 metodi, riconciliazione dei metodi di sizing obbligatoria. Unità, valuta, periodo, geografia espliciti. |
| **SAM** | come TAM, ristretto ai vincoli reali (geografia, canale, regolamentazione, segmento servibile). |
| **SOM** | **sempre derived, method `bottom_up` obbligatorio**: driver → formula → valore. Un "SOM = 3% del TAM" nudo è un blocco al gate. |

Ogni grandezza vive **una sola volta** come `ASS-`/`P-ASS-` con
`derivation.variables` esplicita; lo `structured-output.json` referenzia
(`tam_ref`/`sam_ref`/`som_ref`), non replica. Il validator **ricalcola**
ogni derivato della catena: un valore scritto a mano che diverge dal
ricalcolo è `value_mismatch`.

**Driver tipici del SOM bottom-up:** clienti eleggibili nel beachhead ×
quota raggiungibile (capacità commerciale reale, non desiderio) × valore
annuo per cliente (ARPA). La quota raggiungibile deve reggere il confronto
con la capacità GTM che emergerà allo Stage 6 (tensione SOM↔GTM, ciclo
di conflitto — mai riscrittura silenziosa dello Stage 4).

## Riconciliazione dei metodi di sizing

Una variabile canonica per metodo (`tam_topdown`, `tam_bottomup`) + una
variabile riconciliata (`tam_canonical`) referenziata dai downstream. Due
sole strategie ammesse:

- **`weighted_average`**: formula DSL con pesi `ratio` che **sommano a 1**
  (i pesi sono a loro volta `ASS-`);
- **`selected_ref`**: selezione motivata di **una** stima — richiede
  `rationale` e `decision_ref` (`DEC-`) obbligatori; il valore canonico
  coincide con la stima selezionata.

Mai due valori concorrenti nello stesso `ASS-`; mai una terza strategia.

## Contesto strategico: PESTEL e Porter (qualitativi, tracciati)

- **PESTEL**: solo i fattori che cambiano una decisione del piano
  (regolamentazione, tecnologia, macro-trend) — ogni fattore con classe di
  evidenza e fonte nel `source-register`.
- **Porter (5 forze)**: intensità competitiva, potere di
  fornitori/clienti, minaccia di nuovi entranti/sostituti — sintesi in
  `analysis.md`, claim rilevanti classificati. Nessun numero inventato:
  i fattori qualitativi non generano `ASS-` quantitativi impliciti.

## Competitive landscape (nessun competitor inventato)

Sei categorie, **tutte valutate**:

`direct` · `indirect` · `substitutes` · `internal` (soluzioni fatte in
casa dal cliente) · `non_consumption` (non fare nulla) · `status_quo`
(come si gestisce oggi, dallo Stage 1).

- Ogni competitor: id `CMP-`, `name`, `assessment` (perché vince/perde
  contro la nostra value proposition — valutazione, non elenco).
- Categoria senza attori reali: `result: "none_identified"` con
  `research_notes` (dove hai cercato) e `rationale` (perché è plausibile
  che non ci sia nessuno) **obbligatori**.
- Categoria **assente** dal landscape → FAIL del validator: non valutare
  non è un'opzione.

## Contratto dell'output strutturato (Stage 4)

```json
{
  "market_model": {
    "tam_ref": "P-ASS-008",
    "sam_ref": "P-ASS-010",
    "som_ref": "P-ASS-011",
    "geography": "IT",
    "period": "Y1"
  },
  "competitive_landscape": {
    "categories": {
      "direct": { "competitors": [
        { "id": "CMP-001", "name": "…", "assessment": "…" } ] },
      "non_consumption": {
        "result": "none_identified",
        "research_notes": "…", "rationale": "…" }
    }
  }
}
```

## Criteri di completezza (gate dello stage)

1. SOM bottom-up con driver espliciti; `SOM ≤ SAM ≤ TAM` (stessa unità).
2. TAM/SAM con metodo indipendente e riconciliazione se ≥2 metodi.
3. Ogni categoria competitor valutata (o `none_identified` motivato).
4. Fonti nel `source-register` con `quality_rating`; stime etichettate
   `model_estimate`, mai spacciate per `external_source`.

## Failure mode tipici

- SOM %-di-TAM nudo → `blocked`.
- Prezzo di mercato diverso dal prezzo che comparirà nel business model →
  stessa variabile `ASS-`, mai due valori (incoerenza tipica).
- SOM incompatibile con la capacità GTM → verrà rilevato dallo Stage 6
  (ciclo di conflitto): non "aggiustare" il SOM preventivamente senza evidenza.
- Landscape gonfiato di nomi senza `assessment`: la categoria è valutata
  solo se ogni attore è confrontato con la value proposition.
