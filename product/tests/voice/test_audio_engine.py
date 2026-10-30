"""The app's audio-only engine with the deterministic tone fakes (no model weights).

The visibility-independence test runs the real extraction path: ffmpeg audio
extraction (as the API does), then AudioOnlyEngine analyze / enroll / isolate.
Only the diarizer and embedder are small test models (tones), not the engine."""
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from fakes import FakeDiarizer, FakeEmbedder, scene

PRODUCT = str(Path(__file__).resolve().parents[2])
if PRODUCT not in sys.path:
    sys.path.insert(0, PRODUCT)

from focus_ml.isolation_engines import write_wav  # noqa: E402
from focus_ml.voice.engine import AudioOnlyEngine, regions_to_wire  # noqa: E402
from focus_ml.voice.errors import EnrollmentError  # noqa: E402
from focus_ml.voice.preprocess import load_canonical  # noqa: E402
from focus_ml.voice.visibility import iou, track_visibility  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
TURNS = [("A", 0.0, 6.0), ("B", 6.0, 12.0), ("A", 12.0, 16.0), ("A", 16.0, 18.0), ("B", 16.0, 18.0)]
TOTAL_S = 18.0


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "scene.wav"
    write_wav(str(path), scene(TURNS, TOTAL_S), 16000)
    return str(path)


def engine():
    return AudioOnlyEngine(FakeDiarizer(TURNS), FakeEmbedder())


def test_analysis_lists_voices_with_clean_samples_and_overlap_warning(audio):
    result = engine().analyze(audio)
    by = {s["speaker"]: s for s in result["speakers"]}
    assert set(by) == {"A", "B"} and result["embedder"] == "ecapa"
    assert by["A"]["usable"] and by["A"]["voiceprint"]["format"] == "focus-voiceprint/1"
    # B speaks 6 s alone plus 2 s inside an overlap that is not used.
    assert by["B"]["overlap_fraction"] == pytest.approx(0.25, abs=0.01)
    assert any("overlap" in w for w in by["B"]["warnings"])
    assert by["A"]["sample"]["end"] - by["A"]["sample"]["start"] <= 8.0
    assert by["A"]["sample_wav_b64"] and result["duration_ms"] == 18000
    json.dumps(result)  # wire-safe


def test_too_short_voice_is_marked_unusable():
    turns = [("A", 0.0, 10.0), ("B", 10.0, 11.5)]
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.wav")
        write_wav(path, scene(turns, 12.0), 16000)
        result = AudioOnlyEngine(FakeDiarizer(turns), FakeEmbedder()).analyze(path)
    b = next(s for s in result["speakers"] if s["speaker"] == "B")
    assert b["usable"] is False and b["voiceprint"] is None and "at least" in b["refusal"]


def test_enroll_range_refuses_short_and_mixed_ranges(audio):
    e = engine()
    diar = e.analyze(audio)["diarization"]
    ok = e.enroll_range(audio, diar, 0.0, 6.0)
    assert ok["voiceprint"]["source"]["kind"] == "time_range"
    with pytest.raises(EnrollmentError):
        e.enroll_range(audio, diar, 0.0, 2.0)  # under 4 s of speech
    with pytest.raises(EnrollmentError):
        e.enroll_range(audio, diar, 3.0, 9.0)  # half the range is another voice
    with pytest.raises(EnrollmentError):
        e.enroll_range(audio, diar, 5.0, 5.0)


def test_isolate_keeps_target_mutes_others_and_labels_uncertain(audio, tmp_path):
    e = engine()
    analysis = e.analyze(audio)
    vp = next(s for s in analysis["speakers"] if s["speaker"] == "A")["voiceprint"]
    result = e.isolate(audio, vp, analysis["diarization"], str(tmp_path))
    out = load_canonical(result.wav_path)
    src = load_canonical(audio)
    assert len(out) == len(src) and result.engine == "audio_only" and result.source_offset_ms == 0
    sr = 16000
    assert np.abs(out[1 * sr:5 * sr]).max() > 0.2          # target speaks
    assert np.abs(out[7 * sr:11 * sr]).max() < 1e-3        # other voice muted
    assert np.abs(out[16 * sr:18 * sr]).max() < 1e-3       # overlap muted
    wire = regions_to_wire(result.details["regions"])
    assert wire and all(r["label"] in ("target", "uncertain") for r in wire)
    assert any(r["label"] == "target" and r["start_ms"] <= 1000 and r["end_ms"] >= 5000 for r in wire)
    assert all(a["end_ms"] <= b["start_ms"] for a, b in zip(wire, wire[1:]))


def test_isolate_has_no_video_parameter_at_all():
    import inspect
    for name in ("analyze", "enroll_range", "enroll_file", "isolate"):
        params = inspect.signature(getattr(AudioOnlyEngine, name)).parameters
        assert not {"video", "video_path", "frames", "face", "face_id", "bbox", "landmarks"} & set(params)


def test_embedder_mismatch_is_not_silently_accepted(audio, tmp_path):
    e = engine()
    analysis = e.analyze(audio)
    vp = dict(analysis["speakers"][0]["voiceprint"], embedder="other-model")
    with pytest.raises(Exception):
        e.isolate(audio, vp, analysis["diarization"], str(tmp_path))


# -- on-screen evidence (enrollment only) ------------------------------------
def test_tracker_follows_the_chosen_face_and_ignores_others():
    first = (100.0, 100.0, 50.0, 50.0)
    frames = [(t, t) for t in range(0, 6000, 500)]

    def detect(t):
        if t < 2000:
            return [(102.0, 101.0, 50.0, 50.0), (400.0, 100.0, 50.0, 50.0)]
        if t < 4000:
            return [(400.0, 100.0, 50.0, 50.0)]  # chosen face left; another person remains
        return [(104.0, 100.0, 50.0, 50.0)]
    spans = track_visibility(frames, detect, first)
    assert spans[0] == {"start_ms": 0, "end_ms": 2000}
    assert spans[-1]["start_ms"] == 4000 and spans[-1]["end_ms"] == 6000
    assert iou((0, 0, 10, 10), (20, 20, 10, 10)) == 0.0


# -- visibility independence --------------------------------------------------
def ff(*args):
    subprocess.run([FFMPEG, "-nostdin", "-y", "-v", "error", *args], check=True, timeout=120)


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required")
def test_same_audio_and_enrollment_give_identical_output_with_original_blacked_out_and_no_video(tmp_path):
    from services.api.focus_api.inference import extract_audio_wav

    src = tmp_path / "audio.wav"
    write_wav(str(src), scene(TURNS, TOTAL_S), 16000)
    original = tmp_path / "original.mp4"
    ff("-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=25:duration={TOTAL_S}", "-i", str(src),
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(original))
    blacked = tmp_path / "blacked.mp4"
    ff("-i", str(original), "-vf", "lutyuv=y=16:u=128:v=128", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       "-c:a", "copy", str(blacked))
    no_video = tmp_path / "audio_only.m4a"
    ff("-i", str(original), "-vn", "-c:a", "copy", str(no_video))
    # The three files really differ in what is on screen.
    assert original.read_bytes() != blacked.read_bytes()

    outputs, regions, analyses = {}, {}, {}
    for name, media in (("original", original), ("blacked", blacked), ("none", no_video)):
        wav = tmp_path / f"{name}.16k.wav"
        extract_audio_wav(FFMPEG, str(media), str(wav), 18000)
        e = engine()
        analysis = e.analyze(str(wav))
        enrollment = e.enroll_range(str(wav), analysis["diarization"], 0.0, 6.0)  # same user choice
        job = tmp_path / name
        job.mkdir()
        result = e.isolate(str(wav), enrollment["voiceprint"], analysis["diarization"], str(job))
        outputs[name] = Path(result.wav_path).read_bytes()
        regions[name] = regions_to_wire(result.details["regions"])
        analyses[name] = analysis["diarization"]
    assert len(outputs["original"]) > 100_000
    assert outputs["original"] == outputs["blacked"] == outputs["none"]
    assert regions["original"] == regions["blacked"] == regions["none"]
    assert analyses["original"] == analyses["blacked"] == analyses["none"]
    with wave.open(str(tmp_path / "original" / "isolated.wav")) as w:
        assert (w.getframerate(), w.getnchannels()) == (16000, 1)


def test_real_enrollment_voiceprints_pass_the_api_validator(audio):
    """Contract test: voiceprints produced by the real engine (range and file) survive validation."""
    from services.api.focus_api.remote_inference import validate_voiceprint

    class Wide(FakeEmbedder):  # the validator requires realistic (>= 8) dimensions
        def embed(self, samples):
            return np.tile(super().embed(samples), 2) / np.sqrt(2)

    engine = lambda: AudioOnlyEngine(FakeDiarizer(TURNS), Wide())  # noqa: E731
    solo = os.path.join(os.path.dirname(audio), "solo.wav")
    write_wav(solo, scene([("A", 0.0, 8.0)], 8.0), 16000)
    e = engine()
    diar = e.analyze(audio)["diarization"]
    solo_engine = AudioOnlyEngine(FakeDiarizer([("A", 0.0, 8.0)]), Wide())
    for vp in (e.enroll_range(audio, diar, 0.0, 6.0)["voiceprint"], solo_engine.enroll_file(solo)["voiceprint"]):
        clean = validate_voiceprint(json.loads(json.dumps(vp)))
        assert clean["source"]["clean_spans"] and clean["source"]["level"] is not None
        assert clean["vector"] == vp["vector"]
    for sp in e.analyze(audio)["speakers"]:
        validate_voiceprint(sp["voiceprint"])
