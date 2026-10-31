@echo off
rem CUDA preflight for any NVIDIA GPU, and with the arguments below the one-mixture real inference.
rem   Overlap-Preflight.cmd                                  -> checks only
rem   Overlap-Preflight.cmd --enrollment e.wav --mixture m.wav --out minimal-out
if exist "%~dp0product\tools\windows_worker.py" (cd /d "%~dp0") else cd /d "%~dp0..\.."
call "%~dp0focus_env.cmd"
if errorlevel 1 (
  pause
  exit /b 1
)
if "%~1"=="" (
  "%FOCUS_PY%" product\tools\overlap_minimal_infer.py --candidate wesep_bsrnn --out preflight-out --preflight-only
) else (
  "%FOCUS_PY%" product\tools\overlap_minimal_infer.py --candidate wesep_bsrnn %*
)
pause
