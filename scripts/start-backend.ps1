$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Project .venv is missing. Run scripts/install.ps1 first.'
}
$env:PROJECT_ROOT = $projectRoot
$env:PYTHONUTF8 = '1'
Write-Host 'Map-Vector backend: http://127.0.0.1:8840 (or MAPVECTOR_API_PORT)' -ForegroundColor Cyan
& $pythonPath -X utf8 -m mapvector
exit $LASTEXITCODE
