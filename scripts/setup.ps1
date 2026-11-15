param([string]$Python = 'python', [string]$Pnpm = '')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) { throw 'Install Python 3.12+ from python.org and enable Add Python to PATH.' }
& $Python -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12 or later is required"'
if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.12 or later.' }
if (-not (Test-Path .venv/Scripts/python.exe)) { & $Python -m venv .venv; if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' } }
& .venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22.12+ from nodejs.org.' }
Push-Location frontend
try {
    if ($Pnpm) { & $Pnpm install --frozen-lockfile --ignore-scripts }
    else { npx.cmd --yes pnpm@11.25.0 install --frozen-lockfile --ignore-scripts }
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    node node_modules/vite/bin/vite.js build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Host 'Setup complete. Run scripts/start.ps1 and open http://127.0.0.1:8765'
