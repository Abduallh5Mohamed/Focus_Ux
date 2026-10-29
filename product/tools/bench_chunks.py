"""Consecutive 2-second chunk benchmark. RUN ON THE GPU MACHINE, not Replit.

    python product/tools/bench_chunks.py --video clip.mp4 --clip-id baseline_01 \
        --speaker a --target-slot 0 --label adaptive-v1 --tracking-mode adaptive \
        --run-dir runs/adaptive-v1

Cuts the video into chunks with ffmpeg, runs the real adapter on each chunk in
order and writes bench numbers (RTF, latency, queue depth) plus the isolated
audio in the focus_eval run layout, so ``python -m focus_eval evaluate`` can
score the same run. The target is chosen per chunk as the face at position
``--target-slot`` (left to right on the chunk's first frame); this is a
benchmark shortcut, not the product selection flow.

Requires FOCUS_MODEL_SOURCE / FOCUS_MODEL_CACHE and CUDA. Without them the
adapter raises and nothing is reported as measured.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import replace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "packages", "ml"))

from focus_ml.adapter import LegacyDolphinAdapter  # noqa: E402
from focus_ml.chunk_bench import ChunkResult, run_chunks, write_run  # noqa: E402
from focus_ml.config import AdapterConfig  # noqa: E402
from focus_ml.types import TargetSelection  # noqa: E402


def cut_chunks(video: str, out_dir: str, chunk_s: float, ffmpeg: str = "ffmpeg") -> list[str]:
    pattern = os.path.join(out_dir, "chunk_%04d.mp4")
    subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", video,
         "-f", "segment", "-segment_time", str(chunk_s), "-reset_timestamps", "1",
         "-c:v", "libx264", "-c:a", "aac", "-force_key_frames",
         f"expr:gte(t,n_forced*{chunk_s})", pattern],
        check=True,
    )
    return sorted(os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.startswith("chunk_"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--clip-id", required=True)
    ap.add_argument("--speaker", required=True)
    ap.add_argument("--target-slot", type=int, default=0)
    ap.add_argument("--label", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--chunk-s", type=float, default=2.0)
    ap.add_argument("--tracking-mode", choices=("reference", "adaptive"), default="reference")
    a = ap.parse_args()

    cfg = replace(AdapterConfig.from_env(), tracking_mode=a.tracking_mode)
    adapter = LegacyDolphinAdapter(cfg)
    models = adapter.load_models(cfg)  # raises honestly without GPU/weights

    with tempfile.TemporaryDirectory() as work:
        chunks = cut_chunks(a.video, work, a.chunk_s)

        def process(index: int, chunk: str) -> ChunkResult:
            cands = sorted(adapter.detect_candidates(chunk, cfg, video_id=a.clip_id),
                           key=lambda c: c.bbox[0])
            target = TargetSelection(face_id=cands[a.target_slot].face_id)
            job = os.path.join(work, f"job_{index:04d}")
            res = adapter.extract_target(chunk, target, job, models, video_id=a.clip_id)
            return ChunkResult(index, res.wav_path, res.duration_ms / 1000.0, 0.0,
                               timings=dict(res.timings))

        results = run_chunks(chunks, process, a.chunk_s)
        bench = write_run(a.run_dir, a.label, a.clip_id, a.speaker, results, a.chunk_s,
                          {"tracking_mode": a.tracking_mode})
    print(f"RTF {bench['rtf']} (target <= {bench['rtf_target']}), "
          f"failed {bench['n_failed']}/{bench['n_chunks']}, "
          f"max queue {bench['max_queue_depth']}, latency p95 {bench['latency_s']['p95']}s")
    return 0 if bench["n_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
