# The tuned strategies at a $5,000 budget, live on paper (no order is ever sent), beside the
# 24-hour run (which keeps port 8765 and its own window):
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_paper_tuned.ps1
#   ... -Hours 336 -Port 8766          # the defaults
# Then open http://127.0.0.1:8766/#/paper. Ctrl+C stops it; the current segment is written first.
# Settings from eval/paper/tune_20261106.md; rules: docs\preregistration\paper-tuned-5k-20261106.md.
# The clock is corrected from Coinbase's timestamps (this PC's ran 223-345 ms fast on 2026-11-06).
param(
    [double]$Hours = 336,
    [int]$Port = 8766,
    [string]$Out = "data\paper\live-tuned"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$Candidates = @($env:PYTHON, ".\.venv\Scripts\python.exe", "..\..\..\.venv\Scripts\python.exe") | Where-Object { $_ -and (Test-Path $_) }
$Python = if ($Candidates) { @($Candidates)[0] } else { "python" }
# find_spec prints nothing, so Windows PowerShell 5.1 does not turn a traceback into a stopping error
& $Python -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('websockets') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install "websockets>=15"
    if ($LASTEXITCODE -ne 0) { throw "pip could not install websockets into $Python" }
}
# orjson is optional (faster parsing); a new Python may have no wheel for it yet
& $Python -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('orjson') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install --only-binary=:all: "orjson>=3.10"
    if ($LASTEXITCODE -ne 0) { Write-Host "orjson has no wheel for this Python: using the standard json module" }
}
if (-not (Test-Path "frontend\dist\index.html")) { throw "frontend\dist is missing: run 'npm run build' in frontend\ first" }
if (-not $Out) { $Out = "data\paper\live-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmm") }

$Registered = "improve+gap@0.05,zgap@0.05,gap@0.1"
$Strategies = @(
    "improve+gap@0.05", "zgap@0.05", "gap@0.1",
    "hawkes@1.25", "kelly@5", "model@0.25", "taker@25",
    "touch", "improve", "improve+gap@0.25", "gap@0.25", "zgap@0.25"
) -join ","

Write-Host "Live view: http://127.0.0.1:$Port/#/paper   output: $Out"
& $Python -m marketimmune.cli.paper_trade --out $Out --hours $Hours --segment-hours 2 --serve $Port --web frontend\dist `
    --strategies $Strategies --registered $Registered --clock coinbase --quote-usd 250 --max-quotes 4 --budget-usd 5000
