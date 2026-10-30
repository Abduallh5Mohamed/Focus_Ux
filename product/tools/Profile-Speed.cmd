@echo off
rem Profiles the pipeline on this computer. Usage: Profile-Speed.cmd clip1.wav clip3.wav clip10.wav
cd /d "%~dp0\..\.."
set PYTHONPATH=%CD%\product;%CD%\product\packages\ml
"A:\focus\.venv\Scripts\python.exe" product\tools\profile_pipeline.py --warmup --clips %* --out profile.json --limits-out speed_limits.json
pause
