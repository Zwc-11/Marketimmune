# Market making on Hyperliquid's builder-deployed (HIP-3) markets in growth mode, live on paper (no order
# is ever sent), in its own window beside the other runs:
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_paper_hip3.ps1
#   ... -Hours 168 -Port 8769          # the defaults
# Then open http://127.0.0.1:8769/#/paper. Ctrl+C stops it; the current segment is written first.
# Why: on the nine majors every quoter's edge is below the 1.5 bp maker fee. Growth-mode HIP-3 markets
# (trade.xyz equities, indices, commodities) charge 0.3 bp maker / 0.9 bp taker at tier 0
# (docs.trade.xyz/perp-mechanics/fees). Their oracle (activeAssetCtx) is the price reference;
# BTC-USD on Coinbase is subscribed only to correct the receive clock.
# The raw recordings are the point: every strategy is replayed on them afterwards.
param(
    [double]$Hours = 168,
    [int]$Port = 8769,
    [string]$Out = "",
    [string]$WarmFrom = ""
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$PaperDir = Split-Path -Parent (Get-Location).Path  # data\paper, beside this app folder
if (-not $Out) { $Out = Join-Path $PaperDir "live-hip3" }
if (-not $WarmFrom) { $WarmFrom = Join-Path $PaperDir "live-mm\state" }
$Candidates = @($env:PYTHON, ".\.venv\Scripts\python.exe", "..\..\..\.venv\Scripts\python.exe") | Where-Object { $_ -and (Test-Path $_) }
$Python = if ($Candidates) { @($Candidates)[0] } else { "python" }
& $Python -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('websockets') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install "websockets>=15"
    if ($LASTEXITCODE -ne 0) { throw "pip could not install websockets into $Python" }
}
if (-not (Test-Path "frontend\dist\index.html")) { throw "frontend\dist is missing: copy it from ..\app\frontend\dist" }

# Wallet scores are shared across coins: start from the market-maker run's (coin models stay per coin)
$State = Join-Path $Out "state"
if (-not (Test-Path $State) -and (Test-Path (Join-Path $WarmFrom "wallets.json"))) {
    New-Item -ItemType Directory -Force -Path $State | Out-Null
    Copy-Item -Path (Join-Path $WarmFrom "wallets.json") -Destination $State
    Write-Host "Warm start: wallet scores copied from $WarmFrom"
}

$Coins = @(
    "xyz:XYZ100", "xyz:SP500", "xyz:BRENTOIL", "xyz:CL", "xyz:SILVER", "xyz:NATGAS", "xyz:JPY",
    "xyz:SNDK", "xyz:SOXL", "xyz:SKHX", "xyz:MU", "xyz:NVDA", "xyz:SPCX", "xyz:DRAM", "xyz:GOOGL",
    "xyz:SKHY", "xyz:INTC", "xyz:SMSN", "xyz:EWY", "xyz:KORU", "xyz:CRCL", "xyz:AMD", "xyz:MRVL",
    "xyz:AAPL", "xyz:TSLA", "xyz:MSFT", "xyz:META", "xyz:AMZN", "xyz:ANT", "io:SNDK", "io:NVDA", "io:ANTH"
) -join ","
$Strategies = @(
    "touch", "zgap@0.05", "mm@1.5",
    "hush@d=1/quiet=5/tol=0.3", "hush@d=3/quiet=5/inf=0.665/tol=0.3"
) -join ","

Write-Host "Live view: http://127.0.0.1:$Port/#/paper   output: $Out"
& $Python -m marketimmune.cli.paper_trade --out $Out --hours $Hours --segment-hours 2 --serve $Port --web frontend\dist `
    --coins $Coins --strategies $Strategies --clock coinbase --quote-usd 250 --max-quotes 4 --budget-usd 5000 `
    --maker-fee-bps 0.3 --taker-fee-bps 0.9
