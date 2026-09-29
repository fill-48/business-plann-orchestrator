# Business Plan Orchestrator

Una skill per [Claude Code](https://docs.claude.com/en/docs/claude-code/overview)
che accompagna un founder dall'**idea grezza** a un **business plan completo,
coerente e verificabile**: un processo a stage con decision gate, registri
persistenti di assunzioni ed evidenze, validator deterministici e un modello
finanziario calcolato, non scritto a mano.

> **Stato: v0.7.1, prima release pubblica** — tutti gli Stage 0–13 sono
> implementati, dalla scoperta dell'idea alla generazione del documento
> finale. La 0.7.1 deriva dalla baseline di sviluppo 0.7.0 e ne corregge la
> guardia sulla posizione dei progetti dello Stage 10, che rifiutava i
> progetti in `~/projects/` (dettagli nel [CHANGELOG](CHANGELOG.md)). Il
> progetto è giovane: leggi [Limiti](#limiti-e-responsabilità) prima di
> usarlo per decisioni reali.

## A chi serve

- founder e team in fase pre-seed/seed che devono strutturare un'idea e
  capire se regge;
- chi prepara un piano per un business angel, un fondo, una banca o un bando
  pubblico e vuole numeri riconducibili a driver e fonti;
- advisor e incubatori che vogliono un processo ripetibile e tracciabile.

## Principi

1. **Evidenze prima della narrativa** — ogni affermazione è classificata
   (`verified_fact`, `internal_evidence`, `external_source`,
   `founder_assumption`, `model_estimate`, `missing_information`) e nessuna
   ipotesi diventa un fatto in silenzio.
2. **Driver prima delle percentuali** — ricavi e costi derivano da driver
   espliciti registrati in un unico `assumptions-register.json`.
3. **Cassa prima dell'utile** — burn, runway e fabbisogno di cassa vengono
   prima del risultato economico.
4. **Milestone prima del funding** — la richiesta di capitale deriva da
   milestone, costi e flussi di cassa, mai il contrario.

L'executive summary si scrive per ultimo, e le incoerenze tra valori non
vengono mai mediate: vengono esposte come `INCOERENZA RILEVATA` e decise
dall'utente.

## Prerequisiti

- **Claude Code** con supporto a skill e subagent;
- **Python 3.12+** con il pacchetto **`jsonschema`**: il transaction manager,
  i validator e i generatori del piano finanziario sono script Python
  eseguiti durante la sessione;
- **bash** (Linux, macOS, Git Bash) oppure **PowerShell** per l'installer.

## Installazione

```bash
git clone https://github.com/fill-48/business-plann-orchestrator.git
cd business-plann-orchestrator
python -m pip install -r requirements.txt
```

**macOS / Linux**

```bash
bash install.sh
```

**Windows (PowerShell)**

```powershell
pwsh -File install.ps1
# con Windows PowerShell 5.1: powershell -ExecutionPolicy Bypass -File install.ps1
```

L'installer copia il pacchetto in `~/.claude/skills/business-plan-orchestrator/`
e, se esiste già un'installazione, ne salva un backup in
`~/.claude/skill-backups/`. Disinstallazione: `bash install.sh --uninstall`
oppure `pwsh -File install.ps1 -Uninstall`. Dettagli e casi particolari in
[`docs/installation.md`](docs/installation.md).

## Quick start

1. Crea una cartella di lavoro per il tuo progetto, **fuori** da questo
   repository, e apri Claude Code al suo interno.
2. Invoca la skill con la tua idea:

   ```text
   /business-plan-orchestrator Voglio creare un servizio che aiuta i piccoli
   studi dentistici a ridurre gli appuntamenti mancati...
   ```

   Funziona anche in linguaggio naturale ("aiutami a trasformare questa idea
   in un business plan").
3. Rispondi alle domande dello Stage 0 e approva il **prompt contract**:
   solo dopo l'approvazione vengono create le cartelle degli stage successivi.
4. Procedi stage per stage. Ogni stage si chiude con un decision gate; in una
   nuova sessione la skill riprende da `shared/project-status.md`.

Vuoi vedere un progetto già avviato? Guarda l'esempio fittizio in
[`examples/fictional-startup/`](examples/fictional-startup/).

## Gli stage

| Stage | Cartella | Che cosa produce |
|---|---|---|
| 0 | `00_idea-discovery/` | idea verbatim, domande mirate, classificazione della startup, prompt contract, registri iniziali |
| 1 | `01_problem-and-need/` | problema misurabile e falsificabile, percepito vs dimostrato |
| 2 | `02_customer-segmentation/` | segmenti, ruoli user/buyer/decision maker, beachhead |
| 3 | `03_value-proposition/` | value proposition mappata su problema e segmenti, checkpoint delle evidenze |
| 4 | `04_market-and-competition/` | TAM/SAM/SOM ricalcolabili (SOM bottom-up), panorama competitivo |
| 5 | `05_business-model/` | prezzo, logica di ricavo per driver, contribution margin |
| 6 | `06_go-to-market/` | funnel ricalcolabile, CAC, churn, capacità commerciale |
| 7 | `07_operations-and-ip/` | processi core make/buy/partner, capacità, dipendenze, strategia IP |
| 8 | `08_team-and-governance/` | ruoli, gap di competenze, decision right, equity, hiring |
| 9 | `09_roadmap-and-milestones/` | milestone con dipendenze, owner, costi, criteri go/no-go |
| 10 | `10_financial-plan/` | modello finanziario deterministico: tre scenari, riconciliazioni, capitolo e workbook |
| 11 | `11_funding-request/` | richiesta di capitale riconciliata con fabbisogno, impieghi e runway |
| 12 | `12_data-room/` | indice delle evidenze e tracciabilità claim → evidenza |
| 13 | `13_document-generation/` | business plan finale in diciassette capitoli |

Descrizione completa in [`docs/workflow.md`](docs/workflow.md).

## Output

- `output/business-plan.md` — il business plan finale (Stage 13);
- `10_financial-plan/financial-plan.md` e `10_financial-plan/financial-model.xlsx`
  — capitolo finanziario e workbook generati dal canonico;
- `11_funding-request/funding-request.md` — la richiesta di capitale;
- `12_data-room/data-room-index.md` — l'indice della data room;
- `shared/` — registri di assunzioni, evidenze, fonti, rischi, decisioni e
  condizioni, stato del progetto;
- per ogni stage: `structured-output.json` (canonico validato),
  `handoff.md` ed eventuali bozze di sezione.

I file canonici sono scritti **solo** dal transaction manager, in modo
atomico e con journal di recovery.

## Limiti e responsabilità

- **Non è consulenza** finanziaria, legale, fiscale o d'investimento. Il
  risultato è una bozza strutturata che deve essere verificata da te e, dove
  serve, da professionisti.
- La qualità del piano dipende dalle informazioni che fornisci: la skill
  espone le lacune (`missing_information`) ma non può colmarle.
- Il modello finanziario è deterministico sui driver registrati: non
  sostituisce la tua verifica dei driver né una due diligence.
- In v0.7.1 **non** sono inclusi: un review loop finale avversariale, PDF o
  DOCX, la riapertura di un piano già completato.
- Le risposte di Claude possono contenere errori: i validator bloccano
  incoerenze numeriche e strutturali, non garantiscono che le tue ipotesi
  siano corrette.

## Privacy

I progetti restano sui tuoi file locali, nella tua working directory; gli
script della skill non effettuano chiamate di rete. Le conversazioni e i file
letti da Claude sono però elaborati da Claude Code secondo le condizioni del
servizio che usi. Non inserire dati che non puoi condividere con quel
servizio, e **non committare progetti reali in repository pubblici**. Vedi
[`docs/privacy-and-data-handling.md`](docs/privacy-and-data-handling.md) e
[`SECURITY.md`](SECURITY.md).

## Test

```bash
python -m pip install -r requirements.txt
bash tests/run-tests.sh              # tutto (smoke + integration)
bash tests/run-tests.sh --smoke      # solo i test rapidi
```

```powershell
pwsh -File tests/run-tests.ps1                 # tutto
pwsh -File tests/run-tests.ps1 -Suite smoke    # solo i test rapidi
```

I test usano directory temporanee e non scrivono nel checkout. La CI li
esegue su Linux e Windows.

## Documentazione

- [Installazione](docs/installation.md)
- [Uso](docs/usage.md)
- [Workflow e stage](docs/workflow.md)
- [Metodologia](docs/methodology.md)
- [Architettura](docs/architecture.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Privacy e trattamento dei dati](docs/privacy-and-data-handling.md)
- [Contribuire](CONTRIBUTING.md) · [Sicurezza](SECURITY.md) ·
  [Codice di condotta](CODE_OF_CONDUCT.md) · [Changelog](CHANGELOG.md)

## Licenza

[MIT](LICENSE) © 2026 Filippo Grossi
