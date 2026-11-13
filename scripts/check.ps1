$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = "$projectRoot/.venv/Scripts/python.exe"

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Check failed: $Program $Arguments" }
}

Push-Location $projectRoot
try {
    Invoke-Checked -Program $pythonPath -Arguments @('-m', 'ruff', 'check', 'backend', 'scripts')
    Invoke-Checked -Program $pythonPath -Arguments @('-m', 'ruff', 'format', '--check', 'backend', 'scripts')
    Invoke-Checked -Program $pythonPath -Arguments @('-m', 'mypy')
    Invoke-Checked -Program $pythonPath -Arguments @('-m', 'pytest', '-q')
    Invoke-Checked -Program $pythonPath -Arguments @('scripts/export_contracts.py', '--check')
    Push-Location "$projectRoot/frontend"
    try {
        Invoke-Checked -Program 'npm.cmd' -Arguments @('run', 'contracts:check')
        Invoke-Checked -Program 'npm.cmd' -Arguments @('run', 'lint')
        Invoke-Checked -Program 'npm.cmd' -Arguments @('run', 'typecheck')
        Invoke-Checked -Program 'npm.cmd' -Arguments @('test')
        Invoke-Checked -Program 'npm.cmd' -Arguments @('run', 'build')
    } finally { Pop-Location }
} finally { Pop-Location }
