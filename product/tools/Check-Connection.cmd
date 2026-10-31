@echo off
rem Works from the worker ZIP (this file at the folder root) and from a full checkout (product\tools).
if exist "%~dp0product\tools\windows_worker.py" (cd /d "%~dp0") else cd /d "%~dp0..\.."
call "%~dp0focus_env.cmd"
if errorlevel 1 (
  pause
  exit /b 1
)
"%FOCUS_PY%" product\tools\windows_worker.py --check %*
pause
