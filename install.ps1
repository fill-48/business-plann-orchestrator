# Install or uninstall the business-plan-orchestrator skill for Claude Code.
#
#   pwsh -File install.ps1              install (or update) into ~/.claude/skills/
#   pwsh -File install.ps1 -Uninstall   remove the installed skill
#
# An existing installation is backed up to ~/.claude/skill-backups/ before it
# is replaced or removed. Backups live outside ~/.claude/skills/ so Claude Code
# never discovers them as duplicate skills.
[CmdletBinding()]
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"

$name = "business-plan-orchestrator"
$userHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$src = Join-Path $PSScriptRoot ".claude/skills/$name"
$dstRoot = Join-Path $userHome ".claude/skills"
$dst = Join-Path $dstRoot $name
$backupRoot = Join-Path $userHome ".claude/skill-backups"

function Backup($path) {
    if (Test-Path $path) {
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $base = Join-Path $backupRoot "$name.bak-$stamp"
        $bak = $base
        $n = 1
        # Two backups in the same second must not collide (Copy-Item into an
        # existing directory would nest the copy instead of creating a backup).
        while (Test-Path $bak) {
            $bak = "$base-$n"
            $n++
        }
        Copy-Item $path $bak -Recurse -Force
        Write-Host "Backup: $bak"
    }
}

function Test-Prerequisites {
    $py = $null
    foreach ($candidate in @("python", "python3")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            & $cmd.Source -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) { $py = $cmd.Source; break }
        }
    }
    if (-not $py) {
        Write-Warning "Python not found. The skill scripts need Python >= 3.12 with the 'jsonschema' package."
        return
    }
    & $py -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "$(& $py --version 2>&1) found; the skill scripts need Python >= 3.12."
    }
    & $py -c "import jsonschema" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "The 'jsonschema' package is missing. Install it with: python -m pip install -r requirements.txt"
    }
}

if ($Uninstall) {
    Backup $dst
    if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
    Write-Host "Uninstalled."
    exit 0
}

if (-not (Test-Path (Join-Path $src "SKILL.md"))) {
    throw "SKILL.md not found in source: $src"
}

New-Item -ItemType Directory -Force -Path $dstRoot | Out-Null
Backup $dst
if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
Copy-Item $src $dst -Recurse -Force
# Local interpreter caches are never part of the package.
Get-ChildItem -Path $dst -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -Path $dst -Recurse -File -Filter "*.pyc" | Remove-Item -Force

if (-not (Test-Path (Join-Path $dst "SKILL.md"))) {
    throw "Install verification failed: SKILL.md missing"
}
$expected = @(Get-ChildItem -Path $src -Recurse -File | Where-Object {
        $_.Extension -ne ".pyc" -and $_.FullName -notmatch "[\\/]__pycache__[\\/]" }).Count
$actual = @(Get-ChildItem -Path $dst -Recurse -File).Count
if ($expected -ne $actual) {
    throw "Install verification failed: expected $expected files, found $actual"
}

Write-Host "Installed to: $dst ($actual files)"
Test-Prerequisites
