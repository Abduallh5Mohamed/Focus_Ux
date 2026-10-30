"""Voice enrollment: one voiceprint format from three sources.

* a diarized speaker label,
* a manual time range,
* a separate voice recording file.

Every source needs a minimum of CLEAN speech (default 4 s): only this
speaker, no overlap, acceptable level, no clipping. Otherwise enrollment is
refused with a plain explanation; borderline samples enroll with a warning.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .embedder import Embedder, embed_segments
from .errors import EnrollmentError
from .preprocess import slice_samples
from .segments import intersect, subtract, total
from .types import SAMPLE_RATE, Diarization, Segment, Voiceprint


@dataclass
class EnrollmentConfig:
    min_clean_s: float = 4.0
    min_span_s: float = 0.5          # shorter clean fragments are ignored
    min_rms_dbfs: float = -45.0      # refuse below this (too quiet)
    warn_rms_dbfs: float = -35.0
    max_clip_fraction: float = 0.01  # refuse above this
    warn_clip_fraction: float = 0.001
    clip_level: float = 0.99
    max_foreign_fraction: float = 0.10   # other voices in a range/file: refuse above
    warn_overlap_fraction: float = 0.20  # speech lost to overlap: warn above
    warn_short_s: float = 8.0            # enrolled but thin: recommend more


def check_level(samples: np.ndarray, cfg: EnrollmentConfig) -> tuple[dict, list[str]]:
    x = np.asarray(samples, dtype=np.float64)
    rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
    dbfs = 20 * np.log10(rms) if rms > 0 else -120.0
    clip = float(np.mean(np.abs(x) >= cfg.clip_level)) if x.size else 0.0
    info = {"rms_dbfs": round(float(dbfs), 1), "clip_fraction": round(clip, 5)}
    if dbfs < cfg.min_rms_dbfs:
        raise EnrollmentError(
            f"The sample is too quiet ({dbfs:.0f} dBFS). Record closer to the microphone and try again.")
    if clip > cfg.max_clip_fraction:
        raise EnrollmentError(
            f"The sample is distorted ({clip:.1%} of it is clipped). Lower the volume and record again.")
    warns = []
    if dbfs < cfg.warn_rms_dbfs:
        warns.append(f"The sample is quiet ({dbfs:.0f} dBFS); matching may be less reliable.")
    if clip > cfg.warn_clip_fraction:
        warns.append(f"Slight clipping ({clip:.2%}); matching may be less reliable.")
    return info, warns


def _concat(samples, spans) -> np.ndarray:
    return np.concatenate([slice_samples(samples, s) for s in spans]) if spans else np.zeros(0, np.float32)


def _finalize(samples, spans, embedder: Embedder, cfg: EnrollmentConfig, source: dict,
              lost_overlap_s: float, speech_s: float) -> Voiceprint:
    spans = [s for s in spans if s.duration >= cfg.min_span_s]
    clean_s = total(spans)
    if clean_s < cfg.min_clean_s:
        raise EnrollmentError(
            f"Only {clean_s:.1f} s of clean speech was found; at least {cfg.min_clean_s:g} s of this "
            "voice speaking alone (no one else talking) is needed. Pick a longer or cleaner sample.")
    level, warns = check_level(_concat(samples, spans), cfg)
    if speech_s > 0 and lost_overlap_s / speech_s > cfg.warn_overlap_fraction:
        warns.append(f"{lost_overlap_s / speech_s:.0%} of this voice's speech overlapped with others "
                     "and was not used.")
    if clean_s < cfg.warn_short_s:
        warns.append(f"Only {clean_s:.1f} s of clean speech; {cfg.warn_short_s:g} s or more gives a "
                     "more reliable voiceprint.")
    vec, used = embed_segments(embedder, samples, spans)
    if vec is None:
        raise EnrollmentError("The clean speech fragments are too short to measure a voice.")
    return Voiceprint([float(v) for v in vec], embedder.name, used,
                      {**source, "level": level, "clean_spans": [s.as_dict() for s in spans]}, warns)


def _clean_spans(diar: Diarization, speaker: str) -> tuple[list[Segment], float, float]:
    """Own turns minus other speakers' turns and all overlaps."""
    own = [t for t in diar.turns if t.speaker == speaker]
    others = [t for t in diar.turns if t.speaker != speaker]
    clean = subtract(own, others + list(diar.overlaps))
    return clean, total(own), total(own) - total(clean)


def enroll_from_speaker(samples, diar: Diarization, speaker: str, embedder: Embedder,
                        cfg: EnrollmentConfig | None = None) -> Voiceprint:
    cfg = cfg or EnrollmentConfig()
    if speaker not in diar.speakers:
        raise EnrollmentError(f"No speaker {speaker!r} was found; available: {', '.join(diar.speakers) or 'none'}.")
    spans, speech_s, lost = _clean_spans(diar, speaker)
    return _finalize(samples, spans, embedder, cfg, {"kind": "speaker_label", "speaker": speaker},
                     lost, speech_s)


def enroll_from_range(samples, diar: Diarization, start: float, end: float, embedder: Embedder,
                      cfg: EnrollmentConfig | None = None, *, source_kind: str = "time_range",
                      extra_source: dict | None = None) -> Voiceprint:
    cfg = cfg or EnrollmentConfig()
    if end <= start:
        raise EnrollmentError("The time range is empty.")
    window = [Segment(start, end)]
    turns = [Segment(s.start, s.end, t.speaker) for t in diar.turns for s in intersect([t], window)]
    if not turns:
        raise EnrollmentError("No speech was found in that time range.")
    by_spk: dict[str, float] = {}
    for t in turns:
        by_spk[t.speaker] = by_spk.get(t.speaker, 0.0) + t.duration
    dominant = max(by_spk, key=by_spk.get)
    speech_s = sum(by_spk.values())
    foreign = (speech_s - by_spk[dominant]) / speech_s
    if foreign > cfg.max_foreign_fraction:
        raise EnrollmentError(
            f"{foreign:.0%} of the speech in this sample comes from other voices. Use a sample of "
            "one person speaking alone.")
    own = [t for t in turns if t.speaker == dominant]
    cuts = [t for t in turns if t.speaker != dominant] + intersect(diar.overlaps, window)
    spans = subtract(own, cuts)
    return _finalize(samples, spans, embedder, cfg,
                     {"kind": source_kind, "start": start, "end": end, **(extra_source or {})},
                     total(own) - total(spans), total(own))


def enroll_from_file(file_samples, file_diar: Diarization, embedder: Embedder,
                     cfg: EnrollmentConfig | None = None, name: str = "") -> Voiceprint:
    """A separate voice recording: the whole file is the range."""
    dur = len(file_samples) / SAMPLE_RATE
    return enroll_from_range(file_samples, file_diar, 0.0, dur, embedder, cfg,
                             source_kind="voice_file", extra_source={"file": name})


def best_clean_spans(diar: Diarization, max_len: float = 8.0, min_len: float = 1.0) -> dict:
    """Per speaker: the longest clean span (no other voice, no overlap), trimmed
    to ``max_len`` around its middle; None when no clean span is long enough."""
    out: dict[str, dict | None] = {}
    for spk in diar.speakers:
        spans, _, _ = _clean_spans(diar, spk)
        spans = [s for s in spans if s.duration >= min_len]
        if not spans:
            out[spk] = None
            continue
        best = max(spans, key=lambda s: s.duration)
        if best.duration > max_len:
            mid = (best.start + best.end) / 2
            best = Segment(mid - max_len / 2, mid + max_len / 2, spk)
        out[spk] = {**best.as_dict(), "duration": round(best.duration, 3)}
    return out
