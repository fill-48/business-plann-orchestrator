# Metodologia — Value proposition (Stage 3)

> Caricare **solo** quando si lavora su `03_value-proposition/`
> (workflow `04_value-proposition.md`). Fonte:
> [`reference/architecture.md`](../reference/architecture.md) §10. Framework: Value
> Proposition Canvas (jobs/pains/gains ↔ relievers/creators).

## Struttura del canvas (VPC)

Lato cliente (dallo Stage 1–2, non reinventato qui):

- **jobs**: cosa il cliente sta cercando di fare (funzionali, sociali,
  emotivi);
- **pains**: cosa fa male mentre lo fa (dal problema di Stage 1);
- **gains**: cosa vorrebbe ottenere in più.

Lato offerta:

- **pain relievers**: come la soluzione riduce pains specifici;
- **gain creators**: come produce gains specifici.

**Regola di mapping:** ogni pain reliever e gain creator deve
mappare un pain/gain che esiste negli output di Stage 1–2 (stesso
vocabolario, riferimenti espliciti al `SEG-` interessato). Un reliever
senza pain a monte è marketing, non value proposition. Selezionare i
**top 3** job/pain/gain, non l'inventario completo.

## Value metrics e switching rationale

- **Perché meglio dello status quo:** confronto esplicito con le
  alternative dello Stage 1 — che cosa giustifica il costo di switching?
- **Metrica di valore:** la grandezza misurabile su cui il cliente
  percepisce il beneficio (ore risparmiate, % scarto, € recuperati).
  Se quantificata, la cifra è una `P-ASS-*` referenziata, mai un numero
  inline nello slogan.
- Uno slogan senza metrica non supera il gate ("slogan senza
  metrica" è un blocco).

## Proof points (il cuore del checkpoint evidenze)

Ogni claim rilevante della value proposition è un **proof point**:

```json
{
  "claim": "riduce il tempo di preparazione del 30%",
  "evidence_classification": "internal_evidence",
  "evidence_refs": ["EVD-003"],
  "value_metric_ref": "P-ASS-002"
}
```

Regole vincolanti:

- `evidence_classification` usa **esattamente** le 6 classi di
  `methodology/evidence-framework.md` (`verified_fact` ·
  `internal_evidence` · `external_source` · `founder_assumption` ·
  `model_estimate` · `missing_information`);
- una classe validata (`verified_fact`/`internal_evidence`/
  `external_source`) **richiede** `evidence_refs` (EVD-*) — un claim
  "validato" senza evidenza referenziata è invalido;
- un claim senza prova va marcato onestamente `founder_assumption` (o
  `missing_information` se il dato proprio non c'è): **claim con proof o
  marcato assunzione**, mai claim nudo.

## Checkpoint evidenze (tra Stage 3 e Stage 4)

Il gate distingue tre stati: `validated_evidence` (almeno un proof point
con classe validata), `unvalidated` (solo `founder_assumption`/
`model_estimate`), `missing_information`.

**Regola enforced da `validate_stage_gate` (egress Stage 3):** uno Stage 3
fondato **solo su assunzioni non validate** non può chiudersi `approved`.
Al massimo `approved_with_conditions`, con una `COND-` che porta:

- `validation_action` concreta (es. "5 interviste buyer con test di
  pricing", non "validare meglio");
- `owner` (`founder`/`external`/`orchestrator`);
- `due_before_stage` a valle (tipicamente `04_market-and-competition`):
  la COND aperta **blocca l'ingresso** dello stage dovuto finché non è
  `resolved`/`waived` con `DEC-` tracciata.

## Contratto dell'output strutturato (Stage 3)

```json
{
  "value_proposition": {
    "id": "VP-001",
    "segment_ref": "SEG-001",
    "jobs": ["…top 3…"],
    "pains": ["…top 3, dal problema di Stage 1…"],
    "gains": ["…top 3…"],
    "mapping": [
      { "pain": "…", "reliever": "…" },
      { "gain": "…", "creator": "…" }
    ],
    "switching_rationale": "…vs status quo di Stage 1…",
    "value_metrics": [ { "metric": "…", "ref": "P-ASS-002" } ],
    "proof_points": [ …vedi sopra… ]
  }
}
```

## Criteri di completezza (gate dello stage e checkpoint evidenze)

1. Ogni gain/pain mappato dagli output di Stage 1–2 (riferimenti a `SEG-`).
2. Ogni claim con proof point o marcato assunzione.
3. Metrica di valore presente e referenziata.
4. Se nessun proof point è validato: `COND-` completa proposta nel
   candidate (`proposed-conditions.json`) e gate al massimo
   `approved_with_conditions`.

## Failure mode tipici

- Gain dichiarato qui e mai ripreso come driver in Stage 5–6 (incoerenza
  tipica): i value metrics diventano i driver di pricing/funnel.
- Proof point che "promuove" una `founder_assumption` a `external_source`
  perché citata in un articolo generico: la classe la decide la qualità
  della fonte sul claim specifico, non la presenza di un link.
- Nessun proof né gap dichiarato: blocco al gate.
