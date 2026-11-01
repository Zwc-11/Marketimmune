# The pre-registered A1 ladder (priority fees, BTC/ETH/SOL, Apr 25 to Oct 31 2026), end to end:
# build Gold from node fills (day stage, then wallet scores), train the classifier and quantile
# rungs on the tested days, compare rungs per period, and score A1-A4 on the confirmation months.
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_a1.ps1
#   ... -SkipBuild                 # Gold is already built
#   ... -Coins SOL                 # one coin; the verdicts are scored once all three are done
# Rules: docs\preregistration\a1-speed-bids-2026.md. It must be committed, unchanged, first.
# Needs: data\bronze\node_fills, data\bronze\hyperliquid\candles (pull_candles), Binance aggTrades.
param(
    [string]$Coins = "BTC,ETH,SOL",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$Python = if ($env:PYTHON) { $env:PYTHON } else { ".\.venv\Scripts\python.exe" }
$Prereg = "docs\preregistration\a1-speed-bids-2026.md"
if (-not (git log --oneline -1 -- $Prereg)) { throw "$Prereg is not committed: commit it before any 2026 model is trained" }
git diff --quiet HEAD -- $Prereg
if ($LASTEXITCODE -ne 0) { throw "$Prereg has uncommitted changes: commit them first (or record them under Deviations)" }

function Run([string[]]$Arguments) {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$Gold = "20260425..20261027,20261029..20261031"  # 2026-10-28 has no Binance file
$Discovery = "20260506,20260513,20260520,20260527,20260603,20260610,20260617,20260624,20260701,20260708,20260715,20260722,20260729,20260805,20260812,20260819,20260826"
$Confirmation = "20260901..20261027,20261029..20261031"
$Rungs = @("l0_trade", "l1_trade", "l2_trade", "l3_fee", "l3_fee_placebo")
$Pairs = @(  # challenger, base
    @("l1_trade", "l0_trade"),
    @("l2_trade", "l1_trade"),
    @("l3_fee", "l2_trade"),
    @("l3_fee_placebo", "l2_trade")
)
$Eval = "eval\a1"
New-Item -ItemType Directory -Force -Path $Eval, "$Eval\discovery", "$Eval\confirmation", "data\models\a1" | Out-Null

foreach ($Coin in $Coins.Split(",")) {
    $Name = "a1_$($Coin.ToLower())"
    if (-not $SkipBuild) {
        Run @("-m", "marketimmune.cli.build_node_gold", "--coin", $Coin, "--dates", $Gold, "--skip-existing")
        Run @("-m", "marketimmune.cli.build_node_gold", "--coin", $Coin, "--dates", $Gold, "--stage", "wallet")
    }
    foreach ($r in $Rungs) {  # one 8-day panel per tested day; resumes where it stopped
        Run @("-m", "marketimmune.cli.a1_ladder", "--coin", $Coin, "--rung", $r, "--model", "classifier", "--test-dates", "$Discovery,$Confirmation")
        Run @("-m", "marketimmune.cli.a1_ladder", "--coin", $Coin, "--rung", $r, "--model", "quantile", "--test-dates", "$Discovery,$Confirmation")
    }
    foreach ($Period in @(@("discovery", $Discovery), @("confirmation", $Confirmation))) {
        $Dir, $Dates = $Period
        foreach ($p in $Pairs) {
            $c, $b = $p
            Run @("-m", "marketimmune.cli.compare_rungs", "--dates", $Dates, "--base", "$Eval\${Name}_$b.oof.parquet", "--challenger", "$Eval\${Name}_$c.oof.parquet", "--out", "$Eval\$Dir\${Name}_${c}_vs_${Name}_$b.json")
            Run @("-m", "marketimmune.cli.compare_rungs", "--dates", $Dates, "--loss", "pinball", "--tau", "0.1", "--base", "$Eval\q_${Name}_$b.oof.parquet", "--challenger", "$Eval\q_${Name}_$c.oof.parquet", "--out", "$Eval\$Dir\q_${Name}_${c}_vs_q_${Name}_$b.json")
        }
        Run (@("-m", "marketimmune.cli.mcs_rungs", "--dates", $Dates, "--out", "$Eval\$Dir\mcs_brier_$Name.json") + ($Rungs | ForEach-Object { "$Eval\${Name}_$_.oof.parquet" }))
        Run (@("-m", "marketimmune.cli.mcs_rungs", "--dates", $Dates, "--loss", "pinball", "--tau", "0.1", "--out", "$Eval\$Dir\mcs_pinball_q10_$Name.json") + ($Rungs | ForEach-Object { "$Eval\q_${Name}_$_.oof.parquet" }))
    }
}
# Score once all three coins have their confirmation comparisons (coins may run in separate calls)
$Done = @("btc", "eth", "sol") | Where-Object { Test-Path "$Eval\confirmation\q_a1_${_}_l3_fee_vs_q_a1_${_}_l2_trade.json" }
if ($Done.Count -eq 3) {
    Run @("-m", "marketimmune.cli.score_a1", "--dir", "$Eval\confirmation", "--out", "$Eval\a1_verdicts.json")
    Run @("-m", "marketimmune.cli.score_a1", "--dir", "$Eval\discovery", "--out", "$Eval\a1_discovery_exploratory.json")
}
