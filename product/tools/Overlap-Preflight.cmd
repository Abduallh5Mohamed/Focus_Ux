@echo off
rem Windows CUDA preflight (and, with the arguments below, the one-mixture real inference).
rem   Overlap-Preflight.cmd                                  -> checks only
rem   Overlap-Preflight.cmd --enrollment e.wav --mixture m.wav --out minimal-out
if exist "%~dp0product\tools\windows_worker.py" (cd /d "%~dp0") else cd /d "%~dp0..\.."
if not exist "A:\focus\.venv\Scripts\python.exe" (
  echo Original Python was not found at A:\focus\.venv\Scripts\python.exe.
  pause
  exit /b 1
)
if "%~1"=="" (
  "A:\focus\.venv\Scripts\python.exe" product\tools\overlap_minimal_infer.py --candidate wesep_bsrnn --out preflight-out --preflight-only
) else (
  "A:\focus\.venv\Scripts\python.exe" product\tools\overlap_minimal_infer.py --candidate wesep_bsrnn %*
)
pause
