@echo off
cd /d "%~dp0..\.."
call "%~dp0focus_env.cmd"
if errorlevel 1 (
  pause
  exit /b 1
)
set PYTHONPATH=%CD%\product;%CD%\product\packages\ml
"%FOCUS_PY%" -m focus_ml.voice.cli readiness %*
pause
