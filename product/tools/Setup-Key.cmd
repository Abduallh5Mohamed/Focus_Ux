@echo off
cd /d "%~dp0"
if not exist "A:\focus\.venv\Scripts\python.exe" (
  echo Original Python was not found at A:\focus\.venv\Scripts\python.exe.
  pause
  exit /b 1
)
"A:\focus\.venv\Scripts\python.exe" product\tools\windows_worker.py --setup
pause
