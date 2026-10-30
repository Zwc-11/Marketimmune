# Windows twin of the Makefile: .\make.ps1 <target>
param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "lint", "typecheck", "test", "coverage", "rust-test", "bench", "frontend-test", "frontend-build", "server", "ci")]
    [string]$Target = "ci"
)

$ErrorActionPreference = "Stop"
$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

function Run([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Target) {
    "install" { Run $Python @("-m", "pip", "install", "-e", ".[training,server,aws,fast,dev]") }
    "lint" { Run $Python @("-m", "ruff", "check", "."); Run $Python @("scripts/check_line_limit.py") }
    "typecheck" { Run $Python @("scripts/typecheck.py") }
    "test" { Run $Python @("-m", "pytest") }
    "coverage" { Run $Python @("-m", "coverage", "run", "-m", "pytest"); Run $Python @("-m", "coverage", "report") }
    "rust-test" { Run "cargo" @("test", "--workspace", "--release") }
    "bench" { Run $Python @("eval/pipeline_speed/bench.py", "--out", "eval/pipeline_speed/results.json"); Run "cargo" @("bench", "-p", "hl-replay", "--bench", "replay") }
    "frontend-test" { Run "npm" @("--prefix", "frontend", "run", "typecheck"); Run "npm" @("--prefix", "frontend", "test") }
    "frontend-build" { Run "npm" @("--prefix", "frontend", "run", "build:server") }
    "server" { Run $Python @("server/manage.py", "migrate"); Run $Python @("server/manage.py", "runserver") }
    "ci" {
        foreach ($t in @("lint", "typecheck", "coverage", "rust-test", "frontend-test")) { & $PSCommandPath $t }
    }
}
