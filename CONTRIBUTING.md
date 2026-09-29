# Contribuire a Business Plan Orchestrator

Grazie per l'interesse. Questo documento spiega come preparare l'ambiente,
come è organizzato il progetto e quali regole valgono per le modifiche.

## Setup

Prerequisiti:

- Python **3.12** o superiore;
- il pacchetto `jsonschema` (unica dipendenza di terze parti);
- `bash` (Linux/macOS, o Git Bash su Windows) oppure PowerShell 7+;
- Claude Code, per provare la skill in una sessione reale.

```bash
git clone https://github.com/fill-48/business-plann-orchestrator.git
cd business-plann-orchestrator
python -m pip install -r requirements.txt
bash tests/run-tests.sh            # oppure: pwsh -File tests/run-tests.ps1
```

Per provare le modifiche in Claude Code installa la skill dal tuo checkout
(`bash install.sh` o `pwsh -File install.ps1`): l'installer copia il
pacchetto in `~/.claude/skills/` con backup della versione precedente.

## Struttura del progetto

```text
.claude/skills/business-plan-orchestrator/   il pacchetto installabile (runtime)
├── SKILL.md                                 controller: instrada, non contiene il manuale
├── reference/architecture.md                specifica architetturale
├── workflows/  methodology/  runtime-agents/  templates/  fallbacks/
├── schemas/  config/  checks/  profiles/
├── transaction/transaction_manager.py       unico scrittore canonico
├── validators/                              validator deterministici
└── output/                                  generatori dello Stage 10
docs/                                        documentazione utente
examples/fictional-startup/                  esempio fittizio (anche fixture di test)
tests/smoke/                                 test rapidi: installazione, struttura, boundary
tests/integration/                           test del runtime (transazioni, validator, finanza, data room, document generation)
install.sh  install.ps1                      installer
```

Tutto ciò che serve a runtime deve stare dentro il pacchetto: la skill
installata non può dipendere da file del repository (`docs/`, `tests/`,
`examples/`). Il test `tests/smoke/test_installed_skill.py` lo verifica.

## Test richiesti

Prima di aprire una pull request:

```bash
bash tests/run-tests.sh                 # smoke + integration
bash tests/run-tests.sh --smoke         # solo i test rapidi
```

Su Windows: `pwsh -File tests/run-tests.ps1` (`-Suite smoke|integration|all`).

- Ogni modifica al runtime deve lasciare verde l'intera suite.
- Una correzione di bug arriva con un test che fallisce senza la correzione.
- Una nuova regola di validazione arriva con almeno un caso positivo e un
  caso negativo che produce il codice di errore atteso.
- La CI esegue la suite su Linux e Windows.

## Regole per le modifiche al runtime

**Schemi (`schemas/`).** Sono contratti. Un cambiamento di struttura, enum,
pattern o campi obbligatori è una modifica di contratto: va motivato nella
pull request, riflesso nei validator e nei workflow che producono quei file,
coperto da test e annotato nel `CHANGELOG.md`. Le `description` possono
essere migliorate liberamente.

**Validator (`validators/`).** Devono restare deterministici (nessun
orologio, rete o casualità), non scrivere nel progetto salvo i percorsi
dichiarati (candidate `.working/<tx>/`, derivati documentati) e riportare
esiti con codici stabili. Non cambiare il significato di un codice
esistente: aggiungine uno nuovo. Gli exit code sono parte del contratto
(0 valido, 1 candidate o esito di dominio non valido, 2 errore d'uso,
3 stato canonico del progetto non valido).

**Workflow (`workflows/`) e `SKILL.md`.** Sono istruzioni lette da Claude a
runtime. Devono descrivere il comportamento reale del codice, usare
`<skill_dir>` per invocare gli script e mantenere validi i link relativi
dentro il pacchetto. `SKILL.md` resta un controller magro.

**Transaction manager (`transaction/`).** È l'unico scrittore dei file
canonici. Qualunque modifica deve preservare atomicità, journal, rollback e
recovery; aggiungi test di crash/recovery per ogni nuovo percorso di
scrittura. Non introdurre scritture canoniche fuori dal transaction manager.

**Configurazione (`config/enforcement-config.json`).** Ordine degli stage,
matrice stage × fase × validator e tolleranze sono contratti: ogni modifica
va giustificata e testata.

## Dipendenze

Il runtime usa solo la libreria standard di Python più `jsonschema`. Non
introdurre nuove dipendenze di terze parti senza una motivazione esplicita
nella pull request (perché serve, alternative valutate, licenza,
manutenzione). Il workbook XLSX, per esempio, è generato senza librerie
esterne per scelta.

## Fixture e dati fittizi

- Usa **solo dati inventati** in fixture, test, esempi e issue: nessun
  business plan reale, nessun dato di aziende o persone reali, nessuna
  credenziale, nemmeno "di prova".
- Nomi di aziende e persone devono essere chiaramente fittizi.
- L'esempio `examples/fictional-startup/` è letto dai test: modificane il
  contenuto solo se aggiorni anche i test che ne dipendono.
- I test non devono scrivere nel checkout: usa directory temporanee.

## Commit e pull request

- Un commit per modifica logica, con messaggio all'imperativo e un prefisso
  di ambito, per esempio `validators: rifiuta alias non canonici dei claim`
  o `docs: chiarisci l'installazione su macOS`.
- La pull request descrive il problema, la soluzione, l'impatto su contratti
  e dati esistenti e i test eseguiti (usa il template proposto).
- Aggiorna la documentazione e il `CHANGELOG.md` (sezione `Unreleased`)
  quando cambia il comportamento visibile.

## Lingua

Prosa (documentazione, workflow, messaggi all'utente) in italiano; chiavi
JSON, identificatori, nomi di file e codici in inglese.

## Licenza dei contributi

Contribuendo accetti che il tuo contributo sia distribuito con la licenza MIT
del progetto.
