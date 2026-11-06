# The market maker (marketimmune/paper/mm.py) live on paper (no order is ever sent), beside the
# 24-hour and tuned runs (ports 8765 and 8766, their own windows):
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_paper_mm.ps1
#   ... -Hours 168 -Port 8767          # the defaults
# Then open http://127.0.0.1:8767/#/paper. Ctrl+C stops it; the current segment is written first.
# Settings and rules: docs\preregistration\paper-mm-20261106.md; replays: eval\paper\mm_20261106.md.
# The clock is corrected from Coinbase's timestamps, as in the tuned run.
param(
    [double]$Hours = 168,
    [int]$Port = 8767,
    [string]$Out = "data\paper\live-mm"
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
& $Python -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('orjson') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install --only-binary=:all: "orjson>=3.10"
    if ($LASTEXITCODE -ne 0) { Write-Host "orjson has no wheel for this Python: using the standard json module" }
}
if (-not (Test-Path "frontend\dist\index.html")) { throw "frontend\dist is missing: run 'npm run build' in frontend\ first" }

$Registered = "mm@h=2/skew=6"
$Strategies = @(
    "mm@h=2/skew=6",
    "mm@1.5", "mm@3", "mm@h=1.5/stop=0/dd=0/net=0/burst=0",
    "zgap@0.05", "touch"
) -join ","

Write-Host "Live view: http://127.0.0.1:$Port/#/paper   output: $Out"
& $Python -m marketimmune.cli.paper_trade --out $Out --hours $Hours --segment-hours 2 --serve $Port --web frontend\dist `
    --strategies $Strategies --registered $Registered --clock coinbase --quote-usd 250 --max-quotes 4 --budget-usd 5000
