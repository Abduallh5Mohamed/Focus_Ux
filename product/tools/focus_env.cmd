@echo off
rem Finds the Python environment that runs FOCUS on this computer and sets FOCUS_PY.
rem Call it after changing to the project folder:   call "%~dp0focus_env.cmd"
rem Order: 1. FOCUS_PYTHON, if you set it to a python.exe. It must exist and is never replaced silently.
rem        2. .venv-ml, .venv or venv in this project folder, the first one that can import torch.
rem        3. python on PATH, if it can import torch.
rem Nothing is installed or downloaded here.
set "FOCUS_PY="
if defined FOCUS_PYTHON goto explicit
for %%D in (.venv-ml .venv venv) do call :try "%CD%\%%D\Scripts\python.exe"
if defined FOCUS_PY exit /b 0
where python >nul 2>nul
if errorlevel 1 goto missing
python -c "import torch" >nul 2>nul
if errorlevel 1 goto missing
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)"') do set "FOCUS_PY=%%P"
if defined FOCUS_PY exit /b 0
goto missing

:explicit
if exist "%FOCUS_PYTHON%" (
  set "FOCUS_PY=%FOCUS_PYTHON%"
  exit /b 0
)
echo FOCUS_PYTHON is set to "%FOCUS_PYTHON%" but that file does not exist.
echo Fix the path, or clear it with:  set FOCUS_PYTHON=
exit /b 1

:try
if defined FOCUS_PY exit /b 0
if not exist %1 exit /b 0
%1 -c "import torch" >nul 2>nul
if errorlevel 1 exit /b 0
set "FOCUS_PY=%~1"
exit /b 0

:missing
echo No Python with PyTorch was found for FOCUS.
echo Looked for .venv-ml, .venv and venv in %CD%, then python on PATH.
echo Point FOCUS at your GPU Python, then run this again:
echo   set FOCUS_PYTHON=C:\path\to\your\python.exe
echo See docs\LOCAL_GPU_GUIDE.md.
exit /b 1
