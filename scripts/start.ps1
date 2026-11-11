$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PROJECT_ROOT = $projectRoot
$env:PYTHONUTF8 = '1'
& (Join-Path $projectRoot '.venv/Scripts/python.exe') -X utf8 -m mapvector
exit $LASTEXITCODE
