$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 --version
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.12 no está instalado. Instálalo y vuelve a ejecutar este script."
    }
    & py -3.12 -m venv .venv
} else {
    $pythonVersion = & python --version 2>&1
    if ($pythonVersion -notmatch "^Python 3\.12\.") {
        throw "Se requiere Python 3.12. Instálalo o habilita el lanzador 'py'."
    }
    & python -m venv .venv
}

if ($LASTEXITCODE -ne 0) {
    throw "No se pudo crear el entorno virtual .venv."
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo actualizar pip dentro de .venv."
}
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron instalar las dependencias del proyecto."
}

Write-Host "Entorno listo. Arranca PhotoBridge con .\scripts\start.ps1"

