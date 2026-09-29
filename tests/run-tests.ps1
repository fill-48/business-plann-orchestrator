# Run the test suite of business-plan-orchestrator.
#
#   pwsh -File tests/run-tests.ps1                      smoke + integration
#   pwsh -File tests/run-tests.ps1 -Suite smoke         smoke tests only (fast)
#   pwsh -File tests/run-tests.ps1 -Suite integration   integration tests only
#
# Every test is a standalone script invoked as: python <test> --root <repo>.
# Tests work in temporary directories and never write into the checkout.
[CmdletBinding()]
param(
    [ValidateSet("all", "smoke", "integration")]
    [string]$Suite = "all"
)
$ErrorActionPreference = "Stop"

$here = $PSScriptRoot
$repo = Split-Path -Parent $here

$py = $env:PYTHON
if (-not $py) {
    foreach ($candidate in @("python", "python3")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            & $cmd.Source -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { $py = $cmd.Source; break }
        }
    }
}
if (-not $py) {
    Write-Error "Python >= 3.12 not found (set `$env:PYTHON to the interpreter path)"
    exit 2
}

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONIOENCODING = "utf-8"

$dirs = @()
if ($Suite -in @("all", "smoke")) { $dirs += Join-Path $here "smoke" }
if ($Suite -in @("all", "integration")) { $dirs += Join-Path $here "integration" }

$passed = 0
$failed = @()
foreach ($dir in $dirs) {
    $tests = Get-ChildItem -Path $dir -Filter "test_*.py" | Sort-Object Name
    foreach ($test in $tests) {
        $name = "$(Split-Path -Leaf $dir)/$($test.Name)"
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        & $py $test.FullName --root $repo
        $code = $LASTEXITCODE
        $seconds = [int]$watch.Elapsed.TotalSeconds
        if ($code -eq 0) {
            $passed++
            Write-Host "ok   $name (${seconds}s)"
        } else {
            $failed += $name
            Write-Host "FAIL $name (${seconds}s)"
        }
    }
}

Write-Host ""
Write-Host "passed: $passed, failed: $($failed.Count)"
if ($failed.Count -gt 0) {
    $failed | ForEach-Object { Write-Host "  $_" }
    exit 1
}
exit 0
