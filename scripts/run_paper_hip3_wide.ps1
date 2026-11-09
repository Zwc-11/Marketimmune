# Deep passive quotes on the WIDE-SPREAD growth-mode HIP-3 markets, live on paper (no order is ever
# sent), in its own window beside the other runs:
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_paper_hip3_wide.ps1
#   ... -Hours 168 -Port 8770          # the defaults
# Then open http://127.0.0.1:8770/#/paper. Ctrl+C stops it; the current segment is written first.
# Compare the original 50-market selection and six strategies under the audited execution model.
# Fees remain the experiment's assumptions: 0.3 bp maker / 0.9 bp taker.
# Previous results require replay with the corrected engine before drawing strategy conclusions.
# The raw recordings are the point: they are the next selection and test data.
param(
    [double]$Hours = 168,
    [int]$Port = 8770,
    [string]$Out = "",
    [string]$WarmFrom = ""
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$PaperDir = Split-Path -Parent (Get-Location).Path  # data\paper, beside this app folder
if (-not $Out) { $Out = Join-Path $PaperDir ("live-hip3-audited-" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmss")) }
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
if ($WarmFrom -and -not (Test-Path $State) -and (Test-Path (Join-Path $WarmFrom "wallets.json"))) {
    New-Item -ItemType Directory -Force -Path $State | Out-Null
    Copy-Item -Path (Join-Path $WarmFrom "wallets.json") -Destination $State
    Write-Host "Warm start: wallet scores copied from $WarmFrom"
}

$Coins = @(
    "io:OAI", "io:ANTH", "io:NBIS", "io:EWY", "io:PRL", "io:NVDA", "io:CRCL",
    "xyz:NFLX", "xyz:LLY", "xyz:BABA", "xyz:USAR", "xyz:CRWV", "xyz:PALLADIUM", "xyz:KR200",
    "xyz:SOFTBANK", "xyz:JP225", "xyz:HYUNDAI", "xyz:KIOXIA", "xyz:EWJ", "xyz:LITE", "xyz:XLE",
    "xyz:CBRS", "xyz:EWZ", "xyz:ARM", "xyz:EWT", "xyz:ASML", "xyz:MINIMAX", "xyz:DELL",
    "xyz:IBM", "xyz:SMH", "xyz:BE", "xyz:ZHIPU", "xyz:QCOM", "xyz:AMAT", "xyz:GIGADEV",
    "xyz:KSTR", "xyz:CXMT", "xyz:KORU", "xyz:IREN", "xyz:NET", "xyz:AAOI", "xyz:MRNA",
    "xyz:SHEIN", "xyz:SNXX", "xyz:TLT", "xyz:ANT", "para:COHR", "para:IREN", "para:AAOI",
    "para:UNITREE"
) -join ","
$Strategies = @(
    "touch", "mm@8",
    "hush@d=6/quiet=0/tol=0.3", "hush@d=8/quiet=0/tol=0.3", "hush@d=10/quiet=0/tol=0.3", "hush@d=12/quiet=0/tol=0.3"
) -join ","

Write-Host "Live view: http://127.0.0.1:$Port/#/paper   output: $Out"
& $Python -m marketimmune.cli.paper_trade --out $Out --hours $Hours --segment-hours 2 --serve $Port --web frontend\dist `
    --coins $Coins --strategies $Strategies --clock coinbase --quote-usd 250 --max-quotes 4 --budget-usd 5000 `
    --maker-fee-bps 0.3 --taker-fee-bps 0.9
