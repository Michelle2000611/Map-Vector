$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot 'frontend'
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'npm.cmd was not found. Install Node.js and reopen the terminal.'
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendPath 'node_modules/vite/bin/vite.js'))) {
    throw 'Frontend dependencies are missing. Run scripts/install.ps1 first.'
}
$env:npm_config_cache = Join-Path $projectRoot '.venv/npm-cache'
Write-Host 'Map-Vector frontend: http://127.0.0.1:5175 (backend required on port 8840)' -ForegroundColor Cyan
& npm.cmd --prefix $frontendPath run dev
exit $LASTEXITCODE
