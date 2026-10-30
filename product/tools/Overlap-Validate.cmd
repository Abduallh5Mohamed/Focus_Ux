@echo off
rem One command for the RTX 3050 validation. Usage (from anywhere):
rem   Overlap-Validate.cmd target_enroll.wav two_speakers_5to10s.wav meeting_with_overlap.wav
rem Step 1 preflight, step 2 one-mixture GPU test, step 3 end-to-end test. Stops at the first failure.
rem Outputs: validation-out\preflight\preflight.json, validation-out\minimal\{mixture,enrollment,extracted_target}.wav,
rem   gpu_log.txt, report.json, validation-out\e2e\{strict,continuity}\isolated.wav, e2e_report.json
set A1=%~f1
set A2=%~f2
set A3=%~f3
if exist "%~dp0product\tools\windows_worker.py" (cd /d "%~dp0") else cd /d "%~dp0..\.."
set PY=A:\focus\.venv\Scripts\python.exe
if not exist "%PY%" (
  echo Original Python was not found at %PY%.
  pause
  exit /b 1
)
if "%~3"=="" (
  echo Usage: Overlap-Validate.cmd ENROLLMENT.wav MIXTURE_5_10S.wav RECORDING_WITH_OVERLAP.wav
  pause
  exit /b 1
)
"%PY%" product\tools\overlap_minimal_infer.py --candidate wesep_bsrnn --out validation-out\preflight --preflight-only
if errorlevel 1 goto failed
"%PY%" product\tools\overlap_minimal_infer.py --candidate wesep_bsrnn --enrollment "%A1%" --mixture "%A2%" --out validation-out\minimal
if errorlevel 1 goto failed
echo.
echo Listen to validation-out\minimal\extracted_target.wav. Press Ctrl+C to stop if it is not the target voice.
pause
"%PY%" product\tools\overlap_e2e.py --recording "%A3%" --enrollment "%A1%" --out validation-out\e2e
if errorlevel 1 goto failed
echo Done. Send back the validation-out folder.
pause
exit /b 0
:failed
echo A step failed. Nothing after it was run. Send back the validation-out folder.
pause
exit /b 1
