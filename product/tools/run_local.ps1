param(
    [ValidateSet('api', 'web', 'check')]
    [string]$Service = 'api'
)

$ErrorActionPreference = 'Stop'
$focusRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $focusRoot
. (Join-Path $PSScriptRoot 'local_paths.ps1')

if ($Service -eq 'web') {
    $env:VITE_API_BASE_URL = '/api'
    $env:VITE_DEV_MOCK_API = '0'
    $env:VITE_LIVE_ENABLED = '0'
    & npm.cmd --prefix product/apps/web run dev -- --host 127.0.0.1 --port 5173
    exit $LASTEXITCODE
}

$focusPython = Join-Path $focusRoot '.venv-ml\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $focusPython)) {
    throw 'Missing project-local GPU environment: .venv-ml'
}
$env:PYTHONPATH = "$focusRoot\product;$focusRoot\product\packages\ml"
$env:FOCUS_MODEL_SOURCE = Join-Path $focusRoot 'model-assets\Dolphin-runtime'
$env:FOCUS_MODEL_CACHE = Join-Path $focusRoot 'model-assets\cache\hf'
$env:HF_HOME = $env:FOCUS_MODEL_CACHE
$env:TORCH_HOME = Join-Path $focusRoot 'model-assets\cache\torch'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:KERAS_HOME = Join-Path $focusRoot 'model-assets\cache\keras'
$env:DEEPFACE_HOME = Join-Path $focusRoot 'model-assets\cache\deepface'
$env:TF_CPP_MIN_LOG_LEVEL = '2'
$env:OMP_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
$env:FOCUS_INFERENCE_MODE = 'local'
$env:FOCUS_LIVE_ENABLED = '0'
$env:FOCUS_API_UI_ORIGINS = 'http://127.0.0.1:5173,http://localhost:5173'
$env:FOCUS_API_STORAGE_ROOT = Join-Path $focusRoot 'runtime\local-session\api'

if ($Service -eq 'check') {
    @'
import torch
from focus_ml.config import AdapterConfig
from focus_ml.runtime import LocalEngine
print('PyTorch:', torch.__version__, 'CUDA:', torch.cuda.is_available(), flush=True)
engine = LocalEngine(AdapterConfig.from_env())
try:
    engine.initialize()
except Exception as exc:
    print(type(exc).__name__, str(exc), getattr(exc, 'detail', ''), flush=True)
    raise
print('Models loaded on', engine.models.device, flush=True)
'@ | & $focusPython -
    exit $LASTEXITCODE
}

Write-Host 'FOCUS API: http://127.0.0.1:8000; real local GPU; live mode disabled.'
Write-Host 'The dispatcher loads models on the first request. Stop with Ctrl+C.'
& $focusPython -m uvicorn services.api.focus_api.main:app --host 127.0.0.1 --port 8000 --workers 1
exit $LASTEXITCODE
