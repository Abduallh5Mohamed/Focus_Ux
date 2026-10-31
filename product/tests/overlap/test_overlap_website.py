"""WeSep in the website flow: reference audio per enrollment type and the routing summary.
Tone fakes only; nothing here is model or GPU evidence."""
import base64
import io
import wave

import numpy as np

from fakes import SR, FakeDiarizer, FakeEmbedder, scene
from helpers import ToneExtractor
from focus_ml.isolation_engines import write_wav
from focus_ml.voice.engine import AudioOnlyEngine
from focus_ml.voice.extractor import GatedBaseline
from focus_ml.voice.preprocess import load_canonical
from focus_ml.voice.routing import CONTINUITY, RoutingConfig, summarize_routing

TURNS = [("A", 0.0, 8.0), ("B", 8.0, 12.0), ("A", 12.0, 16.0), ("A", 16.0, 18.0), ("B", 16.0, 18.0)]


def engine(**kw):
    return AudioOnlyEngine(FakeDiarizer(TURNS), FakeEmbedder(), **kw)


def recording(tmp_path):
    path = tmp_path / "s.wav"
    write_wav(str(path), scene(TURNS, 18.0), 16000)
    return str(path), load_canonical(str(path))


def analysis(e, path):
    a = e.analyze(path)
    return a, next(s for s in a["speakers"] if s["speaker"] == "A")["voiceprint"]


def test_speaker_label_enrollment_rebuilds_reference(tmp_path):
    path, x = recording(tmp_path)
    e = engine(overlap_extractor=ToneExtractor())
    a, vp = analysis(e, path)
    res = e.isolate(path, vp, a["diarization"], str(tmp_path))
    s = res.details["routing_summary"]
    assert s["extractor_ran"] and s["pieces_extracted"] >= 1 and s["overlap_seconds"] > 0


def test_time_range_enrollment_rebuilds_reference(tmp_path):
    path, x = recording(tmp_path)
    e = engine(overlap_extractor=ToneExtractor())
    a, _ = analysis(e, path)
    vp = e.enroll_range(path, a["diarization"], 0.0, 7.0)["voiceprint"]
    assert vp["source"]["kind"] == "time_range" and vp["source"]["clean_spans"]
    res = e.isolate(path, vp, a["diarization"], str(tmp_path))
    assert res.details["routing_summary"]["extractor_ran"]
    assert "overlap_error" not in res.details["routing_summary"]


def make_voice_file(tmp_path):
    path = tmp_path / "voice.wav"
    write_wav(str(path), scene([("A", 0, 6)], 6.0), 16000)
    solo = AudioOnlyEngine(FakeDiarizer([("A", 0.0, 6.0)]), FakeEmbedder())
    return solo.enroll_file(str(path), "voice.wav")


def test_voice_file_enrollment_carries_clean_reference_audio(tmp_path):
    result = make_voice_file(tmp_path)
    raw = base64.b64decode(result["reference_wav_b64"])
    with wave.open(io.BytesIO(raw), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
        assert 4.0 <= w.getnframes() / 16000 <= 10.0
    path, x = recording(tmp_path)
    e = engine(overlap_extractor=ToneExtractor())
    a, _ = analysis(e, path)
    vp = result["voiceprint"]
    ref = np.frombuffer(raw[44:], dtype="<i2").astype(np.float32) / 32768
    res = e.isolate(path, vp, a["diarization"], str(tmp_path), reference_audio=ref)
    assert res.details["routing_summary"]["extractor_ran"]
    # Without the reference there is no clean audio: skipped, with a stated reason.
    res = e.isolate(path, vp, a["diarization"], str(tmp_path))
    s = res.details["routing_summary"]
    assert not s["extractor_ran"] and s["overlap_extraction"] == "skipped"
    assert "enrollment audio" in s["reason"] and s["extractor_requested"] == "fake"


def test_default_off_output_equals_gated_baseline(tmp_path):
    path, x = recording(tmp_path)
    e = engine()
    a, vp = analysis(e, path)
    res = e.isolate(path, vp, a["diarization"], str(tmp_path))
    from focus_ml.voice.match import classify_regions
    from focus_ml.voice.types import Diarization, Voiceprint
    regions = classify_regions(x, Diarization.from_dict(a["diarization"]), Voiceprint.from_dict(vp),
                               e.embedder, e.match)
    baseline = tmp_path / "baseline.wav"
    write_wav(str(baseline), GatedBaseline().extract(x, regions), 16000)   # same WAV rounding
    assert np.array_equal(load_canonical(res.wav_path), load_canonical(str(baseline)))
    s = res.details["routing_summary"]
    assert (s["extractor_requested"], s["extractor_ran"], s["overlap_extraction"]) == (None, False, "disabled")
    assert s["isolation_claim"] == "strict_isolation" and s["fallback_used"] is False


def test_continuity_fallback_is_never_called_isolation(tmp_path):
    path, _ = recording(tmp_path)
    e = engine(routing=RoutingConfig(mode=CONTINUITY))
    a, vp = analysis(e, path)
    s = e.isolate(path, vp, a["diarization"], str(tmp_path)).details["routing_summary"]
    assert s["fallback_used"] and s["fallback_seconds"] > 0 and s["isolation_claim"] == "not_isolation"


def test_summary_lists_each_region_with_route_and_status(tmp_path):
    path, _ = recording(tmp_path)
    e = engine(overlap_extractor=ToneExtractor())
    a, vp = analysis(e, path)
    s = e.isolate(path, vp, a["diarization"], str(tmp_path)).details["routing_summary"]
    assert s["regions"] and all({"start_ms", "end_ms", "route", "status"} <= r.keys() for r in s["regions"])
    got = [r for r in s["regions"] if r["status"] == "extracted"]
    assert got and all(r["route"] == "fake" for r in got)
    assert all(r["route"] == "strict_muting" for r in s["regions"] if r["status"] != "extracted")
    assert summarize_routing(None)["overlap_extraction"] == "disabled"


def test_summary_counts_overlap_when_extraction_is_disabled_skipped_or_failed(tmp_path):
    from focus_ml.overlap.base import BlockedError
    path, _ = recording(tmp_path)

    def summary(**kw):
        e = engine(**kw)
        a, vp = analysis(e, path)
        return e.isolate(path, vp, a["diarization"], str(tmp_path)).details["routing_summary"], vp, a, e

    s, vp, a, e = summary()                                        # disabled
    assert s["overlap_seconds"] == 2.0 and s["muted_seconds"] == 2.0 and s["pieces_muted"] == 1
    assert s["overlap_extraction"] == "disabled" and not s["extractor_ran"]

    class Blocked(ToneExtractor):
        def _extract_batch(self, *a):
            raise BlockedError("blocked", "missing_weights", "x")
    s, *_ = summary(overlap_extractor=Blocked())                   # failed
    assert s["overlap_extraction"] == "failed" and s["overlap_seconds"] == 2.0 and s["pieces_muted"] == 1

    from focus_ml.voice.types import Voiceprint
    file_vp = dict(vp, source={"kind": "voice_file"})              # skipped: no reference
    e = engine(overlap_extractor=ToneExtractor())
    s = e.isolate(path, file_vp, a["diarization"], str(tmp_path)).details["routing_summary"]
    assert s["overlap_extraction"] == "skipped" and s["overlap_seconds"] == 2.0
