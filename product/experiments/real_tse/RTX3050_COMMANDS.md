# Repeat on the Windows laptop (RTX 3050) for GPU timing and peak VRAM

The laptop could not be reached from the Replit workspace, so **nothing in this experiment was measured on the RTX 3050**.
Every timing in `report.html` is CPU (8 cores, no GPU). Peak VRAM there says "not measured (CPU)".

Run from the repository root in a Command Prompt. `PY` is the original environment's Python (it already holds the GPU torch).

```bat
set PY=A:\focus\.venv\Scripts\python.exe

REM 1. Setup (approval-first; separate folder %LOCALAPPDATA%\FocusVoice\overlap; downloads ~1.5 GB)
product\tools\Setup-Overlap.cmd
REM    Answer yes. If the optional pyannote step fails, that does not affect these three candidates.
REM    Scoring packages for this experiment (STOI and PESQ), installed into the same separate folder:
%PY% -m pip install --target "%LOCALAPPDATA%\FocusVoice\overlap\site" pystoi pesq setuptools
REM    (pesq compiles C code; without a C compiler it fails and the report prints PESQ as an error, STOI still works.)
%PY% product\tools\overlap_experiment.py readiness --out experiment-out

REM 2. Solo recordings and the mixture set (same data, same seed 83 as the CPU run)
curl -L -o dev-clean.tar.gz https://www.openslr.org/resources/12/dev-clean.tar.gz
%PY% product\tools\librispeech_solo.py --archive dev-clean.tar.gz --out solo --speakers 84 1462 1673 1919 174 251 422 652 --seconds 60
%PY% product\tools\overlap_set.py --solo-dir solo --out overlap-set --language english_librispeech_non_egyptian --layout experiment --seed 83

REM 3. Comparison run: same candidates, same mixes, GPU
%PY% product\tools\overlap_experiment.py run --set overlap-set --out experiment-out --device cuda --candidates wesep_bsrnn usef_tse spexplus --seed 83
%PY% product\tools\overlap_experiment.py render --out experiment-out
```

`experiment-out\report.html` has the same tables with GPU seconds, real-time factor and peak VRAM. The separation scores
should match the CPU run closely (fp16 on GPU can move them slightly; the run falls back to fp32 on NaN).
If a candidate fails to load, the report shows its exact error and the others still run.
