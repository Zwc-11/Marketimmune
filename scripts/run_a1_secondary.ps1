# A1 secondary analyses (docs\preregistration\a1-speed-bids-2026.md, "Secondary"), after run_a1.ps1:
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_a1_secondary.ps1
#   ... -WithHorizons      # also retrain every rung at 1 s and 60 s (long: about as much again as A1, twice)
# 1. Log loss, and pinball at tau 0.5 and 0.9, for A1-A4 and the placebo on the confirmation months,
#    from the 10 s runs' OOF predictions (eval\a1\secondary).
# 2. The lead-time curve (plan A.5 test 4): markout by blocks since a fee-paying taker hit the
#    same side (eval\a1\lead_time.json).
# 3. With -WithHorizons: the whole ladder at 1 s and 60 s (eval\a1\h1s, eval\a1\h60s), compared
#    with Brier and pinball at tau 0.1 like the primary.
# 4. The report tables again (eval\a1\a1_tables.md), which include whatever of this exists.
param([switch]$WithHorizons)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$Python = if ($env:PYTHON) { $env:PYTHON } else { ".\.venv\Scripts\python.exe" }

function Run([string[]]$Arguments) {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$Confirmation = "20260901..20261027,20261029..20261031"
$Discovery = "20260506,20260513,20260520,20260527,20260603,20260610,20260617,20260624,20260701,20260708,20260715,20260722,20260729,20260805,20260812,20260819,20260826"
$Rungs = @("l0_trade", "l1_trade", "l2_trade", "l3_fee", "l3_fee_placebo")
$Pairs = @(@("l1_trade", "l0_trade"), @("l2_trade", "l1_trade"), @("l3_fee", "l2_trade"), @("l3_fee_placebo", "l2_trade"))
$Losses = @(  # name, prefix, compare_rungs arguments
    @("log", "", @("--loss", "log")),
    @("pinball50", "q_", @("--loss", "pinball", "--tau", "0.5")),
    @("pinball90", "q_", @("--loss", "pinball", "--tau", "0.9"))
)
$Eval = "eval\a1"
New-Item -ItemType Directory -Force -Path "$Eval\secondary" | Out-Null

foreach ($Coin in @("btc", "eth", "sol")) {
    foreach ($p in $Pairs) {
        $c, $b = $p
        foreach ($l in $Losses) {
            $name, $prefix, $extra = $l
            $out = "$Eval\secondary\${prefix}a1_${Coin}_${c}_vs_${prefix}a1_${Coin}_$b.$name.json"
            if (Test-Path $out) { continue }
            Run (@("-m", "marketimmune.cli.compare_rungs", "--dates", $Confirmation, "--base", "$Eval\${prefix}a1_${Coin}_$b.oof.parquet", "--challenger", "$Eval\${prefix}a1_${Coin}_$c.oof.parquet", "--out", $out) + $extra)
        }
    }
}
Run @("-m", "marketimmune.cli.a1_lead_time", "--coins", "BTC,ETH,SOL", "--out", "$Eval\lead_time.json")

if ($WithHorizons) {
    foreach ($h in @("1s", "60s")) {
        $Dir = "$Eval\h$h"
        New-Item -ItemType Directory -Force -Path "$Dir\confirmation" | Out-Null
        foreach ($Coin in @("BTC", "ETH", "SOL")) {
            $Name = "a1_$($Coin.ToLower())"
            foreach ($r in $Rungs) {
                foreach ($m in @("classifier", "quantile")) {
                    Run @("-m", "marketimmune.cli.a1_ladder", "--coin", $Coin, "--rung", $r, "--model", $m, "--horizon", $h, "--out", $Dir, "--models-dir", "data\models\a1_h$h", "--test-dates", "$Discovery,$Confirmation")
                }
            }
            foreach ($p in $Pairs) {
                $c, $b = $p
                Run @("-m", "marketimmune.cli.compare_rungs", "--dates", $Confirmation, "--base", "$Dir\${Name}_$b.oof.parquet", "--challenger", "$Dir\${Name}_$c.oof.parquet", "--out", "$Dir\confirmation\${Name}_${c}_vs_${Name}_$b.json")
                Run @("-m", "marketimmune.cli.compare_rungs", "--dates", $Confirmation, "--loss", "pinball", "--tau", "0.1", "--base", "$Dir\q_${Name}_$b.oof.parquet", "--challenger", "$Dir\q_${Name}_$c.oof.parquet", "--out", "$Dir\confirmation\q_${Name}_${c}_vs_q_${Name}_$b.json")
            }
        }
        Run @("-m", "marketimmune.cli.score_a1", "--dir", "$Dir\confirmation", "--out", "$Dir\a1_secondary_scored.json")
    }
}
Run @("-m", "marketimmune.cli.a1_report", "--dir", $Eval, "--out", "$Eval\a1_tables.md")
