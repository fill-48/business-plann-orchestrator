# Troubleshooting

## La skill non compare in Claude Code

- Verifica che esista `~/.claude/skills/business-plan-orchestrator/SKILL.md`
  (su Windows `%USERPROFILE%\.claude\skills\...`).
- Apri una **nuova** sessione: le skill vengono lette all'avvio.
- Se hai installato più copie (per esempio anche in `<repository>/.claude/skills/`),
  rimuovi quella che non usi.

## `python` non trovato o versione troppo vecchia

Gli script richiedono Python 3.12+. Su macOS e Linux l'interprete può
chiamarsi `python3`: Claude userà quello disponibile, ma verifica con
`python3 --version`. Su Windows, se `python` apre il Microsoft Store,
installa Python da python.org e disattiva gli alias dell'app in
*Impostazioni → App → Alias di esecuzione delle app*.

## `jsonschema non importabile`

```bash
python -m pip install -r requirements.txt
```

Installa il pacchetto per lo **stesso** interprete che Claude Code usa
(`python -m pip`, non un `pip` qualsiasi nel PATH).

## Un validator termina con exit 1, 2 o 3

| Exit | Significato | Che cosa fare |
|---|---|---|
| 1 | il candidate non è valido | leggi i codici di errore nel report JSON e correggi la proposta; nulla è stato scritto nei file canonici |
| 2 | errore d'uso | parametri sbagliati o validator invocato su uno stage che non copre |
| 3 | stato canonico non valido | un file canonico o un registro è stato modificato a mano o è corrotto: ripristinalo (per esempio da Git) prima di proseguire |

## Un'operazione si è interrotta a metà

Il transaction manager registra un journal in `shared/.tx/`. Esegui:

```bash
python "<skill_dir>/transaction/transaction_manager.py" recover --project <progetto>
```

dove `<skill_dir>` è la directory della skill installata. Il comando completa
o annulla l'operazione interrotta; su un progetto pulito non fa nulla.

## `stage_not_implemented`

Il transaction manager rifiuta operazioni su stage oltre il
`release_boundary` dichiarato in `config/enforcement-config.json`. In 0.7.1
il confine è l'ultimo stage (`13_document-generation`): se vedi questo
errore, lo stage indicato non esiste o la configurazione è stata modificata.

## `fr_input_incomplete` allo Stage 11

La funding request richiede che canonico, capitolo e workbook dello Stage 10
esistano e siano validati. Completa lo Stage 10 (inclusa la generazione dei
derivati) prima di aprire lo Stage 11.

## `docgen_output_stale`

`output/business-plan.md` esiste ma non corrisponde al documento canonico
(probabilmente è stato modificato a mano). Il file non viene sovrascritto:
spostalo o ripristinalo e rilancia la pubblicazione.

## `real_project_write_forbidden`

I generatori dello Stage 10 rifiutano un progetto che si trova **dentro la
directory della skill** (per esempio dentro
`~/.claude/skills/business-plan-orchestrator/`): i progetti vanno creati
nella tua cartella di lavoro. Sposta il progetto fuori dalla directory della
skill e ripeti il passo. (Fino alla baseline 0.7.0 la guardia rifiutava
anche i progetti sotto `~/projects/`: è stato corretto nella 0.7.1.)

## Path lunghi su Windows

Progetti annidati in cartelle profonde (per esempio dentro cartelle
sincronizzate con servizi cloud) possono superare il limite di 260 caratteri dei path di Windows. Usa una cartella di
lavoro con un path breve (per esempio `C:\bp\<progetto>`) oppure abilita il
supporto ai path lunghi di Windows.

## I test falliscono

- Usa Python 3.12+ con `jsonschema` installato.
- Esegui `bash tests/run-tests.sh --smoke` per isolare i problemi di
  ambiente (installer, shell, dipendenze) dai test del runtime.
- Su Windows lo smoke test degli installer usa Git Bash e PowerShell se
  disponibili; senza nessuno dei due fallisce con un messaggio esplicito.
