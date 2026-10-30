"""The audio-only engine used by the app (analysis, enrollment, isolation).

Validated components only (docs/VOICE_PIPELINE_LOG.md, docs/OVERLAP_EXTRACTION.md):
pyannote community-1 diarization, the ECAPA or pyannote embedder with the
provisional thresholds, and the gated-baseline extractor. The overlap-extraction
candidates stay out: none has run on real weights, so none was validated.

Every method takes an AUDIO FILE. There is no video, frame, face or lip
parameter anywhere, so after enrollment nothing visual can reach the result.
No speech recognition runs here either.
"""
from __future__ import annotations

import base64
import io
import os
import time
import wave

import numpy as np

from ..isolation_engines import write_wav
from ..timing import duration_ms_from_samples
from ..types import EngineResult
from .diarizer import Diarizer
from .embedder import Embedder, embed_segments
from .enroll import (
    EnrollmentConfig, _clean_spans, best_clean_spans, check_level, enroll_from_file,
    enroll_from_range,
)
from .errors import EnrollmentError
from .extractor import Extractor, GatedBaseline
from .match import MatchConfig, classify_regions
from .preprocess import load_canonical, slice_samples
from .segments import total
from .types import SAMPLE_RATE, TARGET, UNCERTAIN, Diarization, Segment, Voiceprint

ENGINE_NAME = "audio_only"
MAX_SPEAKERS = 8


def _wav_b64(samples) -> str:
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1, 1) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class AudioOnlyEngine:
    name = ENGINE_NAME

    def __init__(self, diarizer: Diarizer, embedder: Embedder, *,
                 match: MatchConfig | None = None, extractor: Extractor | None = None,
                 enrollment: EnrollmentConfig | None = None):
        self.diarizer, self.embedder = diarizer, embedder
        self.match = match or MatchConfig.for_embedder(embedder.name)
        self.extractor = extractor or GatedBaseline()
        self.enrollment = enrollment or EnrollmentConfig()

    @classmethod
    def from_env(cls, env=None) -> "AudioOnlyEngine":
        """Real models. Imports stay light until a method runs."""
        from .diarizer import PyannoteDiarizer
        from .embedder import build_embedder
        source = os.environ if env is None else env
        return cls(PyannoteDiarizer(), build_embedder(source.get("FOCUS_VOICE_EMBEDDER") or "ecapa"))

    # -- analysis -----------------------------------------------------------
    def _speaker_quality(self, samples, diar: Diarization, speaker: str):
        spans, speech_s, lost = _clean_spans(diar, speaker)
        spans = [s for s in spans if s.duration >= self.enrollment.min_span_s]
        clean_s = total(spans)
        cfg = self.enrollment
        warnings: list[str] = []
        refusal = None
        if clean_s < cfg.min_clean_s:
            refusal = (f"Only {clean_s:.1f} s of clean speech was found; at least {cfg.min_clean_s:g} s "
                       "of this voice speaking alone is needed.")
        else:
            try:
                _, level_warnings = check_level(
                    np.concatenate([slice_samples(samples, s) for s in spans]), cfg)
                warnings += level_warnings
            except EnrollmentError as exc:
                refusal = exc.message
            if clean_s < cfg.warn_short_s:
                warnings.append(f"Only {clean_s:.1f} s of clean speech; {cfg.warn_short_s:g} s or more "
                                "gives a more reliable voiceprint.")
        overlap_fraction = (lost / speech_s) if speech_s > 0 else 0.0
        if overlap_fraction > cfg.warn_overlap_fraction:
            warnings.append(f"{overlap_fraction:.0%} of this voice's speech overlaps with others "
                            "and is not used.")
        return clean_s, speech_s, overlap_fraction, refusal, warnings

    def analyze(self, audio_path: str, on_progress=None) -> dict:
        """Diarization, one voiceprint per speaker, the best clean sample span
        and its audio clip. Computed once per video; the app caches it."""
        t0 = time.perf_counter()
        samples = load_canonical(audio_path)
        diar = self.diarizer.diarize(samples)
        self.diarizer.unload()
        if on_progress:
            on_progress("analyzing", 0.5)
        best = best_clean_spans(diar)
        by_speech = sorted(diar.speakers, key=lambda s: -total([t for t in diar.turns if t.speaker == s]))
        kept = by_speech[:MAX_SPEAKERS]
        speakers = []
        for speaker in kept:
            clean_s, speech_s, overlap, refusal, warnings = self._speaker_quality(samples, diar, speaker)
            voiceprint, sample, clip = None, best.get(speaker), None
            if refusal is None:
                spans, _, _ = _clean_spans(diar, speaker)
                spans = [s for s in spans if s.duration >= self.enrollment.min_span_s]
                vec, used = embed_segments(self.embedder, samples, spans)
                if vec is None:
                    refusal = "The clean speech fragments are too short to measure a voice."
                else:
                    voiceprint = Voiceprint(
                        [float(v) for v in vec], self.embedder.name, used,
                        {"kind": "speaker_label", "speaker": speaker}, warnings).as_dict()
            if sample is not None:
                clip = _wav_b64(slice_samples(samples, Segment(sample["start"], sample["end"])))
            speakers.append({
                "speaker": speaker, "speech_s": round(speech_s, 3), "clean_s": round(clean_s, 3),
                "overlap_fraction": round(overlap, 4), "usable": refusal is None,
                "refusal": refusal, "warnings": warnings, "sample": sample,
                "sample_wav_b64": clip, "voiceprint": voiceprint,
            })
        self.embedder.unload()
        warnings = []
        if len(diar.speakers) > MAX_SPEAKERS:
            warnings.append(f"{len(diar.speakers)} voices were found; the {MAX_SPEAKERS} who speak most are listed.")
        if not diar.speakers:
            warnings.append("No speech was found in the audio.")
        return {
            "duration_ms": duration_ms_from_samples(len(samples), SAMPLE_RATE),
            "diarization": diar.as_dict(), "speakers": speakers, "warnings": warnings,
            "embedder": self.embedder.name, "seconds": round(time.perf_counter() - t0, 2),
        }

    # -- enrollment (manual range / separate recording) --------------------
    def enroll_range(self, audio_path: str, diarization: dict, start_s: float, end_s: float) -> dict:
        samples = load_canonical(audio_path)
        vp = enroll_from_range(samples, Diarization.from_dict(diarization), start_s, end_s,
                               self.embedder, self.enrollment)
        self.embedder.unload()
        return {"voiceprint": vp.as_dict(), "warnings": vp.warnings}

    def enroll_file(self, audio_path: str, name: str = "") -> dict:
        samples = load_canonical(audio_path)
        diar = self.diarizer.diarize(samples)
        self.diarizer.unload()
        if not diar.turns:
            raise EnrollmentError("No speech was found in the recording.")
        vp = enroll_from_file(samples, diar, self.embedder, self.enrollment, name)
        self.embedder.unload()
        return {"voiceprint": vp.as_dict(), "warnings": vp.warnings}

    # -- isolation -----------------------------------------------------------
    def isolate(self, audio_path: str, voiceprint: dict, diarization: dict, job_dir: str,
                on_progress=None) -> EngineResult:
        """Audio + enrollment + the cached diarization in; isolated.wav and the
        labelled timeline out. Overlap and unmatched speech are muted."""
        t0 = time.perf_counter()
        samples = load_canonical(audio_path)
        enrollment = Voiceprint.from_dict(voiceprint)
        diar = Diarization.from_dict(diarization)
        if on_progress:
            on_progress("matching", 0.0)
        regions = classify_regions(samples, diar, enrollment, self.embedder, self.match)
        self.embedder.unload()
        if on_progress:
            on_progress("matching", 1.0)
            on_progress("separating", 0.0)
        out = self.extractor.extract(samples, regions)
        path = os.path.join(str(job_dir), "isolated.wav")
        write_wav(path, out, SAMPLE_RATE)
        if on_progress:
            on_progress("separating", 1.0)
        warnings = []
        target_s = total([Segment(r.start, r.end) for r in regions if r.label == TARGET])
        if target_s <= 0:
            warnings.append("The enrolled voice was not found in the audio; the result is silent.")
        return EngineResult(
            wav_path=path, duration_ms=duration_ms_from_samples(len(samples), SAMPLE_RATE),
            source_offset_ms=0, timings={"total": round(time.perf_counter() - t0, 2)},
            warnings=warnings, engine=ENGINE_NAME,
            details={"regions": [r.as_dict() for r in regions if r.label in (TARGET, UNCERTAIN)]})


def regions_to_wire(regions: list[dict]) -> list[dict]:
    """Target / uncertain regions in milliseconds, adjacent equal labels merged."""
    items = sorted(({"start_ms": int(round(r["start"] * 1000)), "end_ms": int(round(r["end"] * 1000)),
                     "label": r["label"], "reason": r.get("reason", "")}
                    for r in regions if r["label"] in (TARGET, UNCERTAIN)),
                   key=lambda r: (r["start_ms"], r["end_ms"]))
    merged: list[dict] = []
    for item in items:
        last = merged[-1] if merged else None
        if last and last["label"] == item["label"] and item["start_ms"] <= last["end_ms"]:
            last["end_ms"] = max(last["end_ms"], item["end_ms"])
        else:
            merged.append(dict(item))
    return merged
