"""Minimal REAL inference for one overlap-extraction model on a CUDA GPU (Windows or Linux).

One pretrained model, one enrollment recording, one 5-10 s two-speaker mixture. It runs the GPU
preflight first and refuses to continue when a check fails; nothing is simulated.

  %FOCUS_PY% product\\tools\\overlap_minimal_infer.py ^
      --candidate wesep_bsrnn --enrollment target_enroll.wav --mixture two_speakers.wav --out minimal-out

Writes: preflight.json, mixture.wav, enrollment.wav, extracted_target.wav, gpu_log.txt, report.json.
Use --preflight-only to run just the checks. Weights come from Setup-Overlap.cmd (approval first);
this script downloads nothing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "product"), str(ROOT / "product" / "packages" / "ml")]


def nvidia_smi() -> str:
    try:
        return subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return f"nvidia-smi unavailable: {exc}"


def main() -> int:
    from focus_ml.overlap.base import ENROLL_MAX_S, trim_enrollment
    from focus_ml.overlap.candidates import INFO, ORDER, build_candidate
    from focus_ml.overlap.preflight import run_preflight
    from focus_ml.isolation_engines import write_wav
    from focus_ml.voice.embedder import build_embedder
    from focus_ml.voice.match import cosine
    from focus_ml.voice.preprocess import load_canonical
    from focus_ml.voice.types import SAMPLE_RATE, Voiceprint

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", default="wesep_bsrnn", choices=ORDER)
    ap.add_argument("--enrollment", type=Path)
    ap.add_argument("--mixture", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--embedder", default="ecapa")
    ap.add_argument("--no-fp16", action="store_true")
    ap.add_argument("--preflight-only", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    pre = run_preflight(a.candidate)
    (a.out / "preflight.json").write_text(json.dumps(pre, indent=2))
    for c in pre["checks"]:
        print(f"[{c['status'].upper():7}] {c['name']}: {c['detail']}")
    print(pre["verdict"])
    if a.preflight_only:
        return 0 if pre["ok"] else 2
    if not pre["ok"]:
        print("Stopped: nothing was run. Fix the failed checks and run again.", file=sys.stderr)
        return 2
    if not (a.enrollment and a.mixture):
        print("--enrollment and --mixture are required", file=sys.stderr)
        return 2

    import torch
    enroll, mix = load_canonical(str(a.enrollment)).copy(), load_canonical(str(a.mixture)).copy()
    secs = len(mix) / SAMPLE_RATE
    if not 5.0 <= secs <= 10.0:
        print(f"The mixture must be 5-10 s long (it is {secs:.1f} s).", file=sys.stderr)
        return 2
    ref = trim_enrollment(enroll, ENROLL_MAX_S)
    embedder = build_embedder(a.embedder, "cuda")
    vp = Voiceprint([float(v) for v in embedder.embed(ref)], embedder.name, len(ref) / SAMPLE_RATE,
                    {"kind": "voice_file", "file": a.enrollment.name})
    extractor = build_candidate(a.candidate, device="cuda", fp16=not a.no_fp16, embedder=embedder)
    log = ["== before ==", nvidia_smi()]
    torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    extractor.load()                       # loaded once
    load_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    out = extractor.extract(mix, vp, ref)  # one inference, no repeats
    torch.cuda.synchronize()
    infer_s = time.perf_counter() - t1
    peak = round(torch.cuda.max_memory_allocated() / 2**20, 1)
    log += ["== after inference ==", nvidia_smi()]
    shutil.copyfile(a.mixture, a.out / "mixture.wav")
    shutil.copyfile(a.enrollment, a.out / "enrollment.wav")
    write_wav(str(a.out / "extracted_target.wav"), out, SAMPLE_RATE)
    (a.out / "gpu_log.txt").write_text("\n".join(log))
    import numpy as np
    info = INFO[a.candidate]
    report = {
        "candidate": info.as_dict(), "device": pre["probes"].get("gpu"), "torch": pre["probes"]["torch"],
        "mixture_seconds": round(secs, 2), "load_seconds": round(load_s, 2),
        "inference_seconds": round(infer_s, 3), "peak_vram_mib": peak, "fp16": extractor.use_fp16,
        "output_samples_equal_input": len(out) == len(mix),
        "silent_pct": round(100 * float(np.mean(np.abs(out) < 1e-4)), 2),
        "cosine_output_vs_enrollment": round(cosine(vp.vector, embedder.embed(out)), 4),
        "note": "One mixture is not an acceptance test. Listen to extracted_target.wav before expanding.",
    }
    (a.out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("Failed: " + str(getattr(exc, "message", exc)), file=sys.stderr)
        sys.exit(1)
