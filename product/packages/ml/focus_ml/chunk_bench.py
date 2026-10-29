"""Consecutive-chunk speed benchmark (pure logic).

Simulates a live source that delivers one chunk every ``chunk_s`` seconds and a
single worker that processes chunks in order. Uses the *measured* processing
time of each chunk, so the numbers are only as real as the processor passed in
(on the GPU machine: the real adapter; in tests: a fake).

Per chunk: processing time, arrival, finish, latency (finish - arrival) and
queue depth at arrival. Summary: real-time factor (RTF = processing time /
audio duration; target <= 0.8), latency median/p95/max and max queue depth.

The run directory written by ``write_run`` follows focus_eval's run layout, so
``python -m focus_eval evaluate`` reads it directly::

    <run>/run.json                      {"label": ..., "bench_by_clip": {clip_id: {...}}}
    <run>/<clip_id>/<speaker>.wav       concatenated isolated chunks
    <run>/<clip_id>/<speaker>.txt       optional hypothesis
"""
from __future__ import annotations

import json
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Callable, Sequence

RTF_TARGET = 0.8


@dataclass
class ChunkResult:
    index: int
    wav_path: str | None
    duration_s: float
    processing_s: float
    error: str | None = None
    timings: dict | None = None


def run_chunks(
    chunks: Sequence[str],
    process: Callable[[int, str], ChunkResult | dict],
    chunk_s: float,
    clock: Callable[[], float] = time.perf_counter,
) -> list[ChunkResult]:
    """Process chunks in order, timing each call. ``process`` returns a
    ChunkResult (with its own ``processing_s`` ignored) or a dict with keys
    wav_path, duration_s and optionally timings; exceptions are recorded."""
    results: list[ChunkResult] = []
    for index, chunk in enumerate(chunks):
        started = clock()
        try:
            out = process(index, chunk)
            if isinstance(out, dict):
                out = ChunkResult(
                    index, out.get("wav_path"), float(out.get("duration_s", chunk_s)),
                    0.0, timings=out.get("timings"),
                )
            result = out
            result.index = index
            result.error = None
        except Exception as exc:  # recorded, never hidden
            result = ChunkResult(index, None, chunk_s, 0.0, error=f"{type(exc).__name__}: {exc}")
        result.processing_s = clock() - started
        results.append(result)
    return results


def simulate_stream(results: Sequence[ChunkResult], chunk_s: float) -> list[dict]:
    """Chunk k arrives at (k+1)*chunk_s (it must be fully recorded first); one
    worker processes chunks in order using each chunk's measured time."""
    rows: list[dict] = []
    free_at = 0.0
    finishes: list[float] = []
    for r in results:
        arrival = (r.index + 1) * chunk_s
        start = max(arrival, free_at)
        finish = start + r.processing_s
        free_at = finish
        waiting = sum(1 for f in finishes if f > arrival)  # earlier chunks still unfinished
        finishes.append(finish)
        rows.append({
            "chunk": r.index,
            "duration_s": round(r.duration_s, 3),
            "processing_s": round(r.processing_s, 4),
            "arrival_s": round(arrival, 3),
            "finish_s": round(finish, 3),
            "latency_s": round(finish - arrival, 3),
            "queue_depth_at_arrival": waiting,
            "error": r.error,
            "timings": r.timings,
        })
    return rows


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[pos]


def summarize_bench(results: Sequence[ChunkResult], chunk_s: float) -> dict:
    rows = simulate_stream(results, chunk_s)
    ok = [r for r in results if r.error is None]
    audio_s = sum(r.duration_s for r in ok)
    proc_s = sum(r.processing_s for r in ok)
    rtf = proc_s / audio_s if audio_s > 0 else None
    lat = [row["latency_s"] for row, r in zip(rows, results) if r.error is None]
    return {
        "chunk_s": chunk_s,
        "n_chunks": len(results),
        "n_failed": len(results) - len(ok),
        "audio_s": round(audio_s, 3),
        "processing_s": round(proc_s, 3),
        "rtf": round(rtf, 4) if rtf is not None else None,
        "rtf_target": RTF_TARGET,
        # No verdict when nothing succeeded or any chunk failed.
        "meets_rtf_target": (rtf <= RTF_TARGET) if (rtf is not None and len(ok) == len(results)) else None,
        "latency_s": {
            "median": round(median(lat), 3) if lat else None,
            "p95": round(_percentile(lat, 0.95), 3) if lat else None,
            "max": round(max(lat), 3) if lat else None,
        },
        "max_queue_depth": max((row["queue_depth_at_arrival"] for row in rows), default=0),
        "chunks": rows,
    }


def concat_wavs(paths: Sequence[str], out_path: str) -> None:
    """Concatenate PCM WAVs with identical parameters (stdlib only)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    params = None
    with wave.open(str(out), "wb") as dst:
        for p in paths:
            with wave.open(str(p), "rb") as src:
                current = src.getparams()[:3]
                if params is None:
                    params = current
                    dst.setnchannels(current[0])
                    dst.setsampwidth(current[1])
                    dst.setframerate(current[2])
                elif current != params:
                    raise ValueError(f"{p}: WAV parameters differ from the first chunk")
                dst.writeframes(src.readframes(src.getnframes()))


def write_run(
    run_dir: str, label: str, clip_id: str, speaker_id: str,
    results: Sequence[ChunkResult], chunk_s: float, settings: dict,
) -> dict:
    """Write bench + isolated audio in focus_eval run layout. Audio is written
    only when every chunk succeeded, so a partial run is reported as missing
    audio instead of being scored as a short output."""
    bench = summarize_bench(results, chunk_s)
    bench["settings"] = settings
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    meta_path = root / "run.json"
    by_clip: dict = {}
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("label") != label:
            raise ValueError(
                f"{meta_path} belongs to run {meta.get('label')!r}; use a new run dir or the same label"
            )
        by_clip = dict(meta.get("bench_by_clip") or {})
    by_clip[clip_id] = bench  # one entry per clip; other clips are kept
    meta_path.write_text(
        json.dumps({"label": label, "bench_by_clip": by_clip}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    if bench["n_failed"] == 0 and results:
        concat_wavs([r.wav_path for r in results], str(root / clip_id / f"{speaker_id}.wav"))
    return bench
