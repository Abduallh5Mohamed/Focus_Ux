@echo off
cd /d "%~dp0\..\.."
set PYTHONPATH=%CD%\product;%CD%\product\packages\ml
"A:\focus\.venv\Scripts\python.exe" -m focus_ml.voice.cli readiness %*
pause
