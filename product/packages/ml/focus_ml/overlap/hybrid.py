"""Hybrid extraction: pass through, mute, or extract, region by region.

  target alone             -> passed through unchanged
  others alone / unknown   -> muted
  overlap                  -> sent to the chosen extractor (windows, batched)
  extracted output whose voiceprint similarity is below the threshold
                           -> the region is marked uncertain and muted

Overlapping windows are blended with the same complementary sin^2 crossfade as
the Dolphin path. At a target/extracted seam the two signals cross-fade around
the boundary; at every edge towards a muted region the fade sits INSIDE the
kept audio, so no other speaker leaks. The output has the canonical length.
This class satisfies ``voice.extractor.Extractor`` so it plugs into the
existing pipeline unchanged.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from ..isolation_engines import fit_samples
from ..voice.gpu import release_gpu
from ..voice.match import MatchConfig, cosine
from ..voice.types import SAMPLE_RATE, TARGET, UNCERTAIN, LabelledRegion, Voiceprint
from ..windows import merge_windows, plan_windows
from .base import SILENT_RMS, BlockedError, OverlapExtractor, is_oom, rms, vram_peak_mib, vram_reset

OVERLAP_REASON = "overlap"


@dataclass
class HybridConfig:
    window_s: float = 4.0            # Dolphin's tested window length
    window_overlap: float = 0.5      # for regions longer than one window
    fade_ms: float = 20.0            # seam crossfade
    adjacent_ms: float = 5.0         # gaps up to this between regions count as touching
    check_chunk_s: float = 3.0       # post-extraction voiceprint check granularity
    min_check_s: float = 0.5         # shorter output cannot be verified -> muted
    accept_threshold: float | None = None   # cosine; None = the embedder's target threshold
    vram_budget_mib: float = 3500.0  # a 4 GB RTX 3050 minus headroom
    batch_size: int | None = None    # None = derived from the extractor's VRAM model


# ------------------------------------------------------------------ planning
def merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted(s for s in spans if s[1] > s[0]):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def overlap_spans(regions, n: int, sr: int = SAMPLE_RATE) -> list[tuple[int, int]]:
    """Sample spans of the regions that must be extracted: uncertain regions
    whose reason is overlap, minus anything already passed through."""
    ov = merge_spans([(max(0, int(round(r.start * sr))), min(n, int(round(r.end * sr))))
                      for r in regions if r.label == UNCERTAIN and r.reason == OVERLAP_REASON])
    tgt = merge_spans([(max(0, int(round(r.start * sr))), min(n, int(round(r.end * sr))))
                       for r in regions if r.label == TARGET])
    return subtract_spans(ov, tgt)


def subtract_spans(spans, cuts):
    out = []
    for a, b in spans:
        cur = a
        for c, d in cuts:
            if d <= cur or c >= b:
                continue
            if c > cur:
                out.append((cur, c))
            cur = max(cur, d)
        if cur < b:
            out.append((cur, b))
    return [(a, b) for a, b in out if b > a]


def plan_region_windows(a: int, b: int, n: int, window: int, overlap: float) -> list[tuple[int, int]]:
    """Absolute (start, end) windows covering [a, b). A short region gets ONE
    full-length window centred on it (real neighbouring audio as context, shifted
    to stay inside the clip); a long one gets overlapping windows whose last window
    is anchored to its end."""
    window = min(window, n)
    length = b - a
    if length <= window:
        start = min(max(0, (a + b) // 2 - window // 2), n - window)
        return [(start, start + window)]
    return [(a + s, a + e) for s, e in plan_windows(length, SAMPLE_RATE, window / SAMPLE_RATE, overlap)]


def split_check_chunks(a: int, b: int, chunk: int, min_len: int) -> list[tuple[int, int]]:
    """Equal pieces of at most ``chunk`` samples, none shorter than ``min_len``;
    a region shorter than ``min_len`` is returned whole (it cannot be verified)."""
    length = b - a
    if length < min_len:
        return [(a, b)]
    k = max(1, int(np.ceil(length / chunk)))
    while k > 1 and length / k < min_len:
        k -= 1
    edges = [a + round(length * i / k) for i in range(k + 1)]
    return list(zip(edges[:-1], edges[1:]))


# -------------------------------------------------------------- composition
def _ramp(n: int) -> np.ndarray:
    return np.sin(0.5 * np.pi * (np.arange(n) + 0.5) / n) ** 2 if n > 0 else np.zeros(0)


def compose(x, pass_spans, ext_spans, ext_audio, fade: int, adjacent: int) -> np.ndarray:
    """Build the output. ``pass_spans``/``ext_spans`` are disjoint sample spans;
    ``ext_audio`` is a full-length array holding the extracted signal inside
    ``ext_spans``. Touching spans of different kind cross-fade centred on the
    seam; the outer edge of each kept group fades inside the group."""
    n = len(x)
    spans = sorted([(a, b, "pass") for a, b in pass_spans] + [(a, b, "ext") for a, b in ext_spans])
    # group spans that touch (within `adjacent`), merging same-kind neighbours
    groups: list[list[list]] = []
    for a, b, kind in spans:
        if groups and a - groups[-1][-1][1] <= adjacent:
            last = groups[-1][-1]
            if last[2] == kind:
                last[1] = max(last[1], b)
            else:
                mid = (last[1] + a) // 2 if a > last[1] else last[1]
                last[1], a = mid, mid
                groups[-1].append([a, b, kind])
        else:
            groups.append([[a, b, kind]])
    keep = np.zeros(n, dtype=np.float32)
    w_ext = np.zeros(n, dtype=np.float32)
    for g in groups:
        ga, gb = g[0][0], g[-1][1]
        keep[ga:gb] = 1.0
        for a, b, kind in g:
            if kind == "ext":
                w_ext[a:b] = 1.0
        for (a1, b1, k1), (a2, b2, k2) in zip(g, g[1:]):
            f = min(fade, (b1 - a1) // 2, (b2 - a2) // 2)
            if f < 2:
                continue
            lo = b1 - f // 2
            hi = lo + f
            r = _ramp(f).astype(np.float32)
            w_ext[lo:hi] = r if k2 == "ext" else r[::-1]
        f = min(fade, (gb - ga) // 2)
        if f > 0:
            r = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, f, endpoint=False))).astype(np.float32)
            if ga > 0:
                keep[ga:ga + f] = r
            if gb < n:
                keep[gb - f:gb] = r[::-1]
    out = keep * (w_ext * ext_audio + (1.0 - w_ext) * x)
    return fit_samples(out, SAMPLE_RATE, SAMPLE_RATE, n)


# --------------------------------------------------------------- the hybrid
class HybridExtractor:
    """``extract(samples, regions)`` like the gated baseline, plus overlap extraction."""

    def __init__(self, extractor: OverlapExtractor, voiceprint: Voiceprint, enrollment, embedder,
                 config: HybridConfig | None = None, match: MatchConfig | None = None):
        self.extractor, self.voiceprint, self.enrollment = extractor, voiceprint, enrollment
        self.embedder = embedder
        self.config = config or HybridConfig()
        self.match = match or MatchConfig.for_embedder(embedder.name)
        self.name = f"hybrid[{extractor.info.name}]"
        self.last_report: dict = {}

    @property
    def threshold(self) -> float:
        t = self.config.accept_threshold
        return self.match.target_threshold if t is None else t

    # -- batched extraction with out-of-memory back-off
    def _run_windows(self, x, windows):
        cfg, ex = self.config, self.extractor
        window_s = max((e - s) for s, e in windows) / SAMPLE_RATE
        batch = cfg.batch_size or ex.max_batch(window_s, cfg.vram_budget_mib)
        outs, per_batch, details = [None] * len(windows), [], []
        order = sorted(range(len(windows)), key=lambda i: windows[i][1] - windows[i][0])
        pos, backoffs = 0, 0
        while pos < len(order):
            idx = order[pos:pos + batch]
            vram_reset()
            t = time.perf_counter()
            try:
                res = ex.extract_batch([x[windows[i][0]:windows[i][1]] for i in idx],
                                       self.voiceprint, self.enrollment)
            except BlockedError:
                raise
            except Exception as exc:
                if not is_oom(exc):
                    raise
                release_gpu()
                if batch == 1:
                    raise BlockedError("the extractor ran out of GPU memory even for one window",
                                       "out_of_memory", f"{type(exc).__name__}: {exc}") from exc
                batch, backoffs = max(1, batch // 2), backoffs + 1
                continue
            dt = time.perf_counter() - t
            for i, o in zip(idx, res):
                outs[i] = o
            details += list(ex.last_details)[:len(idx)] if ex.last_details else [{}] * len(idx)
            per_batch.append({"windows": len(idx), "seconds": round(dt, 4),
                              "seconds_per_window": round(dt / len(idx), 4),
                              "peak_vram_mib": vram_peak_mib()})
            pos += len(idx)
        return outs, per_batch, {"batch_size": batch, "oom_backoffs": backoffs, "details": details}

    def extract(self, samples, regions: list[LabelledRegion]) -> np.ndarray:
        cfg = self.config
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        n, sr = len(x), SAMPLE_RATE
        ov = overlap_spans(regions, n, sr)
        window = int(round(cfg.window_s * sr))
        plans = [plan_region_windows(a, b, n, window, cfg.window_overlap) for a, b in ov]
        flat = [w for p in plans for w in p]
        t0 = time.perf_counter()
        outs, per_batch, meta = ([], [], {"batch_size": None, "oom_backoffs": 0, "details": []}) \
            if not flat else self._run_windows(x, flat)
        extract_s = time.perf_counter() - t0
        # per-region estimate over [a, b), crossfading the windows of long regions
        ext_audio = np.zeros(n, dtype=np.float32)
        cursor, ext_spans, region_log = 0, [], []
        min_check = int(round(cfg.min_check_s * sr))
        for (a, b), wins in zip(ov, plans):
            ests = outs[cursor:cursor + len(wins)]
            cursor += len(wins)
            if len(wins) == 1 and wins[0][1] - wins[0][0] >= b - a:
                est = ests[0][a - wins[0][0]:b - wins[0][0]]
            else:
                est = merge_windows(ests, [(s - a, e - a) for s, e in wins], b - a)
            ext_audio[a:b] = est
            for ca, cb in split_check_chunks(a, b, int(cfg.check_chunk_s * sr), min_check):
                rec = self._check_piece(ext_audio, ca, cb, min_check)
                region_log.append(rec)
                if rec["status"] == "extracted":
                    ext_spans.append((ca, cb))
        tgt = merge_spans([(max(0, int(round(r.start * sr))), min(n, int(round(r.end * sr))))
                           for r in regions if r.label == TARGET])
        out = compose(x, tgt, merge_spans(ext_spans), ext_audio,
                      int(cfg.fade_ms * sr / 1000), int(cfg.adjacent_ms * sr / 1000))
        peaks = [b["peak_vram_mib"] for b in per_batch if b["peak_vram_mib"] is not None]
        ov_s = sum(b - a for a, b in ov) / sr
        self.last_report = {
            "extractor": self.extractor.info.name, "mechanism": self.extractor.info.mechanism,
            "accept_threshold": round(self.threshold, 4), "fp16": self.extractor.use_fp16,
            "fp16_fallbacks": self.extractor.fp16_fallbacks,
            "windows": len(flat), "overlap_regions": len(ov), "overlap_seconds": round(ov_s, 3),
            "extract_seconds": round(extract_s, 4),
            "seconds_per_window": round(extract_s / len(flat), 4) if flat else None,
            "rtf_overlap": round(extract_s / ov_s, 4) if ov_s else None,
            "peak_vram_mib": max(peaks) if peaks else None,
            "batches": per_batch, "batch_size": meta["batch_size"], "oom_backoffs": meta["oom_backoffs"],
            "window_details": meta["details"], "pieces": region_log,
            "uncertain_muted_seconds": round(sum(
                (r["end"] - r["start"]) for r in region_log if r["status"] != "extracted"), 3),
        }
        return out

    def _check_piece(self, ext_audio, a, b, min_check) -> dict:
        sr = SAMPLE_RATE
        rec = {"start": round(a / sr, 3), "end": round(b / sr, 3), "label": UNCERTAIN, "score": None}
        piece = ext_audio[a:b]
        if b - a < min_check:
            return {**rec, "status": "muted", "reason": "too_short_to_verify"}
        if rms(piece) < SILENT_RMS:
            return {**rec, "status": "muted", "reason": "silent_output"}
        score = cosine(self.voiceprint.vector, self.embedder.embed(piece))
        rec["score"] = round(score, 4)
        if score < self.threshold:
            return {**rec, "status": "muted", "reason": "below_voiceprint_threshold"}
        return {**rec, "label": TARGET, "status": "extracted", "reason": "voiceprint_match"}
