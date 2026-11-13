param(
    [ValidateSet('backend', 'frontend')]
    [string]$Service = 'backend'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if ($Service -eq 'backend') {
        & "$projectRoot/.venv/Scripts/python.exe" -m uvicorn road_safety.api:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend
    } else {
        Push-Location "$projectRoot/frontend"
        try { & npm.cmd run dev } finally { Pop-Location }
    }
    if ($LASTEXITCODE -ne 0) { throw "$Service exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
