"""Worker-protocol tests for the audio-only tasks. Synthetic payloads; no models."""
import base64
import io
import json
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services.api.focus_api.config import Settings
from services.api.focus_api.interfaces import ProviderError
from services.api.focus_api.routes import create_app

KEY = "synthetic-audio-test-key-" * 2
AUTH = {"Authorization": "Bearer " + KEY}


def wav_bytes(seconds=1.0):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return out.getvalue()


class Videos:
    def __init__(self, duration_ms):
        self.duration_ms, self.deleted = duration_ms, False

    def get_video(self, _id):
        return SimpleNamespace(deleted=self.deleted, duration_ms=self.duration_ms)


@pytest.fixture
def remote(tmp_path):
    app = create_app(settings=Settings(storage_root=tmp_path, inference_mode="remote", worker_token=KEY),
                     start_dispatcher=False)
    bridge = app.state.inference_bridge
    bridge.repo = Videos(12_000)
    with TestClient(app) as client:
        client.post("/worker/poll", headers=AUTH)
        yield app, client, bridge, tmp_path


def vp(n=8):
    return {"format": "focus-voiceprint/1", "vector": [0.1] * n, "embedder": "ecapa", "dim": n,
            "duration_s": 9.0, "source": {"kind": "speaker_label"}, "warnings": []}


def analysis(duration_ms=12_000, **over):
    clip = base64.b64encode(wav_bytes(3.0)).decode()
    body = {"duration_ms": duration_ms, "embedder": "ecapa", "warnings": [],
            "diarization": {"speakers": ["S0"], "turns": [{"start": 0, "end": 5, "speaker": "S0"}],
                            "overlaps": [], "speech": [{"start": 0, "end": 5, "speaker": None}]},
            "speakers": [{"speaker": "S0", "speech_s": 5, "clean_s": 5, "overlap_fraction": 0,
                          "usable": True, "refusal": None, "warnings": [],
                          "sample": {"start": 1, "end": 4}, "sample_wav_b64": clip, "voiceprint": vp()}]}
    body.update(over)
    return body


def run(client, bridge, tmp_path, kind, payload=None, duration_ms=12_000, path=None):
    source = path or tmp_path / "task.wav"
    if path is None:
        source.write_bytes(wav_bytes(1.0))
    bridge.repo.duration_ms = duration_ms
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(bridge.call, kind=kind, video_id="v", video_path=str(source),
                         payload=payload, timeout_s=10)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        r = client.post("/worker/poll", headers=AUTH)
        if r.status_code == 200:
            return pool, future, r.json()
        time.sleep(0.01)
    pytest.fail("no task offered")


def test_analysis_task_sends_audio_only_and_accepts_valid_result(remote):
    _app, client, bridge, tmp = remote
    pool, future, task = run(client, bridge, tmp, "analyze")
    assert task["kind"] == "analyze" and task["face_id"] is None and "payload" not in task
    media = client.get(f"/worker/tasks/{task['task_id']}/media", headers=AUTH)
    assert media.headers["content-type"] == "audio/wav" and media.content[:4] == b"RIFF"
    r = client.post(f"/worker/tasks/{task['task_id']}/analysis", headers=AUTH, json=analysis())
    assert r.status_code == 200
    assert future.result(5)["speakers"][0]["speaker"] == "S0"
    pool.shutdown()


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(duration_ms=3000),
    lambda b: b["speakers"][0]["voiceprint"].update(vector=[float("nan")] * 8),
    lambda b: b["speakers"][0]["voiceprint"].update(vector=[0.1] * 5000),
    lambda b: b["speakers"][0].update(usable="yes"),
    lambda b: b["speakers"][0].update(voiceprint=None),
    lambda b: b["speakers"][0].update(sample={"start": 0, "end": 30}),
    lambda b: b["speakers"][0].update(sample_wav_b64="!!notbase64"),
    lambda b: b["speakers"][0].update(sample_wav_b64=base64.b64encode(wav_bytes(8.0)).decode()),
    lambda b: b["diarization"].update(turns=[{"start": 0, "end": 1, "speaker": "S0"}] * 4001),
    lambda b: b.update(speakers=b["speakers"] * 9),
])
def test_invalid_analysis_is_rejected_and_never_completes(remote, mutate):
    _app, client, bridge, tmp = remote
    pool, future, task = run(client, bridge, tmp, "analyze")
    body = analysis()
    mutate(body)
    r = client.post(f"/worker/tasks/{task['task_id']}/analysis", headers=AUTH, content=json.dumps(body))
    assert r.status_code in (400, 413)
    assert not future.done()
    client.post(f"/worker/tasks/{task['task_id']}/error", headers=AUTH, json={"code": "PROCESSING_FAILED"})
    with pytest.raises(ProviderError):
        future.result(5)
    pool.shutdown()


def test_result_routes_check_kind_and_credentials(remote):
    _app, client, bridge, tmp = remote
    pool, future, task = run(client, bridge, tmp, "analyze")
    url = f"/worker/tasks/{task['task_id']}"
    assert client.post(url + "/analysis", json=analysis()).status_code == 401
    assert client.post(url + "/enrollment", headers=AUTH, json={"refused": "x"}).status_code == 404
    assert client.post(url + "/regions", headers=AUTH, json={"regions": []}).status_code == 404
    assert client.post(url + "/audio", headers=AUTH, content=wav_bytes(12)).status_code == 404
    client.post(url + "/error", headers=AUTH, json={"code": "TIMEOUT"})
    pool.shutdown()


def test_enrollment_result_voiceprint_or_refusal(remote):
    _app, client, bridge, tmp = remote
    payload = {"mode": "range", "start_ms": 0, "end_ms": 6000, "diarization": {}}
    pool, future, task = run(client, bridge, tmp, "enroll", payload)
    assert task["payload"] == payload and task["face_id"] is None
    bad = client.post(f"/worker/tasks/{task['task_id']}/enrollment", headers=AUTH,
                      json={"voiceprint": {**vp(), "vector": [1.0]}})
    assert bad.status_code == 400
    ok = client.post(f"/worker/tasks/{task['task_id']}/enrollment", headers=AUTH,
                     json={"voiceprint": vp(), "warnings": ["short"]})
    assert ok.status_code == 200 and future.result(5)["warnings"] == ["short"]
    pool.shutdown()
    pool, future, task = run(client, bridge, tmp, "enroll", payload)
    client.post(f"/worker/tasks/{task['task_id']}/enrollment", headers=AUTH, json={"refused": "too quiet"})
    assert future.result(5) == {"refused": "too quiet"}
    pool.shutdown()


def test_visibility_spans_are_validated(remote):
    _app, client, bridge, tmp = remote
    video = tmp / "c.mp4"
    video.write_bytes(b"synthetic")
    pool, future, task = run(client, bridge, tmp, "visibility", {"bbox": [1, 2, 3, 4], "frame_size": [64, 48]},
                             path=video)
    media = client.get(f"/worker/tasks/{task['task_id']}/media", headers=AUTH)
    assert media.headers["content-type"] == "video/mp4"
    url = f"/worker/tasks/{task['task_id']}/visibility"
    assert client.post(url, headers=AUTH, json={"visible": [{"start_ms": 5, "end_ms": 1}]}).status_code == 400
    assert client.post(url, headers=AUTH, json={"visible": [{"start_ms": 0, "end_ms": 99_000}]}).status_code == 400
    assert client.post(url, headers=AUTH, json={"visible": [{"start_ms": 0, "end_ms": 2000}]}).status_code == 200
    assert future.result(5) == [{"start_ms": 0, "end_ms": 2000}]
    pool.shutdown()


def test_isolate_needs_regions_first_then_accepts_a_three_minute_wav(remote):
    _app, client, bridge, tmp = remote
    payload = {"voiceprint": vp(), "diarization": {}}
    pool, future, task = run(client, bridge, tmp, "isolate", payload, duration_ms=180_000)
    assert task["payload"] == payload and task["face_id"] is None
    url = f"/worker/tasks/{task['task_id']}"
    headers = {**AUTH, "X-Focus-Engine": "audio_only", "Content-Type": "audio/wav"}
    assert client.post(url + "/audio", headers=headers, content=wav_bytes(180)).status_code == 400
    assert client.post(url + "/regions", headers=AUTH, json={"regions": [
        {"start_ms": 0, "end_ms": 500, "label": "other"}]}).status_code == 400
    ok = client.post(url + "/regions", headers=AUTH, json={"regions": [
        {"start_ms": 0, "end_ms": 90_000, "label": "target", "reason": "voice_match"},
        {"start_ms": 90_000, "end_ms": 91_000, "label": "uncertain", "reason": "close_score"}]})
    assert ok.status_code == 200
    wrong_engine = client.post(url + "/audio", headers={**headers, "X-Focus-Engine": "dolphin"},
                               content=wav_bytes(180))
    assert wrong_engine.status_code == 400
    assert client.post(url + "/audio", headers=headers, content=wav_bytes(100)).status_code == 400
    assert client.post(url + "/audio", headers=headers, content=wav_bytes(180)).status_code == 200
    data, duration, engine, regions = future.result(5)
    assert (duration, engine, len(regions)) == (180_000, "audio_only", 2)
    pool.shutdown()


def test_lip_extract_keeps_its_fifteen_second_cap(remote):
    _app, client, bridge, tmp = remote
    pool, future, task = run(client, bridge, tmp, "extract", duration_ms=30_000)
    r = client.post(f"/worker/tasks/{task['task_id']}/audio", headers={**AUTH, "X-Focus-Engine": "dolphin"},
                    content=wav_bytes(30))
    assert r.status_code == 400
    client.post(f"/worker/tasks/{task['task_id']}/error", headers=AUTH, json={"code": "TIMEOUT"})
    pool.shutdown()


def test_detect_and_analyze_can_be_pending_together_but_not_the_same_kind_twice(remote):
    _app, client, bridge, tmp = remote
    source = tmp / "x.wav"
    source.write_bytes(wav_bytes(1))
    pool = ThreadPoolExecutor(max_workers=3)
    a = pool.submit(bridge.call, kind="detect", video_id="v", video_path=str(source), timeout_s=3)
    b = pool.submit(bridge.call, kind="analyze", video_id="v", video_path=str(source), timeout_s=3)
    seen = set()
    deadline = time.monotonic() + 5
    while len(seen) < 2 and time.monotonic() < deadline:
        r = client.post("/worker/poll", headers=AUTH)
        if r.status_code == 200:
            seen.add(r.json()["kind"])
        time.sleep(0.01)
    assert seen == {"detect", "analyze"} and bridge.status()["busy"]
    with pytest.raises(ProviderError) as busy:
        bridge.call(kind="analyze", video_id="v", video_path=str(source), timeout_s=1)
    assert busy.value.code == "GPU_BUSY"
    for f in (a, b):
        with pytest.raises(ProviderError):
            f.result(6)
    assert not bridge.status()["busy"]
    pool.shutdown()
