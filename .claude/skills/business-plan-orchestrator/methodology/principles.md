# Principi non negoziabili

> Fonte: [`reference/architecture.md`](../reference/architecture.md) §3. Caricare questo
> file quando l'orchestratore deve validare una decisione, non per farne un
> riassunto narrativo nelle sezioni del piano.

Per ciascun principio: cosa impone all'orchestratore, e come si riconosce una
violazione.

## 1. Evidenze prima della narrativa

**Impone:** ogni affermazione rilevante è classificata in una delle 6 classi
(`methodology/evidence-framework.md`). Nessun subagent trasforma silenziosamente
un'ipotesi in un fatto.

**Test di violazione:** un claim quantitativo o strategico compare nel testo senza
un `EVD-<id>` o `ASS-<id>` associato in `affected_sections`.

## 2. Un solo set ufficiale di assunzioni

**Impone:** tutto il sistema usa un unico `assumptions-register.json`. Vietato:
introdurre assunzioni direttamente nei capitoli, modificare numeri senza
aggiornare il registro, usare valori diversi in sezioni diverse, correggere
incoerenze senza registrare la decisione.

**Test di violazione:** lo stesso concetto (es. "prezzo medio netto") ha due valori
diversi in due file → apri `INCOERENZA RILEVATA`, non mediare.

## 3. Driver prima delle percentuali

**Impone:** ricavi, costi e crescita derivano da driver espliciti, non da
percentuali dichiarate senza scomposizione.

Driver commerciale minimo:
```text
Ricavi_t = Clienti attivi_t × Ordini medi_t × Prezzo medio netto_t
Clienti attivi_t = Clienti attivi_(t-1) + Nuovi clienti_t - Clienti persi_t
Nuovi clienti_t = Lead_t × Conversion rate_t
```

Driver SaaS minimo:
```text
MRR finale = MRR iniziale + new MRR + expansion MRR - churned MRR
```

Driver deep-tech minimo:
```text
Fabbisogno di cassa = costo milestone + overhead + contingency - funding secured
```

**Test di violazione:** un numero di ricavo/costo compare senza un driver
tracciabile a monte.

## 4. Cassa prima dell'utile

**Impone:** priorità a burn mensile, runway, capitale circolante, timing incassi
e pagamenti, capex, funding gap, fabbisogno di cassa cumulato. Un risultato
economico positivo non basta se la cassa diventa negativa (rilevante soprattutto
per startup grant-driven, dove l'utile contabile può essere fuorviante).

**Test di violazione:** il piano mostra utile netto positivo senza mostrare il
profilo di cassa nello stesso periodo.

## 5. Milestone prima del funding

**Impone:** la funding request deriva in quest'ordine, mai al contrario:
```text
Milestone → attività → risorse → costi → timing dei flussi
→ fabbisogno di cassa → funding request
```

**Test di violazione:** un importo di funding request compare prima che esistano
milestone, attività e costi che lo giustifichino.

## 6. Executive summary per ultimo

**Impone:** l'executive summary si genera solo quando tutte le sezioni sono
complete, il financial model è validato, il funding request è riconciliato e il
red-team review non rileva criticità bloccanti. In v0.7.1 il review loop
finale avversariale (red-team) non è incluso: l'executive summary dello
Stage 13 dichiara esplicitamente che la review finale non è stata eseguita
(vedi `methodology/document-generation.md`).

**Test di violazione:** viene scritto o richiesto un executive summary prima che
gli stage a monte siano `approved`.

---

## Scenari obbligatori

Il financial plan (Stage 10) deve sempre includere `base_case`,
`downside_case`, `upside_case` — mai un solo scenario.

## Revisione avversariale

Il sistema cerca attivamente: incoerenze numeriche, assunzioni non supportate,
claim senza fonte, ricavi non riconciliati, market sizing debole, funding non
allineato alla roadmap, cassa negativa non evidenziata, working capital ignorato,
rischi non mitigati, contraddizioni tra capitoli. In v0.7.1 questa ricerca è
affidata ai validator e ai gate di ciascuno stage; il review loop finale e la
revisione red-team descritti in `reference/architecture.md` §16–§17 non sono
inclusi in v0.7.1.
