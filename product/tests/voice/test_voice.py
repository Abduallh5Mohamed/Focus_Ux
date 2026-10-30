import inspect
import shutil
import subprocess

import numpy as np
import pytest

from focus_ml.errors import ModelUnavailableError
from focus_ml.voice import diarizer as diarizer_mod
from focus_ml.voice import embedder as embedder_mod
from focus_ml.voice import pipeline as pipeline_mod
from focus_ml.voice import enroll as enroll_mod
from focus_ml.voice.diarizer import CachedDiarizer, from_turns
from focus_ml.voice.enroll import (EnrollmentConfig, best_clean_spans, enroll_from_file,
                                   enroll_from_range, enroll_from_speaker)
from focus_ml.voice.errors import EnrollmentError
from focus_ml.voice.extractor import GatedBaseline, target_mask
from focus_ml.voice.match import MatchConfig, classify_regions, classify_score
from focus_ml.voice.pipeline import run_pipeline
from focus_ml.voice.preprocess import load_canonical
from focus_ml.voice.segments import overlaps_from_turns, subtract
from focus_ml.voice.types import OTHER, TARGET, UNCERTAIN, LabelledRegion, Segment, Voiceprint
from focus_ml.voice.weights import require_weights, weight_status, DIARIZER_REPO, ECAPA_REPO

from fakes import SR, FakeDiarizer, FakeEmbedder, scene

TURNS = [("A", 0.0, 6.0), ("B", 6.0, 12.0)]


def _diar(turns=TURNS):
    return from_turns([Segment(a, b, s) for s, a, b in turns])


# --- segments
def test_subtract_and_overlaps():
    turns = [Segment(0, 5, "A"), Segment(4, 8, "B")]
    ov = overlaps_from_turns(turns)
    assert [(o.start, o.end) for o in ov] == [(4, 5)]
    left = subtract([Segment(0, 5, "A")], [Segment(1, 2), Segment(4, 9)])
    assert [(s.start, s.end) for s in left] == [(0, 1), (2, 4)]


# --- enrollment rules
def test_enroll_from_speaker_ok_and_format_roundtrip():
    x = scene([("A", 0, 6), ("B", 6, 12)], 12)
    vp = enroll_from_speaker(x, _diar(), "SPEAKER" if False else "A", FakeEmbedder())
    assert vp.duration_s == pytest.approx(6.0, abs=0.01)
    assert Voiceprint.from_dict(vp.as_dict()).vector == vp.vector


def test_enroll_refuses_short_clean_speech_and_min_is_configurable():
    x = scene([("A", 0, 3), ("B", 3, 12)], 12)
    diar = _diar([("A", 0, 3), ("B", 3, 12)])
    with pytest.raises(EnrollmentError, match="at least 4"):
        enroll_from_speaker(x, diar, "A", FakeEmbedder())
    vp = enroll_from_speaker(x, diar, "A", FakeEmbedder(), EnrollmentConfig(min_clean_s=2.0))
    assert vp.duration_s == pytest.approx(3.0, abs=0.01)


def test_enroll_excludes_overlap_from_clean_time():
    plan = [("A", 0, 8), ("B", 4, 12)]
    diar = _diar(plan)
    vp = enroll_from_speaker(scene(plan, 12), diar, "A", FakeEmbedder())
    assert vp.duration_s == pytest.approx(4.0, abs=0.01)   # 0-4 only
    assert any("overlap" in w for w in vp.warnings)


def test_enroll_level_and_clipping_checks():
    diar = _diar([("A", 0, 6)])
    with pytest.raises(EnrollmentError, match="too quiet"):
        enroll_from_speaker(scene([("A", 0, 6)], 6, amp=0.0005), diar, "A", FakeEmbedder())
    loud = np.clip(scene([("A", 0, 6)], 6, amp=3.0), -1, 1)
    with pytest.raises(EnrollmentError, match="distorted"):
        enroll_from_speaker(loud, diar, "A", FakeEmbedder())
    vp = enroll_from_speaker(scene([("A", 0, 6)], 6, amp=0.01), diar, "A", FakeEmbedder())
    assert any("quiet" in w for w in vp.warnings)


def test_enroll_unknown_speaker_and_range_with_other_voices():
    x = scene(TURNS, 12)
    with pytest.raises(EnrollmentError, match="available"):
        enroll_from_speaker(x, _diar(), "Z", FakeEmbedder())
    with pytest.raises(EnrollmentError, match="other voices"):
        enroll_from_range(x, _diar([("A", 0, 6), ("B", 6, 12)]), 2.0, 10.0, FakeEmbedder())
    vp = enroll_from_range(x, _diar(), 0.5, 5.5, FakeEmbedder())
    assert vp.source["kind"] == "time_range"


def test_enroll_from_file():
    f = scene([("B", 0, 5)], 5)
    vp = enroll_from_file(f, _diar([("B", 0, 5)]), FakeEmbedder(), name="me.wav")
    assert vp.source["kind"] == "voice_file" and vp.duration_s == pytest.approx(5.0, abs=0.01)
    with pytest.raises(EnrollmentError):
        enroll_from_file(scene([("B", 0, 3)], 3), _diar([("B", 0, 3)]), FakeEmbedder())


def test_best_clean_span_per_speaker():
    spans = best_clean_spans(_diar([("A", 0, 20), ("B", 20, 22)]), max_len=8.0)
    assert spans["A"]["duration"] == 8.0 and spans["B"]["duration"] == 2.0
    assert best_clean_spans(_diar([("A", 0, 0.5)]))["A"] is None


# --- matching
def test_threshold_classification_and_validation():
    cfg = MatchConfig(target_threshold=0.6, other_threshold=0.3)
    assert classify_score(0.6, cfg) == TARGET
    assert classify_score(0.3, cfg) == OTHER
    assert classify_score(0.45, cfg) == UNCERTAIN
    with pytest.raises(ValueError):
        MatchConfig(target_threshold=0.2, other_threshold=0.5)


def test_regions_label_target_other_and_overlap_never_target():
    plan = [("A", 0, 6), ("B", 6, 12), ("A", 10, 12)]
    x = scene(plan, 12)
    diar = _diar(plan)
    emb = FakeEmbedder()
    vp = enroll_from_range(x, diar, 0.0, 5.0, emb)
    regions = classify_regions(x, diar, vp, emb, MatchConfig(0.8, 0.5))
    by = lambda lo, hi: {r.label for r in regions if r.start >= lo and r.end <= hi + 1e-6}
    assert by(0, 6) == {TARGET}
    assert by(6, 10) == {OTHER}
    assert all(r.label == UNCERTAIN and r.reason == "overlap" for r in regions if r.start >= 10 - 1e-6)


def test_voiceprint_embedder_mismatch_refused():
    vp = Voiceprint([1.0, 0.0], "pyannote", 5.0, {})
    with pytest.raises(ValueError, match="enroll again"):
        classify_regions(scene(TURNS, 12), _diar(), vp, FakeEmbedder())


# --- gating, muting, length
def test_gated_baseline_mutes_non_target_keeps_length_and_fades():
    x = np.ones(SR * 4, dtype=np.float32) * 0.5
    regions = [LabelledRegion(1.0, 2.0, TARGET, "A", .9, ""), LabelledRegion(2.0, 3.0, OTHER, "B", .1, ""),
               LabelledRegion(3.0, 3.5, UNCERTAIN, "B", .4, "")]
    out = GatedBaseline().extract(x, regions)
    assert len(out) == len(x)
    assert np.all(out[:SR] == 0) and np.all(out[2 * SR:] == 0)
    assert out[SR + 3200] == pytest.approx(0.5)          # steady state in the middle
    assert 0 <= out[SR + 10] < 0.5                        # ramp inside the region
    assert out[SR - 1] == 0 and out[2 * SR] == 0          # nothing leaks outside


def test_mask_merges_adjacent_target_regions_and_clips_to_length():
    r = [LabelledRegion(0.0, 1.0, TARGET, "A", .9, ""), LabelledRegion(1.0, 9.0, TARGET, "A", .9, "")]
    m = target_mask(SR * 2, r)
    assert len(m) == SR * 2 and m[SR] == 1.0 and m[SR * 2 - 100] == 1.0


# --- pipeline, enrollment sources, audio-only invariance
def test_pipeline_end_to_end_with_fakes_unloads_each_stage():
    plan = [("A", 0, 6), ("B", 6, 12)]
    x = scene(plan, 12)
    emb, dia = FakeEmbedder(), FakeDiarizer(plan)
    vp = enroll_from_range(x, _diar(plan), 0, 6, emb)
    res = run_pipeline(x, vp, diarizer=dia, embedder=emb, match=MatchConfig(0.8, 0.5))
    assert len(res.output) == len(x)
    assert np.abs(res.output[:6 * SR]).max() > 0.1 and np.abs(res.output[6 * SR:]).max() == 0
    assert dia.unloaded == 1 and emb.unloaded >= 1
    assert {"diarize", "match", "extract"} <= set(res.log["stages"])


def test_pipeline_api_has_no_video_input():
    for fn in (pipeline_mod.run_pipeline, pipeline_mod.analyze, enroll_mod.enroll_from_speaker,
               enroll_mod.enroll_from_range, enroll_mod.enroll_from_file, classify_regions):
        assert not [p for p in inspect.signature(fn).parameters if "video" in p.lower()]


@pytest.mark.skipif(not (shutil.which("ffmpeg")), reason="ffmpeg needed")
def test_same_output_with_original_blacked_out_or_no_video(tmp_path):
    import wave
    plan = [("A", 0, 6), ("B", 6, 12)]
    x = scene(plan, 12)
    wav = tmp_path / "a.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())

    def make(name, vf):
        out = tmp_path / name
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"testsrc=size=64x64:rate=25:duration=12", "-i", str(wav), "-vf", vf,
                        "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(out)], check=True)
        return out
    original, black = make("orig.mkv", "null"), make("black.mkv", "drawbox=t=fill:color=black:w=64:h=64")
    outputs = []
    for src in (original, black, wav):                 # video, blacked-out video, no video
        audio = load_canonical(str(src))
        emb = FakeEmbedder()
        vp = enroll_from_range(audio, _diar(plan), 0, 6, emb)
        res = run_pipeline(audio, vp, diarization=_diar(plan), embedder=emb, match=MatchConfig(0.8, 0.5))
        outputs.append((vp.vector, [r.as_dict() for r in res.regions], res.output.tobytes()))
    assert outputs[0] == outputs[1] == outputs[2]


# --- missing weights, cache
def test_missing_weights_raise_clear_errors(tmp_path):
    assert not any(weight_status(tmp_path).values())
    for repo in (DIARIZER_REPO, ECAPA_REPO):
        with pytest.raises(ModelUnavailableError, match="setup"):
            require_weights(repo, tmp_path)
    emb = embedder_mod.EcapaEmbedder("cpu", tmp_path)
    with pytest.raises(ModelUnavailableError):
        emb.load()
    with pytest.raises(ModelUnavailableError):
        diarizer_mod.load_pyannote_pipeline("cpu", tmp_path)


def test_incomplete_download_is_not_ready(tmp_path):
    d = tmp_path / "weights" / ECAPA_REPO.replace("/", "__")
    d.mkdir(parents=True)
    (d / "hyperparams.yaml").write_text("x")
    (d / "embedding_model.ckpt").write_text("x")           # no completion marker
    assert not weight_status(tmp_path)[ECAPA_REPO]


def test_diarization_cached_per_audio(tmp_path):
    inner = FakeDiarizer(TURNS)
    cd = CachedDiarizer(inner, tmp_path)
    x = scene(TURNS, 12)
    a, b = cd.diarize(x), cd.diarize(x.copy())
    assert inner.calls == 1 and cd.hits == 1 and a.as_dict() == b.as_dict()
    cd.diarize(x[: 11 * SR])
    assert inner.calls == 2
