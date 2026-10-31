"""The Windows worker's audio-only task handlers, with tone test models.
Not GPU or Windows acceptance evidence."""
import importlib.util
import io
import json
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

PRODUCT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PRODUCT / "packages" / "ml"))

# tests/voice/fakes.py shares its name with tests/worker/fakes.py; load it by path.
_spec = importlib.util.spec_from_file_location("voice_fakes", PRODUCT / "tests" / "voice" / "fakes.py")
_fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fakes)
FakeDiarizer, FakeEmbedder, scene = _fakes.FakeDiarizer, _fakes.FakeEmbedder, _fakes.scene
from focus_ml.isolation_engines import write_wav  # noqa: E402
from focus_ml.voice.engine import AudioOnlyEngine  # noqa: E402

TURNS = [("A", 0.0, 6.0), ("B", 6.0, 12.0)]


from focus_ml.code_version import ISOLATE_CONTRACT as CONTRACT  # noqa: E402


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("windows_worker", PRODUCT / "tools" / "windows_worker.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Recorder:
    def __init__(self, module):
        self.sent = []
        self.client = object.__new__(module.WorkerClient)
        self.client.json = lambda path, payload=None: self.sent.append((path, payload))
        self.client.request = self._request

    def _request(self, path, data=None, content_type=None, extra=None):
        self.sent.append((path, data, content_type, extra))
        return io.BytesIO(b"{}")


@pytest.fixture
def setup(tmp_path):
    audio = tmp_path / "task-audio.wav"
    write_wav(str(audio), scene(TURNS, 12.0), 16000)
    real = AudioOnlyEngine(FakeDiarizer(TURNS), FakeEmbedder())
    engine = SimpleNamespace(analyze_audio=real.analyze, enroll_audio_range=real.enroll_range,
                             enroll_audio_file=real.enroll_file, isolate_audio=real.isolate)
    return audio, engine, tmp_path


def test_analyze_posts_speakers_samples_and_warnings(module, setup):
    audio, engine, tmp = setup
    rec = Recorder(module)
    rec.client.handle({"kind": "analyze"}, engine, audio, str(tmp), "/worker/tasks/t")
    path, body = rec.sent[0]
    assert path == "/worker/tasks/t/analysis"
    assert {s["speaker"] for s in body["speakers"]} == {"A", "B"} and body["speakers"][0]["sample_wav_b64"]
    json.dumps(body)


def test_enroll_range_posts_voiceprint_and_refusal_is_forwarded_not_raised(module, setup):
    audio, engine, tmp = setup
    rec = Recorder(module)
    diar = engine.analyze_audio(str(audio))["diarization"]
    task = {"kind": "enroll", "payload": {"mode": "range", "start_ms": 0, "end_ms": 6000, "diarization": diar}}
    rec.client.handle(task, engine, audio, str(tmp), "/p")
    assert rec.sent[-1][0] == "/p/enrollment" and rec.sent[-1][1]["voiceprint"]["format"] == "focus-voiceprint/1"
    task["payload"].update(end_ms=1000)
    rec.client.handle(task, engine, audio, str(tmp), "/p")
    assert "refused" in rec.sent[-1][1] and "at least" in rec.sent[-1][1]["refused"]


def test_isolate_sends_regions_then_audio_from_enrollment_and_diarization_only(module, setup):
    audio, engine, tmp = setup
    rec = Recorder(module)
    analysis = engine.analyze_audio(str(audio))
    vp = next(s for s in analysis["speakers"] if s["speaker"] == "A")["voiceprint"]
    task = {"kind": "isolate", "face_id": None,
            "payload": {"voiceprint": vp, "diarization": analysis["diarization"], "contract": CONTRACT}}
    rec.client.handle(task, engine, audio, str(tmp), "/p")
    assert [s[0] for s in rec.sent] == ["/p/regions", "/p/audio"]
    assert any(r["label"] == "target" for r in rec.sent[0][1]["regions"])
    assert rec.sent[1][2] == "audio/wav" and rec.sent[1][3] == {"X-Focus-Engine": "audio_only"}
    with wave.open(io.BytesIO(rec.sent[1][1])) as w:
        assert (w.getframerate(), w.getnframes()) == (16000, 12 * 16000)


def test_isolate_rejects_output_outside_its_directory(module, setup):
    audio, engine, tmp = setup
    other = tmp / "elsewhere"
    other.mkdir()
    rec = Recorder(module)
    analysis = engine.analyze_audio(str(audio))
    vp = analysis["speakers"][0]["voiceprint"]
    task = {"kind": "isolate", "payload": {"voiceprint": vp, "diarization": analysis["diarization"], "contract": CONTRACT}}
    with pytest.raises(ValueError):
        stray = SimpleNamespace(isolate_audio=lambda *a, **k: SimpleNamespace(
            wav_path=str(tmp / "x.wav"), source_offset_ms=0, details={"regions": []}))
        rec.client.handle(task, stray, audio, str(other), "/p")


def test_unknown_task_and_new_defaults(module, setup):
    audio, engine, tmp = setup
    with pytest.raises(ValueError):
        Recorder(module).client.handle({"kind": "mystery"}, engine, audio, str(tmp), "/p")
    assert module.ENGINES[0] == "audio_only"
    assert module.MAX_MEDIA_BYTES >= 180 * 1024 * 1024


def test_isolate_posts_routing_summary_and_passes_reference_audio(module, setup):
    import base64
    audio, engine, tmp = setup
    seen = {}
    real = engine.isolate_audio

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    engine.isolate_audio = spy
    rec = Recorder(module)
    analysis = engine.analyze_audio(str(audio))
    vp = next(s for s in analysis["speakers"] if s["speaker"] == "A")["voiceprint"]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        w.writeframes(b"\x00\x01" * 16000)
    task = {"kind": "isolate", "payload": {
        "voiceprint": vp, "diarization": analysis["diarization"], "contract": CONTRACT,
        "reference_wav_b64": base64.b64encode(buf.getvalue()).decode()}}
    rec.client.handle(task, engine, audio, str(tmp), "/p")
    assert len(seen["reference_audio"]) == 16000
    routing = rec.sent[0][1]["routing"]
    assert routing["overlap_extraction"] == "disabled" and routing["isolation_claim"] == "strict_isolation"
