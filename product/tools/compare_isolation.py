"""Compare isolation settings on one clip. RUN ON THE WINDOWS GPU MACHINE.

    python product/tools/compare_isolation.py --video hard.mp4 --target-slot 0 \
        --out-dir compare_out [--reference clean_target.wav] [--landmarker-model face_landmarker.task]

Runs the same video and the same face through these settings, side by side:
  old_2s             2 s windows, no overlap, no level control, face_alignment
  overlap_4s         4 s windows, 50% overlap, crossfade, level control, face_alignment
  overlap_4s_fast_lm same as overlap_4s but MediaPipe landmarks (needs --landmarker-model)
Each setting is run once to warm up and once timed. Output: <name>.wav per
setting plus report.json / report.txt with per-stage times, total time and,
when --reference is given, SI-SDR improvement over the raw mixture.
Needs FOCUS_MODEL_SOURCE and FOCUS_MODEL_CACHE (read-only) and CUDA.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import replace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "packages", "ml"))

from focus_ml.config import AdapterConfig  # noqa: E402

GATE_TOTAL_S, GATE_LANDMARK_PREP_S = 5.0, 2.0


def si_sdr(estimate, target) -> float:
    import numpy as np

    n = min(len(estimate), len(target))
    est = np.asarray(estimate[:n], dtype=np.float64)
    ref = np.asarray(target[:n], dtype=np.float64)
    est, ref = est - est.mean(), ref - ref.mean()
    scale = np.dot(est, ref) / (np.dot(ref, ref) + 1e-12)
    proj = scale * ref
    noise = est - proj
    return float(10 * np.log10((np.sum(proj ** 2) + 1e-12) / (np.sum(noise ** 2) + 1e-12)))


def si_sdri(est_wav: str, mix_wav: str, ref_wav: str) -> dict:
    import soundfile as sf

    est, _ = sf.read(est_wav, dtype="float32")
    mix, _ = sf.read(mix_wav, dtype="float32")
    ref, _ = sf.read(ref_wav, dtype="float32")
    if est.ndim > 1:
        est = est.mean(axis=1)
    if mix.ndim > 1:
        mix = mix.mean(axis=1)
    if ref.ndim > 1:
        ref = ref.mean(axis=1)
    mix_score, est_score = si_sdr(mix, ref), si_sdr(est, ref)
    return {"si_sdr_mix": round(mix_score, 2), "si_sdr_est": round(est_score, 2),
            "si_sdri": round(est_score - mix_score, 2)}


def settings(base: AdapterConfig, landmarker_model: str | None) -> dict:
    out = {
        "old_2s": replace(base, window_s=2.0, merge="direct", window_overlap=0.0,
                          normalize_audio=False, landmark_backend="face_alignment"),
        "overlap_4s": replace(base, window_s=4.0, merge="crossfade", window_overlap=0.5,
                              normalize_audio=True, landmark_backend="face_alignment"),
    }
    if landmarker_model:
        out["overlap_4s_fast_lm"] = replace(
            out["overlap_4s"], landmark_backend="mediapipe", landmarker_model=landmarker_model)
    return out


def render_text(report: dict) -> str:
    lines = [f"video: {report['video']}"]
    for name, row in report["runs"].items():
        t = row["timings"]
        lines.append(
            f"{name}: total {row['total_s']}s | landmarks {t.get('landmark_s')}s | "
            f"tracking {t.get('detect_track')}s | mouth_roi {t.get('mouth_roi')}s | "
            f"separate {t.get('separate_wall')}s | audio {row['wav']}"
            + (f" | SI-SDRi {row['quality']['si_sdri']} dB" if row.get("quality") else ""))
    gate = report.get("speed_gate")
    if gate:
        lines.append(f"speed gate (<= {GATE_TOTAL_S}s total, landmarks <= {GATE_LANDMARK_PREP_S}s): "
                     f"{'PASS' if gate['pass'] else 'FAIL'} ({gate['setting']})")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--target-slot", type=int, default=0, help="face index, left to right")
    ap.add_argument("--reference", help="clean target WAV, enables SI-SDRi")
    ap.add_argument("--landmarker-model", help="MediaPipe face_landmarker.task file")
    ap.add_argument("--only", nargs="*", help="run only these setting names")
    a = ap.parse_args()

    from focus_ml.adapter import LegacyDolphinAdapter
    from focus_ml.types import TargetSelection

    os.makedirs(a.out_dir, exist_ok=True)
    base = AdapterConfig.from_env()
    todo = settings(base, a.landmarker_model or base.landmarker_model)
    if a.only:
        todo = {k: v for k, v in todo.items() if k in a.only}
    adapter = LegacyDolphinAdapter(base)
    models = adapter.load_models(base)  # raises honestly without GPU/weights
    cands = sorted(adapter.detect_candidates(a.video, base, video_id="compare"),
                   key=lambda c: c.bbox[0])
    target = TargetSelection(face_id=cands[a.target_slot].face_id)

    report: dict = {"video": a.video, "runs": {}}
    with tempfile.TemporaryDirectory() as work:
        mix_wav = os.path.join(work, "mix.wav")
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", a.video,
                        "-vn", "-ar", "16000", "-ac", "1", mix_wav], check=True)
        for name, cfg in todo.items():
            bundle = replace(models, config=cfg)
            run_adapter = LegacyDolphinAdapter(cfg)
            for attempt in ("warmup", "timed"):
                job = os.path.join(work, f"{name}_{attempt}")
                started = time.perf_counter()
                res = run_adapter.extract_target(a.video, target, job, bundle, video_id="compare")
                total = round(time.perf_counter() - started, 2)
            dest = os.path.join(a.out_dir, f"{name}.wav")
            shutil.copyfile(res.wav_path, dest)
            row = {"total_s": total, "timings": dict(res.timings), "wav": dest,
                   "settings": {"window_s": cfg.window_s, "merge": cfg.merge,
                                "overlap": cfg.window_overlap,
                                "normalize": cfg.normalize_audio,
                                "landmarks": cfg.landmark_backend}}
            if a.reference:
                row["quality"] = si_sdri(dest, mix_wav, a.reference)
            report["runs"][name] = row
    fast = report["runs"].get("overlap_4s_fast_lm")
    if fast:
        lm = float(fast["timings"].get("landmark_s", 0.0))
        report["speed_gate"] = {"setting": "overlap_4s_fast_lm",
                                "pass": fast["total_s"] <= GATE_TOTAL_S and lm <= GATE_LANDMARK_PREP_S}
    with open(os.path.join(a.out_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    text = render_text(report)
    with open(os.path.join(a.out_dir, "report.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
