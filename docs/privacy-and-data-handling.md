# Privacy e trattamento dei dati

Un business plan contiene spesso informazioni riservate: dati finanziari,
strategia, proprietà intellettuale, nomi di clienti, partner, dipendenti e
investitori. Questa pagina spiega dove finiscono i dati che inserisci.

## Dove vivono i dati

- **Sul tuo disco**, nella cartella di progetto che la skill crea nella tua
  working directory. La skill non crea copie altrove.
- Gli **script della skill** (transaction manager, validator, generatori)
  leggono e scrivono solo file locali del progetto e **non effettuano
  chiamate di rete**.
- La **data room** indicizza i documenti dove si trovano: non li copia, non
  li sposta e non li modifica.

## Che cosa passa da Claude

Durante la sessione Claude legge i file del progetto e le tue risposte per
guidarti. Questi contenuti sono elaborati da Claude Code secondo le
condizioni del servizio e del piano che usi (per esempio sulla conservazione
e sull'uso dei dati). Prima di inserire informazioni riservate verifica che
quelle condizioni siano compatibili con i tuoi obblighi (accordi di
riservatezza, GDPR, segreto industriale).

Se nella stessa sessione abiliti altre skill, MCP server o strumenti di
ricerca web, quegli strumenti possono trasmettere dati a terzi secondo le
proprie regole. La skill non deve inviare dati del progetto a servizi
esterni senza dirtelo e senza il tuo consenso.

## Minimizzare

- Inserisci solo i dati necessari al piano. Per persone e clienti, ruoli e
  numeri aggregati bastano quasi sempre.
- Non inserire credenziali, chiavi API, password o dati di pagamento. I
  validator della data room e della document generation segnalano i segreti
  riconoscibili, ma non sostituiscono la tua attenzione.
- Anonimizza le interviste prima di salvarle nel progetto.

## Versionare un progetto

- **Non** mettere progetti reali in repository pubblici, né in fork pubblici
  di questo repository.
- Se usi un repository privato, escludi almeno journal, candidate, output
  generati e file di ambiente (vedi l'esempio in [`SECURITY.md`](../SECURITY.md)).
- Ricorda che la data room indicizza i file del progetto: se versioni il
  progetto, versioni anche quei documenti.

## Condividere il piano

`output/business-plan.md`, il capitolo finanziario e il workbook contengono
i tuoi dati. Condividili solo con chi deve riceverli e verifica che non
includano informazioni che non intendi divulgare (per esempio nomi di
clienti nelle evidenze).

## Segnalare un problema

Se noti che la skill tratta i dati in modo diverso da quanto descritto qui,
segnalalo in privato come indicato in [`SECURITY.md`](../SECURITY.md).
