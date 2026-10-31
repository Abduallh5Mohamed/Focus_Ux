"""Profile the audio-only pipeline on the demo laptop (or any machine).

For each clip: time per stage, real-time factor, peak VRAM and peak RAM, and
where the CPU and GPU sit idle. Optionally writes ``speed_limits.json``: the
longest clip length that was MEASURED to meet the speed target. The API reads
that file to set the upload limit and to word its refusal message.

  python product/tools/profile_pipeline.py --clips c1.wav c3.wav c10.wav --out profile.json \
      --limits-out speed_limits.json
  python product/tools/profile_pipeline.py --make-long clip.wav --seconds 600 --out long10.wav

Nothing here is a result until it has been run on the target NVIDIA GPU; the
file records the device so a CPU or other-GPU profile is never mistaken for one.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_runner  # noqa: E402  (sets up sys.path for focus_ml / focus_eval)
from eval_runner import environment_info  # noqa: E402
from focus_ml.isolation_engines import write_wav  # noqa: E402
from focus_ml.voice import preprocess  # noqa: E402
from focus_ml.voice.profile import (  # noqa: E402
    SPEED_LIMITS_FORMAT, ResourceMonitor, StageProfiler, supported_audio_seconds)

DEFAULT_RTF_TARGET = 0.8   # same target as focus_eval.gate


def profile_clips(engine, paths: list[str], *, device: str = "cpu", prefetch: bool = True) -> dict:
    """Analyse, enrol the voice with the most clean speech, isolate.

    Returns {"runs": one entry per clip, "audio_decodes": ffmpeg decodes for the whole call}.
    Decodes are counted per call, not per clip, because prefetching decodes the next clip early."""
    monitor = ResourceMonitor().start()
    runs = []
    decodes0 = preprocess.decode_count
    try:
        stream = preprocess.prefetch_decoded(paths) if prefetch else ((p, None) for p in paths)
        mark = time.perf_counter()   # wall time runs from the end of the previous clip, so waiting for
        for path, _ in stream:       # the decoder is counted, and so is everything the stages leave out
            prof = StageProfiler(device, monitor)
            engine.log = prof
            entry = {"clip": str(path), "ok": False, "error": None}
            audio_s = None
            try:
                # Known even when the run fails: a failed length must still end the supported range.
                audio_s = len(preprocess.load_canonical(path)) / 16000
                analysis = engine.analyze(path)
                usable = [s for s in analysis["speakers"] if s["usable"]]
                if not usable:
                    raise RuntimeError("no usable voice found in this clip")
                target = max(usable, key=lambda s: s["clean_s"])
                with tempfile.TemporaryDirectory(prefix="focus-profile-") as tmp:
                    engine.isolate(path, target["voiceprint"], analysis["diarization"], tmp)
                entry["ok"] = True
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            wall = time.perf_counter() - mark
            d = prof.as_dict()
            entry.update(
                audio_seconds=audio_s, wall_seconds=round(wall, 3), stages=d["stages"],
                # end-to-end elapsed time; stage times can overlap or leave gaps, so they only diagnose
                real_time_factor=round(wall / audio_s, 3) if audio_s else None,
                stage_sum_seconds=d["total_seconds"],
                peak_vram_mib=d["peak_vram_mib"], peak_ram_mib=d["peak_ram_mib"],
                idle_summary={n: s["idle"] for n, s in d["stages"].items()})
            runs.append(entry)
            engine.log = None
            mark = time.perf_counter()
    finally:
        engine.log = None
        monitor.stop()
    return {"runs": runs, "audio_decodes": preprocess.decode_count - decodes0}


def limits_from_runs(runs: list[dict], env: dict, rtf_target: float, ram_budget_mib: float | None = None) -> dict:
    measured = list(runs)   # every attempted clip counts, failed ones included
    total = env.get("gpu_total_vram_mib")
    on_target = bool(env.get("gpu_name")) and bool(total)   # any real GPU with a VRAM reading
    res = supported_audio_seconds(measured, rtf_target, vram_budget_mib=total * 0.9 if total else None,
                                  ram_budget_mib=ram_budget_mib)
    if not runs:
        res["supported_audio_s"] = None
        res["not_installable_reason"] = "no clips were profiled"
    elif not on_target:   # only a run on a real GPU can raise the limit
        res["supported_audio_s"] = None
        res["not_installable_reason"] = "not measured on a real NVIDIA GPU with VRAM readings"
    return {"format": SPEED_LIMITS_FORMAT, **res, "measured_on_target_laptop": on_target,
            "device": env.get("gpu_name") or "cpu only",
            "measured_at": time.strftime("%Y-%m-%d"), "runs": [
                {k: r.get(k) for k in ("audio_seconds", "real_time_factor", "wall_seconds", "peak_vram_mib", "peak_ram_mib", "ok")}
                for r in measured]}


def make_long(src: str, seconds: float, out: str) -> dict:
    """A long test clip made by repeating a real one. The diarizer sees real speech, but the same
    content repeats; say so when reporting."""
    import numpy as np
    x = preprocess.load_canonical(src)
    n = int(seconds * 16000)
    y = np.tile(x, int(np.ceil(n / len(x))))[:n]
    write_wav(out, y, 16000)
    return {"out": out, "seconds": seconds, "source": src, "synthetic_repetition": True}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clips", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limits-out")
    ap.add_argument("--rtf-target", type=float, default=DEFAULT_RTF_TARGET)
    ap.add_argument("--embedder", default="ecapa", choices=("ecapa", "pyannote"))
    ap.add_argument("--device", default="auto")
    ap.add_argument("--no-prefetch", action="store_true")
    ap.add_argument("--warmup", action="store_true", help="run the first clip once before timing (models load at first use)")
    ap.add_argument("--make-long")
    ap.add_argument("--seconds", type=float, default=600.0)
    a = ap.parse_args(argv)
    if a.make_long:
        print(json.dumps(make_long(a.make_long, a.seconds, a.out), indent=1))
        return 0
    if not a.clips:
        ap.error("--clips is required")
    settings = {**eval_runner.DEFAULT_SETTINGS, "embedder": a.embedder, "device": a.device}
    engine = eval_runner.build_real_engine(settings)
    if a.warmup:
        profile_clips(engine, [a.clips[0]], device=settings["device_resolved"], prefetch=False)
    result = profile_clips(engine, a.clips, device=settings["device_resolved"], prefetch=not a.no_prefetch)
    runs = result["runs"]
    env = environment_info()
    report = {"environment": env, "settings": settings, "warmup": a.warmup, "runs": runs, "audio_decodes": result["audio_decodes"],
              "measured_on_target_laptop": bool(env.get("gpu_name"))}
    Path(a.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    if a.limits_out:
        Path(a.limits_out).write_text(json.dumps(limits_from_runs(runs, env, a.rtf_target), indent=1), encoding="utf-8")
    for r in runs:
        print(f"{Path(r['clip']).name}: ok={r['ok']} RTF={r['real_time_factor']} VRAM={r['peak_vram_mib']} "
              f"RAM={r['peak_ram_mib']} {r['error'] or ''}")
    return 0 if all(r["ok"] for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
