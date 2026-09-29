# Fallback locale — Prompt contract

> Usare **solo** se il runtime-check ha verificato che `/prompt-contracts`
> **non** è disponibile in questa installazione. Prima di applicarlo, dichiara
> esplicitamente all'utente:
>
> "Fallback in uso: la skill `/prompt-contracts` non è disponibile in questa
> installazione. Compilo il prompt contract con la procedura locale
> dell'orchestratore, usando il template interno."

## Obiettivo

Produrre un contratto operativo esplicito tra utente e orchestratore prima di
aprire le sezioni successive del business plan — stesso obiettivo della skill
`prompt-contracts`, applicato al gate della Sezione 0
([`reference/architecture.md`](../reference/architecture.md) §8.5–8.6).

## Procedura

1. Usa `templates/prompt-contract.md` come scheletro.
2. Compila i 16 campi uno per uno, usando le informazioni raccolte in
   `founder-answers.md`, `startup-concept.md` e `startup-profile.json`. Non
   lasciare campi vuoti: se manca l'informazione, scrivi esplicitamente
   "da definire con l'utente" invece di ometterlo o inventarlo.
3. Presenta il contratto compilato all'utente e chiedi approvazione esplicita
   campo per campo o in blocco.
4. Se l'utente chiede modifiche, aggiorna e richiedi nuova approvazione.
5. Solo quando lo stato passa a `approved` (campo "Stato" in cima al file), il
   decision gate della Sezione 0 può considerarsi superato e le sezioni
   `01_…`–`12_…` possono
   essere create.

## Output atteso

`00_idea-discovery/prompt-contract.md` compilato e, se approvato, con
`**Stato:** approved` e data di approvazione in fondo al file.
