@echo off
rem Starts the audio-only worker from a FULL repo checkout (not the ZIP). Run it from anywhere:
rem   product\tools\Start-Worker-Checkout.cmd
rem Optional research-only trial: in THIS window first run   set FOCUS_OVERLAP_EXTRACTOR=wesep_bsrnn
rem Nothing is enabled unless you set that variable. Credentials and A:\focus are not touched.
cd /d "%~dp0..\.."
if not exist "product\packages\ml\focus_ml\overlap\hybrid.py" (
  echo This is not a full repo checkout. Update the checkout with git pull --ff-only, then try again.
  pause
  exit /b 1
)
if not exist "A:\focus\.venv\Scripts\python.exe" (
  echo Original Python was not found at A:\focus\.venv\Scripts\python.exe.
  pause
  exit /b 1
)
if defined FOCUS_OVERLAP_EXTRACTOR (
  echo RESEARCH-ONLY TRIAL: overlap extractor %FOCUS_OVERLAP_EXTRACTOR% requested in this window only.
) else (
  echo Default mode: overlap is muted. No overlap extractor requested.
)
"A:\focus\.venv\Scripts\python.exe" product\tools\windows_worker.py %*
pause
