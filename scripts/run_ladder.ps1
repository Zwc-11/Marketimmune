# The pre-registered December 2025 ladder for one coin, end to end: rebuild the month (stops on the
# data-quality gate), train the classifier and quantile rungs, compare rungs, MCS, policies,
# decomposition, forecaster report and the H1-H5 verdicts. Reports go to eval\<Name>\ (or -Out).
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_ladder.ps1 -Coin ETH -Name eth_dec
#   ... -Coin ETH -Name eth_dec -SkipRebuild                      # the lake is already built
#   ... -Coin SOL -Name sol_dec -Out eval\sol_dec_corrected -SkipRebuild   # the corrected SOL run
# Rules: docs\preregistration\<coin>-dec-2025-ladder.md. Commit that file before running this.
param(
    [Parameter(Mandatory = $true)][string]$Coin,
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Dates = "20251201..20251231",
    [string]$Out = "",
    [switch]$SkipRebuild
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$Python = if ($env:PYTHON) { $env:PYTHON } else { ".\.venv\Scripts\python.exe" }
$Eval = if ($Out) { $Out } else { "eval\$Name" }
$Rungs = @("l0_book", "l1_book", "l2_book", "l3a_book", "l3b_book", "l3_book", "l3a_placebo_book", "l3b_realised_book")
$McsRungs = @("l0_book", "l1_book", "l2_book", "l3a_book", "l3b_book", "l3_book", "l3a_placebo_book")
$Pairs = @(  # challenger, base
    @("l1_book", "l0_book"),
    @("l2_book", "l1_book"),
    @("l3a_book", "l2_book"),
    @("l3a_placebo_book", "l2_book"),
    @("l3b_book", "l2_book"),
    @("l3b_realised_book", "l2_book")
)

function Run([string[]]$Arguments) {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$Month = @("--coin", $Coin, "--dates", $Dates)
$Forced = "forced_$($Coin.ToLower()).json"
New-Item -ItemType Directory -Force -Path $Eval, "data\models\$Name" | Out-Null
if (-not $SkipRebuild) {
    Run (@("-m", "marketimmune.cli.run_albers_month") + $Month)
    Move-Item -Force "eval\$Forced" "$Eval\$Forced"  # the forecaster's month evaluation, written by the forecast stage
}

foreach ($r in $Rungs) {
    Run (@("-m", "marketimmune.cli.train") + $Month + @("--horizon", "1s", "--feature-set", $r, "--report", "$Eval\${Name}_$r.json", "--model-out", "data\models\$Name\${Name}_$r.cbm"))
    $Contrib = @()
    if ($r -eq "l3_book") { $Contrib = @("--contrib") }  # only the decomposition reads the contributions
    Run (@("-m", "marketimmune.cli.train_quantile") + $Month + @("--horizon", "1s", "--feature-set", $r, "--report", "$Eval\q_${Name}_$r.json") + $Contrib)
}

foreach ($p in $Pairs) {
    $c, $b = $p
    Run @("-m", "marketimmune.cli.compare_rungs", "--base", "$Eval\${Name}_$b.oof.parquet", "--challenger", "$Eval\${Name}_$c.oof.parquet")
    Run @("-m", "marketimmune.cli.compare_rungs", "--loss", "pinball", "--tau", "0.1", "--base", "$Eval\q_${Name}_$b.oof.parquet", "--challenger", "$Eval\q_${Name}_$c.oof.parquet")
}
Run (@("-m", "marketimmune.cli.mcs_rungs") + ($McsRungs | ForEach-Object { "$Eval\${Name}_$_.oof.parquet" }))
Run (@("-m", "marketimmune.cli.mcs_rungs", "--loss", "pinball", "--tau", "0.1") + ($McsRungs | ForEach-Object { "$Eval\q_${Name}_$_.oof.parquet" }))

$Policy = @("-m", "marketimmune.cli.simulate_policy") + $Month
Run ($Policy + @("--oof", "$Eval\q_${Name}_l2_book.oof.parquet", "--policy", "quantile", "--column", "q10", "--limit-bps", "2", "--out", "$Eval\policy_S2.json"))
Run ($Policy + @("--oof", "$Eval\q_${Name}_l3_book.oof.parquet", "--policy", "quantile", "--column", "q10", "--limit-bps", "2", "--out", "$Eval\policy_S3.json"))
Run ($Policy + @("--policy", "rule", "--column", "cex_gap_maker_bps", "--op", "le", "--threshold", "-2", "--cex-latency-ms", "500", "--out", "$Eval\policy_stale_500.json"))
Run @("-m", "marketimmune.cli.decompose", "--oof", "$Eval\q_${Name}_l3_book.oof.parquet")
Run (@("-m", "marketimmune.cli.decompose") + $Month + @("--out", "$Eval\decomposition_$($Coin.ToLower()).json"))
Run @("-m", "marketimmune.cli.score_ladder", "--runs", $Eval, "--name", $Name, "--out", "$Eval\ladder_verdicts.json")
