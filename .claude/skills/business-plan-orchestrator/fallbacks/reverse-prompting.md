# Fallback locale — Reverse prompting

> Usare **solo** se il runtime-check ha verificato che `/reverse-prompting`
> **non** è disponibile in questa installazione. Prima di applicarlo, dichiara
> esplicitamente all'utente:
>
> "Fallback in uso: la skill `/reverse-prompting` non è disponibile in questa
> installazione. Eseguo un reverse-prompting equivalente con la procedura locale
> dell'orchestratore."

## Obiettivo

Invece di chiedere subito "dimmi tutto sulla tua idea", l'agente interroga
attivamente l'utente per far emergere ciò che l'idea grezza lascia implicito —
stesso obiettivo della skill `reverse-prompting`, applicato alla Sezione 0.

## Procedura

1. Rileggi `raw-idea.md` e lo step-back già fatto (`brainstorming-log.md`).
2. Individua **3-5 assunzioni implicite** nel testo dell'utente — cose che
   l'idea grezza dà per scontate senza dichiararle (es. "chi paga davvero",
   "quanto è reale il problema", "perché questo team", "cosa succede se un
   competitor reagisce").
3. Trasforma ciascuna assunzione implicita in una **domanda esplicita** da porre
   all'utente, una alla volta (non in blocco).
4. **Se la risposta contiene un valore quantitativo o un claim rilevante**
   (prezzo, capacità, percentuale, tempistica...): **prima** di scrivere
   qualunque cosa, mostra esplicitamente nella tua risposta la riga
   `🔍 Verifica persistenza — variabile: <nome>` e cerca in
   `shared/assumptions-register.json` (non in prosa sparsa — quel registro è
   l'unica fonte autorevole, Regola A in `workflows/01_idea-discovery.md`,
   protocollo in `checks/persistence-conflict-protocol.json`) se esiste già
   una voce per la stessa categoria. Se non esiste: stato `NO_CONFLICT`,
   crea la voce con il prossimo ID e scrivila **per prima cosa**, poi riporta
   il valore anche in `brainstorming-log.md`. Se esiste con lo stesso valore:
   stato `NO_CONFLICT`, riusa l'ID, nessuna cerimonia. Se esiste con un
   valore diverso: stato `CONFLICT_DETECTED_AWAITING_CONFIRMATION`; **non
   scrivere nulla**, mostra `INCOERENZA RILEVATA` con l'**ID esistente** e
   attendi conferma esplicita in un turno utente successivo prima di
   registrare qualunque cosa. Il turno che propone il nuovo valore non può
   anche confermarlo.
5. Registra domande e risposte (risolte) in `brainstorming-log.md` → sezione
   "Reverse prompting", distinguendo `ambiguità emerse` da `risposte chiave`,
   citando lo stesso ID di assunzione usato in `assumptions-register.json`
   (mai un ID diverso).

## Output atteso

Elenco domande poste + risposte ottenute + ambiguità ancora aperte, in italiano,
senza inventare risposte che l'utente non ha dato.
