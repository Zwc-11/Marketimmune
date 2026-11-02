# ETH in the block simulator, December 2025: the SOL pipeline of docs\research\block-simulator.md.
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_eth_sim.ps1
#   ... -SkipBuild        # the near-touch L4 events (silver\hyperliquid\mbo\ETH) already exist
# 1. build_albers_silver --mbo replays the month again to write the near-touch L4 events (Silver
#    L2 and order events come out byte-identical, so the ETH ladder's Gold is unaffected).
# 2. quote_signals trains the quote-time S2/S3 models on ETH Gold.
# 3. simulate_quotes runs S1, the stale-quote rule, S2 and S3 against the rebuilt book.
# Run it after scripts\run_a1.ps1 has finished: both are CPU-bound.
param([switch]$SkipBuild)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$Python = if ($env:PYTHON) { $env:PYTHON } else { ".\.venv\Scripts\python.exe" }

function Run([string[]]$Arguments) {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$Dates = "20251201..20251231"
if (-not $SkipBuild) {
    Run @("-m", "marketimmune.cli.build_albers_silver", "--coin", "ETH", "--dates", $Dates, "--mbo")
}
Run @("-m", "marketimmune.cli.quote_signals", "--coin", "ETH", "--dates", $Dates, "--report", "eval\quote_signals_eth.json")
Run @("-m", "marketimmune.cli.simulate_quotes", "--coin", "ETH", "--dates", $Dates, "--signals-dir", "data\gold\hyperliquid\quote_signals", "--out", "eval\sim_eth.json")
