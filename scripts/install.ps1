$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    py -3.11 -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
$env:TEMP = Join-Path $projectRoot '.venv/temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
& $pythonPath -m pip install --cache-dir (Join-Path $projectRoot '.venv/pip-cache') -r (Join-Path $projectRoot 'backend/requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
& $pythonPath -m pip install --no-deps --cache-dir (Join-Path $projectRoot '.venv/pip-cache') -e (Join-Path $projectRoot 'backend')
if ($LASTEXITCODE -ne 0) { throw 'Map-Vector installation failed' }
npm --prefix (Join-Path $projectRoot 'frontend') ci --cache (Join-Path $projectRoot '.venv/npm-cache')
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
npm --prefix (Join-Path $projectRoot 'frontend') run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
