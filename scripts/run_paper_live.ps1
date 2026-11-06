# Live paper trading on Hyperliquid with the web terminal, on this machine (no order is ever sent):
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_paper_live.ps1
#   ... -Hours 24 -Port 8765          # the defaults
# Then open http://127.0.0.1:8765/#/paper. Ctrl+C stops it; the current segment is written first.
# Rules for the 24-hour run: docs\preregistration\paper-confirmation-20261106.md.
param(
    [double]$Hours = 24,
    [int]$Port = 8765,
    [string]$Out = ""
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$Candidates = @($env:PYTHON, ".\.venv\Scripts\python.exe", "..\..\..\.venv\Scripts\python.exe") | Where-Object { $_ -and (Test-Path $_) }
$Python = if ($Candidates) { @($Candidates)[0] } else { "python" }
# find_spec prints nothing, so Windows PowerShell 5.1 does not turn a traceback into a stopping error
& $Python -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('websockets') and u.find_spec('orjson') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install "websockets>=15" "orjson>=3.10"
    if ($LASTEXITCODE -ne 0) { throw "pip could not install websockets and orjson into $Python" }
}
if (-not (Test-Path "frontend\dist\index.html")) { throw "frontend\dist is missing: run 'npm run build' in frontend\ first" }
if (-not $Out) { $Out = "data\paper\live-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmm") }

$Strategies = @(
    "touch", "gap@1", "gap@2", "model@0.5", "model@1", "improve", "improve+gap@2", "taker@6", "taker@10",
    "gap@0.25", "gap@0.5", "improve+gap@0.25", "improve+gap@0.5",
    "zgap@0.25", "zgap@0.5", "hawkes@2", "hawkes@3", "kelly@0.5", "kelly@1", "reservation@1", "reservation@3"
) -join ","

Write-Host "Live view: http://127.0.0.1:$Port/#/paper   output: $Out"
& $Python -m marketimmune.cli.paper_trade --out $Out --hours $Hours --segment-hours 2 --serve $Port --web frontend\dist --strategies $Strategies
