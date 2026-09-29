# Metodologia

Un business plan credibile non è un testo che racconta bene un'idea: è un
sistema logico in cui ogni numero discende da driver dichiarati e ogni
affermazione è riconducibile a un'evidenza o a un'assunzione esplicita. La
skill applica questa idea con regole verificabili dai validator.

I moduli metodologici completi, caricati da Claude solo quando servono,
sono nel pacchetto:
[`methodology/`](../.claude/skills/business-plan-orchestrator/methodology/).

## I principi

### 1. Evidenze prima della narrativa

Ogni affermazione rilevante appartiene a una classe:

| Classe | Significato |
|---|---|
| `verified_fact` | verificato in modo indipendente e riproducibile |
| `internal_evidence` | prodotto dall'azienda, non ancora verificato esternamente |
| `external_source` | da una fonte terza (report, pubblicazione, dato pubblico) |
| `founder_assumption` | dichiarato dal founder, non ancora supportato da dati |
| `model_estimate` | derivato da un calcolo del modello |
| `missing_information` | lacuna dichiarata |

Nessuna ipotesi diventa un fatto in silenzio: nel documento finale ogni
valore di assunzione porta la sua etichetta.

### 2. Un solo registro di assunzioni

Tutti i valori quantitativi vivono in `shared/assumptions-register.json`
(`ASS-*`). Non si introducono numeri direttamente nei capitoli, non si usano
valori diversi in sezioni diverse e non si correggono incoerenze senza
registrare la decisione. Un valore divergente produce
`INCOERENZA RILEVATA`, mai una media o una scelta silenziosa.

### 3. Driver prima delle percentuali

Ricavi, costi e crescita derivano da driver espliciti:

```text
Ricavi_t        = Clienti attivi_t × Ordini medi_t × Prezzo medio netto_t
Clienti attivi_t = Clienti attivi_(t-1) + Nuovi clienti_t − Clienti persi_t
Nuovi clienti_t  = Lead_t × Conversion rate_t
MRR finale       = MRR iniziale + new MRR + expansion MRR − churned MRR
```

### 4. Cassa prima dell'utile

Burn mensile, runway, capitale circolante, tempi di incasso e pagamento e
fabbisogno di cassa cumulato vengono prima del risultato economico: un utile
positivo con cassa negativa è un problema, non un successo.

### 5. Milestone prima del funding

```text
Milestone → attività → risorse → costi → timing dei flussi
→ fabbisogno di cassa → funding request
```

La richiesta di capitale deriva dal fabbisogno modellato e lo riconcilia;
il gap residuo è sempre dichiarato.

### 6. Executive summary per ultimo

L'executive summary si compone solo quando tutte le sezioni sono approvate,
il modello finanziario è validato e la funding request è riconciliata.

## Scenari

Il piano finanziario produce tre scenari (`base`, `downside`, `upside`) come
tre calcoli distinti, non tre etichette sulla stessa serie. Se i dati non
permettono uno scenario, lo scenario è dichiarato `NOT_APPLICABLE` con una
motivazione e lo stage si chiude con una condizione aperta.

## Classificazione della startup

Tipo (SaaS, marketplace, foodtech, deep-tech, …), stadio di sviluppo,
lettore primario (business angel, VC, banca, bando pubblico, …), tipo di
funding e orizzonte temporale orientano le domande e le metriche dominanti:
per esempio MRR, churn e CAC per un SaaS; capex e capitale circolante per
un'industriale; DSCR e covenant per un lettore bancario.

## Che cosa la metodologia non garantisce

La skill impedisce incoerenze numeriche e strutturali e rende visibili le
lacune, ma non può sapere se le tue ipotesi sono vere. La qualità del piano
dipende dalle evidenze che porti; le decisioni restano tue.
