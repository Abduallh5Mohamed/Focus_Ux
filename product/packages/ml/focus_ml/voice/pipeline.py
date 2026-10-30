"""The audio-only pipeline. Inputs: audio samples + an enrollment voiceprint.

There is deliberately no video parameter anywhere: a video is reduced to its
audio track before it gets here (see preprocess.load_canonical).
Models run one at a time and are unloaded between stages.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .diarizer import Diarizer
from .embedder import Embedder, embed_segments
from .enroll import _clean_spans, best_clean_spans
from .extractor import Extractor, GatedBaseline
from .gpu import StageLog
from .match import MatchConfig, classify_regions
from .types import SAMPLE_RATE, Diarization, LabelledRegion, Voiceprint


@dataclass
class Analysis:
    diarization: Diarization
    speaker_voiceprints: dict[str, Voiceprint]
    best_spans: dict


@dataclass
class PipelineResult:
    analysis: Analysis
    regions: list[LabelledRegion]
    output: np.ndarray
    log: dict = field(default_factory=dict)


def analyze(samples, diarizer: Diarizer | None, embedder: Embedder, log: StageLog | None = None,
            diarization: Diarization | None = None) -> Analysis:
    """Diarize (unless given), then one voiceprint per speaker from clean speech."""
    log = log or StageLog()
    diar = diarization
    if diar is None:
        with log.stage("diarize"):
            diar = diarizer.diarize(samples)
        diarizer.unload()
    prints: dict[str, Voiceprint] = {}
    with log.stage("speaker_embeddings"):
        for spk in diar.speakers:
            spans, _, _ = _clean_spans(diar, spk)
            vec, used = embed_segments(embedder, samples, spans)
            if vec is not None:
                prints[spk] = Voiceprint([float(v) for v in vec], embedder.name, used,
                                         {"kind": "speaker_label", "speaker": spk})
    embedder.unload()
    return Analysis(diar, prints, best_clean_spans(diar))


def run_pipeline(samples, enrollment: Voiceprint, *, diarization: Diarization | None = None,
                 diarizer: Diarizer | None = None, embedder: Embedder,
                 match: MatchConfig | None = None, extractor: Extractor | None = None,
                 log: StageLog | None = None) -> PipelineResult:
    """Audio + enrollment in; labelled timeline + gated-baseline audio out.
    Pass a precomputed ``diarization`` or a ``diarizer``."""
    log = log or StageLog()
    x = np.asarray(samples, dtype=np.float32)
    if diarization is None:
        if diarizer is None:
            raise ValueError("a diarization or a diarizer is required")
        with log.stage("diarize"):
            diarization = diarizer.diarize(x)
        diarizer.unload()
    with log.stage("match"):
        regions = classify_regions(x, diarization, enrollment, embedder, match)
    embedder.unload()
    with log.stage("extract"):
        out = (extractor or GatedBaseline()).extract(x, regions)
    audio_s = len(x) / SAMPLE_RATE
    summary = log.as_dict()
    summary["audio_seconds"] = round(audio_s, 3)
    summary["real_time_factor"] = round(summary["total_seconds"] / audio_s, 3) if audio_s else None
    return PipelineResult(Analysis(diarization, {}, best_clean_spans(diarization)), regions, out, summary)
