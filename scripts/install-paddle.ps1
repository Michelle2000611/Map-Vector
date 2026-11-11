$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv-ocr-paddle/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    py -3.11 -m venv (Join-Path $projectRoot '.venv-ocr-paddle')
    if ($LASTEXITCODE -ne 0) { throw 'Paddle environment creation failed' }
}
$env:TEMP = Join-Path $projectRoot '.venv/temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
& $pythonPath -m pip install --cache-dir (Join-Path $projectRoot '.venv/pip-cache') -r (Join-Path $projectRoot 'backend/requirements-paddle.lock')
if ($LASTEXITCODE -ne 0) { throw 'Paddle dependency installation failed' }
& $pythonPath -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Paddle dependency verification failed' }
