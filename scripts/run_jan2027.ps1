# The pre-registered January 2027 confirmation (BTC/ETH/SOL), end to end: build Gold from node
# fills (Nov 1 2026 to Jan 31 2027, day stage then wallet scores), train every rung at 10 s and 1 s
# on each January day, compare rungs, and score J1-J4 with score_a1 (unchanged), once per horizon.
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_jan2027.ps1
#   ... -SkipBuild                 # Gold is already built
#   ... -Coins SOL                 # one coin; the verdicts are scored once all three are done
#   ... -Exclude 20270115          # dates with no Binance file or a failed leakage check
# Rules: docs\preregistration\jan-2027-confirmation.md. It must be committed, unchanged, first.
# Needs: data\bronze\node_fills, data\bronze\hyperliquid\candles (pull_candles), Binance aggTrades.
param(
    [string]$Coins = "BTC,ETH,SOL",
    [string]$Exclude = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$Python = if ($env:PYTHON) { $env:PYTHON } else { ".\.venv\Scripts\python.exe" }
$Prereg = "docs\preregistration\jan-2027-confirmation.md"
if (-not (git log --oneline -1 -- $Prereg)) { throw "$Prereg is not committed: commit it before any January 2027 model is trained" }
git diff --quiet HEAD -- $Prereg
if ($LASTEXITCODE -ne 0) { throw "$Prereg has uncommitted changes: commit them first (or record them under Deviations)" }

function Run([string[]]$Arguments) {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$Skip = if ($Exclude) { $Exclude.Split(",") } else { @() }
function Dates([string]$First, [string]$Last) {  # every date from First to Last, minus -Exclude
    $d = [datetime]::ParseExact($First, "yyyyMMdd", $null)
    $end = [datetime]::ParseExact($Last, "yyyyMMdd", $null)
    $out = @()
    while ($d -le $end) {
        $s = $d.ToString("yyyyMMdd")
        if ($Skip -notcontains $s) { $out += $s }
        $d = $d.AddDays(1)
    }
    return ($out -join ",")
}

$FirstGold = "20261101"
$Gold = Dates $FirstGold "20270131"
$Tested = Dates "20270101" "20270131"
$Rungs = @("l0_trade", "l1_trade", "l2_trade", "l3_fee", "l3_fee_placebo")
$Pairs = @(  # challenger, base
    @("l1_trade", "l0_trade"),
    @("l2_trade", "l1_trade"),
    @("l3_fee", "l2_trade"),
    @("l3_fee_placebo", "l2_trade")
)
$Horizons = @("10s", "1s")
$Eval = "eval\jan2027"

foreach ($Coin in $Coins.Split(",")) {
    $Name = "a1_$($Coin.ToLower())"
    if (-not $SkipBuild) {
        Run @("-m", "marketimmune.cli.build_node_gold", "--coin", $Coin, "--dates", $Gold, "--skip-existing")
        Run @("-m", "marketimmune.cli.build_node_gold", "--coin", $Coin, "--dates", $Gold, "--stage", "wallet")
    }
    foreach ($h in $Horizons) {
        $Dir = "$Eval\h$h"
        New-Item -ItemType Directory -Force -Path "$Dir\confirmation" | Out-Null
        foreach ($r in $Rungs) {  # one 8-day panel per tested day; resumes where it stopped
            foreach ($m in @("classifier", "quantile")) {
                Run @("-m", "marketimmune.cli.a1_ladder", "--coin", $Coin, "--rung", $r, "--model", $m, "--horizon", $h, "--first-gold", $FirstGold, "--out", $Dir, "--models-dir", "data\models\jan2027_h$h", "--test-dates", $Tested)
            }
        }
        foreach ($p in $Pairs) {
            $c, $b = $p
            Run @("-m", "marketimmune.cli.compare_rungs", "--dates", $Tested, "--base", "$Dir\${Name}_$b.oof.parquet", "--challenger", "$Dir\${Name}_$c.oof.parquet", "--out", "$Dir\confirmation\${Name}_${c}_vs_${Name}_$b.json")
            Run @("-m", "marketimmune.cli.compare_rungs", "--dates", $Tested, "--loss", "pinball", "--tau", "0.1", "--base", "$Dir\q_${Name}_$b.oof.parquet", "--challenger", "$Dir\q_${Name}_$c.oof.parquet", "--out", "$Dir\confirmation\q_${Name}_${c}_vs_q_${Name}_$b.json")
        }
        Run (@("-m", "marketimmune.cli.mcs_rungs", "--dates", $Tested, "--out", "$Dir\confirmation\mcs_brier_$Name.json") + ($Rungs | ForEach-Object { "$Dir\${Name}_$_.oof.parquet" }))
        Run (@("-m", "marketimmune.cli.mcs_rungs", "--dates", $Tested, "--loss", "pinball", "--tau", "0.1", "--out", "$Dir\confirmation\mcs_pinball_q10_$Name.json") + ($Rungs | ForEach-Object { "$Dir\q_${Name}_$_.oof.parquet" }))
    }
}
# Score each horizon once all three coins have its comparisons (coins may run in separate calls)
foreach ($h in $Horizons) {
    $Dir = "$Eval\h$h"
    $Done = @("btc", "eth", "sol") | Where-Object { Test-Path "$Dir\confirmation\q_a1_${_}_l3_fee_placebo_vs_q_a1_${_}_l2_trade.json" }
    if ($Done.Count -eq 3) {
        Run @("-m", "marketimmune.cli.score_a1", "--dir", "$Dir\confirmation", "--out", "$Dir\verdicts.json")
    }
}
