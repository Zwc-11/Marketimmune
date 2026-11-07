# The quiet-depth maker (hush@, marketimmune/paper/strategies.py) live on paper (no order is ever sent),
# beside the market-maker run (port 8767) and any other run, in its own window:
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_paper_hush.ps1
#   ... -Hours 168 -Port 8768          # the defaults
# Then open http://127.0.0.1:8768/#/paper. Ctrl+C stops it; the current segment is written first.
# Settings and rules: docs\preregistration\paper-hush-20261107.md (Addendum A). The registered test is the
# replay of the market-maker run's recordings; this run is the same quoters live, for watching.
# The wallet scores start warm: on the first start the market-maker run's state is copied in.
# The clock is corrected from Coinbase's timestamps, as in the other runs.
param(
    [double]$Hours = 168,
    [int]$Port = 8768,
    [string]$Out = "",
    [string]$WarmFrom = ""
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$PaperDir = Split-Path -Parent (Get-Location).Path  # data\paper, beside this app folder
if (-not $Out) { $Out = Join-Path $PaperDir "live-hush" }
if (-not $WarmFrom) { $WarmFrom = Join-Path $PaperDir "live-mm\state" }
$Candidates = @($env:PYTHON, ".\.venv\Scripts\python.exe", "..\..\..\.venv\Scripts\python.exe") | Where-Object { $_ -and (Test-Path $_) }
$Python = if ($Candidates) { @($Candidates)[0] } else { "python" }
# find_spec prints nothing, so Windows PowerShell 5.1 does not turn a traceback into a stopping error
& $Python -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('websockets') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install "websockets>=15"
    if ($LASTEXITCODE -ne 0) { throw "pip could not install websockets into $Python" }
}
if (-not (Test-Path "frontend\dist\index.html")) { throw "frontend\dist is missing: copy it from ..\app\frontend\dist" }

$State = Join-Path $Out "state"
if (-not (Test-Path $State) -and (Test-Path (Join-Path $WarmFrom "wallets.json"))) {
    New-Item -ItemType Directory -Force -Path $State | Out-Null
    Copy-Item -Path (Join-Path $WarmFrom "*") -Destination $State -Recurse
    Write-Host "Warm start: wallet scores and coin models copied from $WarmFrom"
}

$Registered = "hush@d=3/quiet=5/inf=0.665/tol=0.3"
$Strategies = @(
    "hush@d=3/quiet=5/inf=0.665/tol=0.3", "hush@d=3/quiet=0/tol=0.3",
    "hush@d=4/quiet=5/tol=0.3", "hush@d=3/quiet=5/tol=0.3",
    "zgap@0.05"
) -join ","

Write-Host "Live view: http://127.0.0.1:$Port/#/paper   output: $Out"
& $Python -m marketimmune.cli.paper_trade --out $Out --hours $Hours --segment-hours 2 --serve $Port --web frontend\dist `
    --strategies $Strategies --registered $Registered --clock coinbase --quote-usd 250 --max-quotes 4 --budget-usd 5000
