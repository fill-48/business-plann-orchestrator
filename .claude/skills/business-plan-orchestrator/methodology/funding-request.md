# Metodologia — Funding request (Stage 11)

Caricata **on-demand** dal workflow
[`workflows/12_funding-request.md`](../workflows/12_funding-request.md) e dal
runtime-agent
[`runtime-agents/funding-strategist.md`](../runtime-agents/funding-strategist.md).

---

## 1. Il principio, prima di ogni regola

> La funding request è una **proiezione sul piano finanziario accettato**.
> Non è un secondo motore finanziario, e non è un esercizio di persuasione.

Una richiesta di capitale che non risale, cifra per cifra, al piano che la
sostiene non è una richiesta debole: è una richiesta **non verificabile**. Il
lettore — business angel, banca, valutatore di un bando — non può distinguere
un numero modellato da un numero desiderato, e a quel punto smette di
distinguere e sconta tutto.

Da qui discendono i cinque divieti che questa metodologia impone e che il
validator misura:

```text
NESSUN RICALCOLO SILENZIOSO
NESSUNA CIFRA MANUALE NON SUPPORTATA
NESSUN FALLBACK NASCOSTO
NESSUNA FABBRICAZIONE DI SCENARIO
NESSUN GAP RESIDUO NASCOSTO
```

## 2. Quale fabbisogno si chiede

Il piano finanziario produce **due** misure distinte del fabbisogno, e non una:

| Misura | Significato |
|---|---|
| `funding_gap_to_zero` | capitale che porta la cassa **esattamente al punto di rottura** |
| `funding_gap_to_buffer` | capitale che rispetta la **soglia di cassa dichiarata dal fondatore** |

La misura **primaria** è `funding_gap_to_buffer`. Il **fallback** a
`funding_gap_to_zero` si attiva **solo e soltanto** quando la primaria vale
`NOT_APPLICABLE`, cioè quando nessuna `cash_buffer_policy` è stata dichiarata.

Dove il fondatore ha dichiarato una politica di cassa, ignorarla per chiedere
meno non è prudenza: è scartare una decisione canonica in favore di una misura
più debole. E dove la politica **non** esiste, la soglia non è zero: è **non
applicabile**, e inventarla trasformerebbe un `missing_information` in un
`model_estimate` non dichiarato.

**Il buffer non si somma.** `funding_gap_to_buffer` nasce già da
`max(0, soglia − minimo di cassa)`: aggiungervi di nuovo la soglia gonfierebbe
la richiesta di una grandezza già contenuta. Il buffer è quindi **esposto** per
leggibilità, e riconciliato come **componente della base**, mai come addendo.

`capital_requirement.modeled_need_ref` **nomina per esteso** il path canonico
usato. Quando scatta il fallback, il documento dichiara che la richiesta è
costruita **a cassa zero** e che nessuna soglia di buffer era disponibile: è
informazione materiale per il lettore.

## 3. Impiego dei proventi

`use_of_proceeds[]` porta **importo e percentuale insieme**. La ridondanza è
voluta: la verifica avviene su entrambi i lati, perché un errore che sopravvive
a un controllo raramente sopravvive a due.

Ogni categoria risale a un `category_id` di
`funding_gap.use_of_proceeds_candidates` e ai suoi `driver_refs`. I candidati
sono **categorie eleggibili**, non un'allocazione: nessun importo vi è
associato dal canonico, e la loro somma non è una richiesta. Il peso di una
categoria è quindi derivato dal **costo canonico** che le righe di quella
categoria portano nei moduli — ed è dichiarato in `provenance[]` con i propri
path. Non si sceglie a mano una ripartizione.

## 4. Runway e sufficienza

`runway_to_zero` e `runway_to_buffer` restano **due grandezze distinte**.
Collassarle non è una semplificazione: è la perdita dell'unica informazione che
distingue «quanto durerò» da «quanto durerò rispettando la mia politica».

Il runway **dopo** il finanziamento è **ricostruito** dal flusso di cassa
canonico, periodo per periodo, con la stessa regola del motore accettato, e con
tolleranza `count` **esatta**. Non è stimato nella narrativa.

`sufficiency.residual_gap_disclosed` è un booleano obbligatorio che può valere
**solo `true`**. Non è un vezzo di schema: rende **strutturalmente impossibile**
emettere il documento nascondendo un gap residuo. Se dopo il finanziamento
resta un buco, il lettore lo vede.

## 5. Milestone

Ogni milestone finanziata mappa a un `MIL-*` **datato e costato**, risolto
contro il registro **reale** della roadmap dello Stage 9 — mai contro una lista
locale.

`out_of_horizon_milestones` va **letto e dichiarato**: una milestone oltre
l'orizzonte ha un costo che **non** è nei totali, e ignorarla sottostimerebbe
in silenzio il fabbisogno. La sua `target_date` resta **nulla**: una milestone
fuori orizzonte non riceve una data plausibile.

Il residuo non mappato è **esposto**, mai assorbito.

## 6. Scenari — e il caso in cui non ci sono

Gli identificatori di scenario sono quelli canonici, minuscoli: `base`,
`downside`, `upside`.

Quando `scenarios.coverage.level` vale `none`, gli scenari avversi **non sono
prodotti e non sono etichettati**: restano `NOT_APPLICABLE` con motivazione
nominata, il documento dichiara che la richiesta è formulata sul **solo
scenario base** e **perché**, e
`dependencies_and_assumptions.decision_needed[]` nomina
`COND-S10-SCENARIO-COVERAGE`.

```text
"Non abbiamo dati per testare il peggio."       CORRETTO
"Il peggio non cambia nulla."                   FABBRICAZIONE
```

Tre serie identiche etichettate con tre nomi diversi non sono un'analisi di
sensitività: sono una figura retorica con l'aspetto di un'analisi.

## 7. Ciò che questo stage non possiede

Valutazione, diluizione, strumento, prezzo, dimensione del round, quota e
termini **non sono prodotti qui**. Lo schema è chiuso e li rende irricevibili;
il validator li respinge anche per contratto, nominando il termine iniettato.

`funding_type`, `primary_reader` e `development_stage` si **leggono** da
`shared/startup-profile.json`. Non si inferiscono dal tono della
conversazione, dalla dimensione del fabbisogno o dal settore: un lettore
sbagliato produce un documento sbagliato, e la deduzione non lascia traccia.

Un termine ignoto assume lo stato dichiarato
`decision_needed {code, question, blocking}`. È la stessa disciplina di
`missing_information` del framework delle evidenze: l'assenza è **visibile**.

## 8. Provenienza e narrativa

Ogni campo numerico ha una voce `provenance[]` con path canonico, scenario,
periodo, unità, valuta e checksum della generazione. Il join fra campi emessi e
provenienza ha residuo **zero**.

La narrativa **non calcola**. Ogni numero citato nella prosa è in
`narrative.numeric_refs[]` e risolve in `provenance[]`. Un numero che compare
solo in prosa è, per definizione, un numero che nessuno ha verificato.

Gli identificatori di evidenza e di fonte sono **tipizzati** in forma canonica
degli id (`EVD-001`, `SRC-1000`). Un alias con padding divergente — `EVD-0021` —
è **riconosciuto e respinto** con codice attribuito, mai normalizzato,
troncato o riscritto: fra un errore diagnosticabile e un riferimento che
sparisce, si sceglie il primo.

## 9. Stato propagato

Il documento **propaga** — non lava — lo stato del piano finanziario. Una
funding request che uscisse «PASS» da un piano `approved_with_conditions`
sarebbe una richiesta **non sostenuta dall'evidenza**, e la prima domanda del
lettore la smonterebbe.

Allo stesso modo, nessun finding è chiuso perché esiste un artefatto nuovo. Un
debito resta `APERTO` finché non è **sanato con prova**.
