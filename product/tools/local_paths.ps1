# Per-process cache/temp paths. Never changes machine/user PATH or global config.
$focusProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ([System.IO.Path]::GetPathRoot($focusProjectRoot) -ne 'D:\') {
    throw 'This local setup requires the project and all download caches on D:.'
}
$focusLocalRuntime = Join-Path $focusProjectRoot 'runtime\local-session'
$env:UV_CACHE_DIR = Join-Path $focusLocalRuntime 'cache\uv'
$env:PIP_CACHE_DIR = Join-Path $focusLocalRuntime 'cache\pip'
$env:npm_config_cache = Join-Path $focusLocalRuntime 'cache\npm'
$env:TEMP = Join-Path $focusLocalRuntime 'temp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:XDG_CACHE_HOME = Join-Path $focusLocalRuntime 'cache'
$env:HF_HOME = Join-Path $focusProjectRoot 'model-assets\cache\hf'
$env:FOCUS_MODEL_SOURCE = Join-Path $focusProjectRoot 'model-assets\Dolphin-runtime'
$env:FOCUS_MODEL_CACHE = $env:HF_HOME
$env:HF_HUB_CACHE = Join-Path $env:HF_HOME 'hub'
$env:HF_ASSETS_CACHE = Join-Path $env:HF_HOME 'assets'
$env:TORCH_HOME = Join-Path $focusProjectRoot 'model-assets\cache\torch'
$env:KERAS_HOME = Join-Path $focusProjectRoot 'model-assets\cache\keras'
$env:DEEPFACE_HOME = Join-Path $focusProjectRoot 'model-assets\cache\deepface'
$env:DEEPFACE_BACKEND_ENGINE = 'pytorch'
$env:OMP_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
$env:NUMBA_CACHE_DIR = Join-Path $focusLocalRuntime 'cache\numba'
$env:CUDA_CACHE_PATH = Join-Path $focusLocalRuntime 'cache\cuda'
$env:TORCHINDUCTOR_CACHE_DIR = Join-Path $focusLocalRuntime 'cache\torchinductor'
$env:MPLCONFIGDIR = Join-Path $focusLocalRuntime 'cache\matplotlib'
$focusBin = Join-Path $focusLocalRuntime 'bin'
if (($env:PATH -split ';') -notcontains $focusBin) {
    $env:PATH = "$focusBin;$env:PATH"
}
foreach ($focusDirectory in @(
    $env:UV_CACHE_DIR, $env:PIP_CACHE_DIR, $env:npm_config_cache,
    $env:TEMP, $env:HF_HOME, $env:TORCH_HOME, $env:KERAS_HOME,
    $env:DEEPFACE_HOME, $env:NUMBA_CACHE_DIR, $env:CUDA_CACHE_PATH,
    $env:TORCHINDUCTOR_CACHE_DIR, $env:MPLCONFIGDIR, $focusBin
)) {
    New-Item -ItemType Directory -Path $focusDirectory -Force | Out-Null
}
