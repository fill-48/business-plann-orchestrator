# Fallback locale — Step-back analysis

> Usare **solo** se il runtime-check ha verificato che `/step-back-prompting`
> **non** è disponibile in questa installazione. Prima di applicarlo, dichiara
> esplicitamente all'utente:
>
> "Fallback in uso: la skill `/step-back-prompting` non è disponibile in questa
> installazione. Eseguo un'analisi step-back equivalente con la procedura locale
> dell'orchestratore."

## Obiettivo

Fare uno "zoom out" prima di eseguire il task, per non curare il sintomo invece
della causa — lo stesso obiettivo della skill `step-back-prompting`, ridotto
all'essenziale per la Sezione 0.

## Procedura

Dato il testo dell'idea grezza (`raw-idea.md`), rispondi in prosa breve a queste
4 domande e scrivi il risultato in `brainstorming-log.md` → sezione
"Step-back analysis":

1. **Principio guida reale.** Al di là della soluzione proposta, qual è il vero
   obiettivo che l'utente vuole raggiungere? (Non "costruire il prodotto X", ma
   il risultato economico/operativo/clinico di fondo.)
2. **Causa radice.** Qual è la frizione (costo, rischio, inefficienza, unmet
   need) che genera il bisogno di questa idea? È verificata o presunta?
3. **Macro-obiettivo.** Come si misura il successo, indipendentemente dal
   prodotto specifico descritto?
4. **Rischio di eseguire alla lettera.** Se procedessimo subito a scrivere le
   sezioni del business plan senza fare altre domande, quale errore strategico
   rischieremmo di consolidare?

## Output atteso

Un blocco di 4 risposte, ciascuna 2-4 righe, in italiano, senza inventare dati:
dove manca informazione, scrivi esplicitamente `missing_information` (vedi
`methodology/evidence-framework.md`) invece di indovinare.
