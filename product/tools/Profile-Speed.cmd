@echo off
rem Profiles the pipeline on this computer. Usage: Profile-Speed.cmd clip1.wav clip3.wav clip10.wav
cd /d "%~dp0..\.."
call "%~dp0focus_env.cmd"
if errorlevel 1 (
  pause
  exit /b 1
)
set PYTHONPATH=%CD%\product;%CD%\product\packages\ml
"%FOCUS_PY%" product\tools\profile_pipeline.py --warmup --clips %* --out profile.json --limits-out speed_limits.json
pause
