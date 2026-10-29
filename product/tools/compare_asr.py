"""Compare ASR models on human-verified Egyptian references (CER/WER, time, GPU memory).

Run on the Windows GPU computer, inside the worker's environment, with models that
are already local (HF_HUB_OFFLINE=1 is forced; nothing is downloaded).

Input directory: pairs ``<clip>.wav`` (isolated audio) + ``<clip>.txt`` (human-written
reference). Anything without a reference is skipped and reported, never scored.

  python product/tools/compare_asr.py --data DIR --models small,medium \
      --out docs/asr_results.json

GPU memory is the peak increase of ``nvidia-smi`` used memory while a model is
loaded and transcribing (ctranslate2 does not use the torch allocator).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "eval"))


def gpu_used_mb():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.split()[0]
        return int(out)
    except Exception:
        return None


class PeakGpu:
    def __enter__(self):
        self.base, self.peak, self._stop = gpu_used_mb(), None, threading.Event()
        if self.base is not None:
            self.peak = self.base
            threading.Thread(target=self._poll, daemon=True).start()
        return self

    def _poll(self):
        while not self._stop.is_set():
            used = gpu_used_mb()
            if used is not None:
                self.peak = max(self.peak, used)
            time.sleep(0.2)

    def __exit__(self, *_):
        self._stop.set()

    @property
    def delta_mb(self):
        return None if self.base is None else self.peak - self.base


def evaluate_model(model, clips, compute, beam):
    from focus_eval.textnorm import error_counts
    from tools.asr_engine import AsrEngine, AsrError
    import soundfile as sf

    engine = AsrEngine(model=model, compute_type=compute)
    engine.beam_size = beam
    row = {"model": model, "compute_type": compute, "beam_size": beam}
    with PeakGpu() as gpu:
        try:
            t0 = time.perf_counter()
            engine._load()
            row["load_s"] = round(time.perf_counter() - t0, 2)
        except AsrError as exc:
            row.update(status=exc.code, detail=str(exc))
            return row
        ce = cn = we = wn = 0
        audio_s = wall_s = 0.0
        per_clip = []
        for wav, ref_text in clips:
            info = sf.info(str(wav))
            t0 = time.perf_counter()
            try:
                segs = engine.transcribe(str(wav))
            except AsrError as exc:
                row.update(status=exc.code, detail=str(exc))
                return row
            elapsed = time.perf_counter() - t0
            hyp = " ".join(s["text"] for s in segs)
            c_err, c_n = error_counts(ref_text, hyp, "char")
            w_err, w_n = error_counts(ref_text, hyp, "word")
            ce, cn, we, wn = ce + c_err, cn + c_n, we + w_err, wn + w_n
            audio_s += info.duration
            wall_s += elapsed
            per_clip.append({"clip": wav.stem, "cer": round(c_err / c_n, 4),
                             "wer": round(w_err / w_n, 4), "seconds": round(elapsed, 2)})
    row.update(
        status="ok", clips=len(per_clip),
        cer=round(ce / cn, 4), wer=round(we / wn, 4),
        median_clip_s=round(statistics.median(c["seconds"] for c in per_clip), 2),
        rtf=round(wall_s / audio_s, 3), gpu_peak_delta_mb=gpu.delta_mb,
        per_clip=per_clip,
    )
    return row


def main():
    os.environ["HF_HUB_OFFLINE"] = "1"
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--models", default="small,medium")
    ap.add_argument("--compute", default="int8_float16")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    clips, skipped = [], []
    for wav in sorted(Path(args.data).glob("*.wav")):
        ref = wav.with_suffix(".txt")
        text = ref.read_text(encoding="utf-8").strip() if ref.is_file() else ""
        (clips if text else skipped).append((wav, text) if text else wav.name)
    if not clips:
        sys.exit("no clips with a human-written reference; nothing to score")
    results = [evaluate_model(m.strip(), clips, args.compute, args.beam)
               for m in args.models.split(",") if m.strip()]
    report = {"n_clips": len(clips), "skipped_no_reference": skipped, "results": results}
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in results:
        print(r["model"], r["status"], r.get("cer"), r.get("wer"), r.get("rtf"), r.get("gpu_peak_delta_mb"))


if __name__ == "__main__":
    main()
