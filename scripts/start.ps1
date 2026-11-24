$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "No existe .venv. Ejecuta primero .\scripts\setup.ps1"
}

& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1) {
    throw "Uvicorn terminó con un error (código $LASTEXITCODE)."
}
