# Metodologia — Problema e bisogno (Stage 1)

> Caricare **solo** quando si lavora su `01_problem-and-need/`
> (workflow `02_problem-and-need.md`). Fonte:
> [`reference/architecture.md`](../reference/architecture.md) §10, Principio 1
> (evidenze prima della narrativa).

## Che cosa deve produrre lo Stage 1

Il problema va formulato come **costo, rischio, inefficienza, perdita o
unmet need** misurabile — mai come descrizione della soluzione. Un problema
che non può essere falsificato ("le aziende vogliono più efficienza") non
supera il gate.

Domande chiave a cui il `problem_statement` deve rispondere:

1. **Chi** ha il problema (ruolo concreto, non "tutti").
2. **Con quale frequenza** si manifesta (episodico, ricorrente, continuo).
3. **Quanto costa oggi** (tempo, denaro, rischio — con l'ordine di
   grandezza registrato come assunzione `P-ASS-*` se stimato).
4. **Quali workaround** esistono già (incluso il non-consumo: non fare
   nulla è sempre un'alternativa).
5. **Quale prova** abbiamo che il problema esiste (classificata con le 6
   classi di `methodology/evidence-framework.md`).

## Percepito vs dimostrato (esplicito, mai implicito)

Ogni problema va marcato su due assi indipendenti:

- **percepito**: il cliente lo riconosce come problema? (Un problema reale
  ma non percepito richiede un GTM educativo, e va detto.)
- **dimostrato**: esistono evidenze indipendenti dal founder?
  (`external_source`/`internal_evidence`/`verified_fact` — una
  `founder_assumption` non dimostra nulla.)

La combinazione va scritta nel campo `perceived_vs_demonstrated` del
`structured-output.json`: `perceived_and_demonstrated` ·
`perceived_only` · `demonstrated_only` · `neither`. `neither` con
intensità dichiarata alta è un'incoerenza da segnalare, non da levigare.

## Alternative e status quo

Elencare le alternative reali con cui il problema viene gestito oggi
(fornitori, processi manuali, non-consumo). Per ciascuna: perché è
insufficiente **dal punto di vista del cliente**, non del founder. Queste
alternative alimenteranno lo switching rationale dello Stage 3 e la
categoria `status_quo` del landscape di Stage 4.

## Intensità e priorità

- `intensity`: `low | medium | high` — quanto fa male quando si manifesta.
- `frequency`: quanto spesso si manifesta.
- Un problema `high/high` senza evidenze è una **ipotesi critica**, non un
  fatto: registrarlo come `founder_assumption` e proporre come validarlo.

## Contratto dell'output strutturato (Stage 1)

`structured-output.json` del candidate deve contenere:

```json
{
  "problem_statement": {
    "type": "cost | risk | inefficiency | loss | unmet_need",
    "description": "…",
    "affected_roles": ["…"],
    "frequency": "…",
    "intensity": "low | medium | high",
    "perceived_vs_demonstrated": "perceived_and_demonstrated | perceived_only | demonstrated_only | neither",
    "current_cost_refs": ["P-ASS-001"],
    "alternatives": [
      { "name": "…", "why_insufficient": "…" }
    ],
    "evidence_refs": ["EVD-001"]
  }
}
```

I valori quantitativi (costo attuale, frequenza numerica) **non** si
scrivono inline: vivono come `P-ASS-*` in `proposed-assumptions.json` e il
`structured-output.json` li **referenzia** (Principio 2: un solo set
ufficiale di assunzioni).

## Criteri di completezza (gate dello stage)

1. Problema misurabile e falsificabile.
2. Almeno **una** evidenza classificata in `evidence_refs` (anche una
   `founder_assumption` esplicita è accettabile: il punto è la
   classificazione onesta, non la perfezione).
3. `perceived_vs_demonstrated` esplicito.
4. Alternative/status quo valutati.

## Failure mode tipici

- **Soluzione travestita da problema** ("manca una app che…"): riformulare.
- **Zero evidenze senza gap dichiarato**: se non ci sono prove, il gap va
  in `open-questions` e la voce resta `missing_information` — lo stage può
  procedere solo con il gap esplicito.
- **Impatto che riappare diverso a valle** (incoerenza tipica): il
  costo del problema citato in Stage 4/5 deve referenziare lo **stesso**
  `ASS-*`, mai un secondo numero.
