# Run from a separate trial checkout; never installs into the original ML Python.
param([switch]$Live)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Run uv sync --locked --python 3.12 --no-python-downloads in this trial checkout first."
}
Get-Command ffmpeg -ErrorAction Stop | Out-Null
Get-Command ffprobe -ErrorAction Stop | Out-Null
if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA is required for private trial storage." }
$root = Join-Path $env:LOCALAPPDATA "FocusLocalTrial"
New-Item -ItemType Directory -Force -Path $root | Out-Null
# Exclusive creation preserves the key across restarts without printing it.
$env:FOCUS_LOCAL_TRIAL_ROOT = $root
$initKey = @'
import os
import secrets
from pathlib import Path
p = Path(os.environ['FOCUS_LOCAL_TRIAL_ROOT']) / 'worker-token'
try:
    with p.open('x') as f:
        f.write(secrets.token_hex(32))
except FileExistsError:
    pass
'@
& $python -c $initKey
if ($LASTEXITCODE -ne 0) { throw "Could not initialize the local worker credential." }
$env:FOCUS_WORKER_TOKEN = (Get-Content -Raw (Join-Path $root "worker-token")).Trim()
if ($env:FOCUS_WORKER_TOKEN.Length -lt 32) { throw "Local worker credential is invalid." }
$env:FOCUS_API_STORAGE_ROOT = Join-Path $root "api"
$env:FOCUS_API_DB_PATH = Join-Path $env:FOCUS_API_STORAGE_ROOT "focus.sqlite3"
$env:FOCUS_API_LOCK_PATH = Join-Path $env:FOCUS_API_STORAGE_ROOT "dispatcher.lock"
$env:FOCUS_API_PUBLIC_BASE_URL = ""
$env:FOCUS_API_UI_ORIGINS = "http://127.0.0.1:5000"
$env:FOCUS_INFERENCE_MODE = "remote"
$env:FOCUS_LIVE_ENABLED = if ($Live) { "1" } else { "0" }
$env:PYTHONPATH = "$(Get-Location)\product;$(Get-Location)\product\packages\ml"
Write-Host "Local API: 127.0.0.1:8000; private storage: LOCALAPPDATA\FocusLocalTrial"
Write-Host "Real GPU worker required. Stop with Ctrl+C; do not use --reload or multiple workers."
try {
    & $python -m uvicorn services.api.focus_api.main:app --host 127.0.0.1 --port 8000 --workers 1
    $apiExitCode = $LASTEXITCODE
} finally {
    Remove-Item Env:FOCUS_WORKER_TOKEN -ErrorAction SilentlyContinue
}
exit $apiExitCode
