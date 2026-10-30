@echo off
rem Works from the worker ZIP (this file at the folder root) and from a full checkout (product\tools).
if exist "%~dp0product\tools\windows_worker.py" (cd /d "%~dp0") else cd /d "%~dp0..\.."
if not exist "A:\focus\.venv\Scripts\python.exe" (
  echo Original Python was not found at A:\focus\.venv\Scripts\python.exe.
  pause
  exit /b 1
)
"A:\focus\.venv\Scripts\python.exe" product\tools\windows_worker.py
pause
