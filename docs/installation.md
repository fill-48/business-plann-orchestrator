# Installazione

## Requisiti

| Componente | Perché serve |
|---|---|
| Claude Code con supporto a skill e subagent | esegue la skill e lancia i subagent a runtime |
| Python 3.12 o superiore | transaction manager, validator e generatori del piano finanziario |
| pacchetto `jsonschema` | validazione dei registri e degli output canonici |
| bash oppure PowerShell | solo per lo script di installazione |

Nessun'altra dipendenza di terze parti: il workbook XLSX è generato con la
sola libreria standard di Python.

Verifica Python:

```bash
python --version          # oppure python3 --version
python -c "import jsonschema; print('jsonschema ok')"
```

## Installazione

```bash
git clone https://github.com/fill-48/business-plann-orchestrator.git
cd business-plann-orchestrator
python -m pip install -r requirements.txt
```

### macOS e Linux

```bash
bash install.sh
```

### Windows

Con PowerShell 7:

```powershell
pwsh -File install.ps1
```

Con Windows PowerShell 5.1:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

In alternativa puoi usare `bash install.sh` da Git Bash.

### Che cosa fa l'installer

1. copia `.claude/skills/business-plan-orchestrator/` in
   `~/.claude/skills/business-plan-orchestrator/` (su Windows
   `%USERPROFILE%\.claude\skills\business-plan-orchestrator\`);
2. se esiste già un'installazione, la salva prima in
   `~/.claude/skill-backups/business-plan-orchestrator.bak-<data-ora>`;
3. esclude le cache Python (`__pycache__`, `*.pyc`);
4. verifica che il numero di file installati coincida con il pacchetto;
5. avvisa (senza bloccare) se Python 3.12 o `jsonschema` non sono
   disponibili.

I backup stanno fuori da `~/.claude/skills/` perché Claude Code non li
scambi per skill duplicate.

## Verifica

Apri una **nuova** sessione di Claude Code (le skill vengono lette
all'avvio) e controlla che la skill sia disponibile, per esempio digitando
`/business-plan-orchestrator`.

Puoi anche eseguire i test del repository:

```bash
bash tests/run-tests.sh --smoke
```

## Aggiornamento

```bash
git pull
python -m pip install -r requirements.txt
bash install.sh            # oppure pwsh -File install.ps1
```

L'installazione precedente viene salvata in `~/.claude/skill-backups/`. I
tuoi progetti non vengono toccati: vivono nelle tue cartelle di lavoro, non
nella directory della skill.

## Disinstallazione

```bash
bash install.sh --uninstall
```

```powershell
pwsh -File install.ps1 -Uninstall
```

Anche la disinstallazione crea un backup. I backup si possono cancellare a
mano da `~/.claude/skill-backups/` quando non servono più.

## Installazione in un solo progetto

Se preferisci rendere la skill disponibile solo in un repository, copia la
cartella `.claude/skills/business-plan-orchestrator/` dentro
`<tuo-repository>/.claude/skills/`. Il pacchetto è autosufficiente: non
dipende da file esterni alla propria cartella.
