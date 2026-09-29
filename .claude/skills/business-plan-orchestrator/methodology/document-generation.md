# Metodologia — Document generation (Stage 13)

Caricata **on-demand** dal workflow
[`workflows/14_document-generation.md`](../workflows/14_document-generation.md)
e dal runtime-agent
[`runtime-agents/business-plan-writer.md`](../runtime-agents/business-plan-writer.md).
Le classi di evidenza sono quelle di
[`methodology/evidence-framework.md`](evidence-framework.md), esatte e non
parafrasabili.

---

## 1. Il principio, prima di ogni regola

> Lo Stage 13 **assembla** il business plan che gli stage precedenti hanno già
> approvato. Non pensa di nuovo il piano: lo rende leggibile, verificabile e
> completo, senza aggiungere né togliere nulla di materiale.

```text
EVIDENZE PRIMA DELLA NARRATIVA
UNA SOLA FONTE: I CANONICI JSON
NESSUN NUMERO FUORI DA UN LEGAME
NESSUNA ASSUNZIONE PROMOSSA A FATTO
EXECUTIVE SUMMARY PER ULTIMO
```

## 2. Il confine A / B / C / D

| Classe | Che cosa lo Stage 13 può fare | Esempi |
|---|---|---|
| **A. Presentazione — ammessa** | ordinare, raggruppare, titolare, numerare, tabulare, citare verbatim, etichettare lo stato epistemico | due capitoli dallo stesso canonico dello Stage 4; tabella degli impieghi dallo Stage 11 |
| **B. Riconciliazione per identità — ammessa** | confronti di **identità** fra dati già autoritativi, senza scegliere un vincitore | impronta di un canonico = checksum della Data Room; stesso legame per il capitale richiesto ovunque |
| **C. Contraddizione o lacuna — fail-closed** | rifiuto attribuito e, fra due valori, blocco `INCOERENZA RILEVATA`; mai mediare, mai scegliere il più recente | canonico mutato dopo la Data Room; base finanziaria stantia; riferimento non risolto |
| **D. Nuovo ragionamento — vietato** | — | ricerca di mercato, stime, ricalcoli, nuove assunzioni, scelta fra scenari, riscrittura di un'argomentazione approvata |

## 3. Le tre classi di testo

Ogni carattere del documento appartiene a una di tre classi, e a nessun'altra:

- **verbatim canonico** — una stringa di un canonico degli Stage 1–12, citata
  intatta con il proprio `json_path`;
- **modello costante** — una frase della tabella chiusa del costruttore, **senza
  cifre**;
- **letterale legato** — `bindings[].rendered`: il valore della foglia
  sorgente **verbatim**, con unità o valuta e l'etichetta epistemica dovuta.

Un blocco di modello da cui, tolti i letterali legati, resta una cifra è
respinto (`docgen_untraced_value`). Nessun numero è convertito, arrotondato o
localizzato: il documento mostra la stringa sorgente.

## 4. Diciassette capitoli, ordine fisso

| # | Capitolo | Fonti |
|---|---|---|
| 1 | Executive summary | tutti, assemblato per ultimo |
| 2 | Società e progetto | profilo, configurazione, governance dello Stage 8 |
| 3 | Problema e bisogno del cliente | Stage 1 |
| 4 | Segmentazione dei clienti | Stage 2 |
| 5 | Soluzione e proposta di valore | Stage 3 |
| 6 | Analisi di mercato | Stage 4, `market_model` |
| 7 | Scenario competitivo | Stage 4, `competitive_landscape` |
| 8 | Modello di business | Stage 5 |
| 9 | Go-to-market | Stage 6 |
| 10 | Operations e tecnologia | Stage 7 |
| 11 | Proprietà intellettuale e difendibilità | Stage 7, `ip_strategy` |
| 12 | Team e governance | Stage 8 |
| 13 | Roadmap e milestone | Stage 9 e copertura dallo Stage 11 |
| 14 | Analisi dei rischi | registro dei rischi e rinvii degli Stage 7–9 |
| 15 | Piano finanziario | Stage 10, catalogo chiuso |
| 16 | Richiesta di finanziamento e impiego dei fondi | Stage 11 |
| 17 | Appendice e indice della data room | Stage 12 e registri |

Nessun capitolo è aggiunto o tolto per preferenza di stile. Un capitolo senza
contenuto porta un avviso con il motivo, mai il silenzio.

## 5. L'executive summary

Non è un riassunto libero: è **assemblato** dagli stessi legami dei capitoli.
Identità del progetto, problema verbatim, segmento **beachhead** per
riferimento (mai un altro segmento chiamato «target»), soluzione verbatim,
TAM/SAM/SOM e prezzo con la loro etichetta, copertura dei claim della Data
Room e fino a cinque claim **supportati**, fino a cinque milestone, fabbisogno,
runway e pareggio dello Stage 10, capitale richiesto, impieghi e runway dello
Stage 11 con lo **stesso** legame dei capitoli 15 e 16, e lo stato del piano:
prontezza, condizioni aperte e claim non supportati o contestati **per
nome**. Chiude l'avvertenza che la review finale non è stata eseguita.

## 6. Numeri, provenienza e Data Room

| Fonte | Regola |
|---|---|
| Stage 10 | solo il catalogo chiuso: calendario, metriche di modulo non per periodo, stato dei moduli, scenari, validazione; serie per periodo e conto economico completo restano nel capitolo e nel workbook dello Stage 10, **rinviati e non copiati** |
| Stage 11 | importo, fabbisogno, impieghi, runway `to_zero` e `to_buffer` mai collassati, sufficienza, tranche e narrativa **verbatim** |
| Stage 12 | ogni ingresso immutabile ha lo sha256 del manifest della Data Room; i claim sono citati con il loro `support_status` verbatim; i conflitti sono resi `INCOERENZA RILEVATA` |
| Registri | un valore `ASS-*` porta la sua etichetta: `(ipotesi del founder)`, `(stima)`, `(dato mancante)`, `(da validare)`; nessuna etichetta solo per un fatto verificato e validato |

Un registro modificato dopo la Data Room è un **WARNING** divulgato
nell'appendice; un canonico modificato, o un record di driver dello Stage 10
diverso da quello su cui il piano è stato calcolato, blocca la costruzione.

## 7. Disclosure che non si sopprimono

Condizioni aperte, claim non supportati o contestati, conflitti e lacune della
Data Room, prontezza del piano finanziario diversa da `ready`, copertura di
scenario parziale, residuo e voci non risolte della funding request, e review
finale non eseguita: sempre **nominati** — id e testo — mai come un conteggio
calcolato. Un'assunzione aperta non è un errore: lo diventa solo se resa senza
la propria etichetta.

## 8. Resa Markdown

Il derivato `output/business-plan.md` è la resa deterministica del canonico
committato: un titolo H1, diciassette H2 «N. Titolo», sezioni H3 «N.M
Titolo», indice con ancore esplicite, numerazione **logica** e nessun numero
di pagina. PDF e DOCX non sono inclusi in v0.7.1 e non si annunciano.

## 9. Anti-pattern

- trasformare la sintesi in un testo scritto da capo;
- leggere un numero dal capitolo Markdown o dal workbook invece che dal
  canonico;
- «arrotondare per leggibilità»;
- tacere una condizione aperta o un claim non supportato;
- trattare un'incoerenza come un refuso;
- dichiarare chiuso un debito o una condizione perché compare nel documento.
