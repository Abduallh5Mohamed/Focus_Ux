@echo off
rem One command: runs the whole Egyptian dataset and writes reports\final\report.md/.json and the listening kit.
cd /d "%~dp0..\.."
call "%~dp0focus_env.cmd"
if errorlevel 1 (
  pause
  exit /b 1
)
set PYTHONPATH=%CD%\product;%CD%\product\packages\ml
"%FOCUS_PY%" product\tools\final_eval.py --dataset product\datasets\egyptian_eval --out reports\final --listening-seed 7 %*
pause
