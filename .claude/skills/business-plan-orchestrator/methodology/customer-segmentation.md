# Metodologia — Customer segmentation (Stage 2)

> Caricare **solo** quando si lavora su `02_customer-segmentation/`
> (workflow `03_customer-segmentation.md`). Fonte:
> [`reference/architecture.md`](../reference/architecture.md) §10.

## I ruoli non sono sinonimi

Per ogni segmento vanno distinti — e mai fusi — i ruoli:

| Ruolo | Domanda che lo identifica |
|---|---|
| **user** | chi usa il prodotto ogni giorno? |
| **buyer** | chi firma l'ordine di acquisto? |
| **decision maker** | chi ha l'ultima parola sulla scelta? |
| **influencer** | chi orienta la decisione senza deciderla? |
| **payer** | da quale budget escono i soldi? |
| **gatekeeper** | chi può bloccare l'adozione (IT, legale, compliance)? |

Confondere buyer e user è un **blocco** al gate dello Stage 2: il pricing, il
funnel e il GTM divergono radicalmente a seconda di chi paga davvero.
Nel B2C i ruoli possono coincidere: va **dichiarato**, non assunto.

## Segmenti (`SEG-`)

Ogni segmento è un'entità qualitativa con id `SEG-` (i numeri
referenziano `ASS-`, non li replicano):

- descrizione operativa (chi, contesto, dimensione qualitativa);
- mappa dei ruoli (sopra);
- ancoraggio al problema di Stage 1 (`problem_ref`): un segmento che non
  soffre il problema definito è fuori — l'incoerenza tipica dello Stage 2
  è il segmento incompatibile col problema;
- accessibilità: possiamo raggiungerlo con le capacità attuali?
- buying process: come compra oggi (ciclo, budget, stagionalità).

Le grandezze quantitative del segmento (numerosità, spesa media) sono
`P-ASS-*` proposte nel candidate, non numeri inline.

## Beachhead (con criterio, non per simpatia)

Il segmento prioritario iniziale (`beachhead`) va scelto con un **criterio
esplicito e tracciato**, ad esempio: intensità del problema × accessibilità
× capacità di referenza. Un beachhead senza criterio dichiarato non supera
il gate ("beachhead senza criterio" è un blocco). Il criterio va
scritto nel campo `selection_criteria` e le eventuali soglie quantitative
referenziate come assunzioni.

## Contratto dell'output strutturato (Stage 2)

```json
{
  "customer_segments": [
    {
      "id": "SEG-001",
      "name": "…",
      "description": "…",
      "roles": {
        "user": "…", "buyer": "…", "decision_maker": "…",
        "influencer": "…", "payer": "…", "gatekeeper": "…"
      },
      "problem_ref": "01_problem-and-need",
      "problem_fit": "…perché questo segmento soffre il problema…",
      "accessibility": "…",
      "buying_process": "…",
      "size_refs": ["P-ASS-001"],
      "evidence_refs": ["EVD-001"]
    }
  ],
  "beachhead": {
    "segment_ref": "SEG-001",
    "selection_criteria": "…criterio esplicito…",
    "rationale": "…"
  }
}
```

## Criteri di completezza (gate dello stage)

1. Almeno un segmento prioritario **ancorato allo Stage 1**.
2. Ruoli separati (user/buyer/DM/payer distinti o coincidenza dichiarata).
3. Beachhead con criterio esplicito.
4. Gap di evidenza sul segmento dichiarati (`missing_information` +
   `open-questions`), non nascosti.

## Failure mode tipici

- Segmento definito per demografia quando il problema è di processo (o
  viceversa): l'ancoraggio al problema decide le variabili di
  segmentazione, non l'abitudine.
- "Il mercato sono tutte le PMI italiane": non è un segmento, è un TAM
  travestito — rimandare la taglia a Stage 4 e definire qui chi soffre di
  più.
- Beachhead scelto per vicinanza personale del founder senza criterio:
  ammesso solo se dichiarato come criterio (accesso privilegiato) e
  registrato come assunzione sul canale.
