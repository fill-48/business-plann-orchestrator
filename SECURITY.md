# Security policy

## Versioni supportate

| Versione | Supportata |
|---|---|
| 0.7.1 e successive 0.7.x | sì |
| precedenti | no (mai pubblicate) |

## Come segnalare una vulnerabilità

**Non aprire una issue pubblica** per segnalare una vulnerabilità.

Usa il canale privato di GitHub: nella pagina del repository apri la scheda
**Security** → **Report a vulnerability** (GitHub Private Vulnerability
Reporting). La segnalazione resta visibile solo ai maintainer finché non viene
pubblicato un advisory.

Includi, se possibile:

- versione (tag o commit) e sistema operativo;
- descrizione del problema e impatto atteso;
- passi minimi per riprodurlo, **con dati fittizi**;
- eventuale proposta di correzione.

Non allegare business plan, modelli finanziari o documenti reali alla
segnalazione: se servono per riprodurre il problema, sostituiscili con dati
inventati.

Riceverai una prima risposta appena possibile; il progetto è mantenuto su
base volontaria e non offre tempi di risposta garantiti.

## Che cosa è in perimetro

- Script eseguibili del pacchetto (`transaction/`, `validators/`, `output/`):
  scritture fuori dalla cartella di progetto o dal candidate dichiarato,
  attraversamento di path, symlink o junction, corruzione dei registri
  canonici, esecuzione di codice a partire da input di progetto.
- Installer (`install.sh`, `install.ps1`): scritture fuori da
  `~/.claude/skills/business-plan-orchestrator/` e `~/.claude/skill-backups/`.
- Istruzioni della skill che inducano Claude a inviare dati del progetto a
  servizi esterni senza che l'utente lo sappia.

## I tuoi dati sono sensibili

I progetti creati con questa skill contengono tipicamente **business plan,
dati finanziari, informazioni su proprietà intellettuale, team, clienti e
investitori**: materiale riservato.

- **Non committare** i tuoi progetti reali in questo repository né in fork
  pubblici. La skill crea i progetti nella tua working directory; tienila
  fuori da repository pubblici.
- **Non committare segreti** (token, password, chiavi API, credenziali) né
  documenti della data room riservata. La data room *indicizza* file già
  presenti nel progetto: se il progetto è versionato, lo sono anche quei file.
- Se versioni un progetto reale in un repository **privato**, aggiungi al suo
  `.gitignore` almeno:

  ```gitignore
  **/.working/          # candidate delle transazioni
  **/shared/.tx/        # journal e lock del transaction manager
  *.bak-*               # backup degli installer
  output/               # business plan generato
  **/10_financial-plan/financial-model.xlsx
  .env
  ```

Il `.gitignore` di questo repository esclude già queste categorie, i report
di test generati e qualunque cartella `projects/` o `output/` alla radice.

## Invio di dati a servizi esterni

Gli script del pacchetto **non effettuano chiamate di rete**: leggono e
scrivono solo file locali del progetto. La skill non deve inviare dati del
progetto a servizi esterni senza una disclosure esplicita e il consenso
dell'utente. Tieni presente che:

- Claude Code elabora le conversazioni e i file che legge secondo le
  condizioni del servizio che usi;
- se abiliti altre skill, MCP server o strumenti di ricerca web, quegli
  strumenti possono trasmettere dati a terzi secondo le proprie regole.

Maggiori dettagli in [`docs/privacy-and-data-handling.md`](docs/privacy-and-data-handling.md).
