param([switch]$Offline)
$ErrorActionPreference = 'Stop'
if ($Offline) { $env:TERM_AGENT_OFFLINE = '1' }
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .venv/Scripts/python.exe)) { throw 'Run scripts/setup.ps1 first.' }
if (-not (Test-Path frontend/dist/index.html)) { throw 'Frontend missing. Run scripts/setup.ps1 first.' }
& .venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
