@echo off
rem Read-only check of this computer: NVIDIA GPU, CUDA, driver, free VRAM, the Python found, the checkpoints
rem and the sizing that would be used. Loads no model and downloads nothing. Usage:
rem   Focus-Check-GPU.cmd                      -> this computer
rem   Focus-Check-GPU.cmd --url https://...    -> also checks the connection to a remote website
if exist "%~dp0product\tools\windows_worker.py" (cd /d "%~dp0") else cd /d "%~dp0..\.."
call "%~dp0focus_env.cmd"
if errorlevel 1 (
  pause
  exit /b 1
)
set PYTHONPATH=%CD%\product;%CD%\product\packages\ml
"%FOCUS_PY%" product\tools\gpu_check.py %*
pause
