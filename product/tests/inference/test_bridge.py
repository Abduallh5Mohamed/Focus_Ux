"""Protocol-only tests with synthetic media/results; NOT real model validation."""
import base64
import io
import json
import threading
import time
import wave
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services.api.focus_api.config import Settings
from services.api.focus_api.identity import make_face_id
from services.api.focus_api.inference import decode_faces
from services.api.focus_api.interfaces import ProviderError
from services.api.focus_api.remote_inference import RemoteBridge, validate_wav
from services.api.focus_api.routes import create_app
from services.api.focus_api.errors import ApiError

# Test-only credential, never an environment secret or deployment credential.
AUTH = {"Authorization": "Bearer " + "synthetic-test-key-" * 3}


def wav_bytes(duration_ms=1000, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x00" * (duration_ms * rate // 1000))
    return output.getvalue()


class MemoryVideos:
    def __init__(self):
        self.deleted = False

    def get_video(self, _id):
        return SimpleNamespace(deleted=self.deleted, duration_ms=1000)


@pytest.fixture
def remote(tmp_path):
    app = create_app(
        settings=Settings(
            storage_root=tmp_path, inference_mode="remote",
            worker_token=AUTH["Authorization"][7:],
        ),
        start_dispatcher=False,
    )
    # Only the bridge uses this stub; API repository remains real.
    app.state.inference_bridge.repo = MemoryVideos()
    with TestClient(app) as client:
        yield app, client, app.state.inference_bridge


def claim(client):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.post("/worker/poll", headers=AUTH)
        assert response.status_code in (200, 204)
        if response.status_code == 200:
            return response.json()
        time.sleep(0.01)
    pytest.fail("bridge did not offer a task")


def start_task(client, bridge, tmp_path, kind="extract"):
    source = tmp_path / "canonical.mp4"
    source.write_bytes(b"synthetic-media-for-protocol-test")
    assert client.post("/worker/poll", headers=AUTH).status_code == 204
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(
        bridge.call, kind=kind, video_id="video-id",
        video_path=str(source), face_id="selected-second-face",
    )
    task = claim(client)
    return pool, future, task


def test_worker_key_is_separate_from_browser_auth(remote):
    _, client, _ = remote
    for headers in ({}, {"Authorization": "Bearer browser-session"}, {"Authorization": "Bearer wrong"}):
        assert client.post("/worker/poll", headers=headers).status_code == 401
        assert client.get("/worker/tasks/made-up/media", headers=headers).status_code == 401
    assert client.get("/videos/private/original", headers=AUTH).status_code == 401


def test_private_preview_auth_separate_and_check_does_not_mark_online(remote):
    _, client, bridge = remote
    assert not bridge.status()["connected"]
    headers = {
        "Authorization": "Bearer separate-platform-gate-test",
        "X-Focus-Worker-Token": AUTH["Authorization"][7:],
    }
    result = client.get("/worker/check", headers=headers)
    assert result.status_code == 200
    body = result.json()
    from focus_ml.code_version import ISOLATE_CONTRACT, code_version
    assert body == {"worker_protocol": 1, "code_version": code_version(), "isolate_contract": ISOLATE_CONTRACT}
    assert not bridge.status()["connected"]
    assert client.get("/worker/check", headers={
        "Authorization": AUTH["Authorization"][7:],
    }).status_code == 401
    assert client.get("/worker/check", headers={
        **AUTH, "X-Focus-Worker-Token": "wrong",
    }).status_code == 401
    assert client.get("/worker/check", headers={
        "Authorization": "Bearer separate-platform-gate-test",
    }).status_code == 401
    assert client.post("/worker/poll", headers=headers).status_code == 204
    assert bridge.status()["connected"]


def test_claim_media_result_and_replay_rejection(remote, tmp_path):
    _, client, bridge = remote
    pool, future, task = start_task(client, bridge, tmp_path)
    try:
        prefix = "/worker/tasks/" + task["task_id"]
        assert task["face_id"] == "selected-second-face"
        assert task["video_id"] == "video-id"
        assert client.post("/worker/poll", headers=AUTH).status_code == 204
        response = client.get(prefix + "/media", headers=AUTH)
        assert response.content == b"synthetic-media-for-protocol-test"
        assert response.headers["cache-control"] == "private, no-store"
        payload = wav_bytes()
        assert client.post(prefix + "/audio", content=payload, headers=AUTH).status_code == 200
        assert future.result(timeout=2) == (payload, 1000, "dolphin")
        assert client.post(prefix + "/audio", content=payload, headers=AUTH).status_code == 404
        assert client.get(prefix + "/media", headers=AUTH).status_code == 404
    finally:
        bridge.close()
        pool.shutdown()


def test_bad_wav_rejected_without_completing_task(remote, tmp_path):
    _, client, bridge = remote
    pool, future, task = start_task(client, bridge, tmp_path)
    prefix = "/worker/tasks/" + task["task_id"]
    try:
        for data in (b"not audio", wav_bytes(500), wav_bytes(rate=8000)):
            assert client.post(prefix + "/audio", content=data, headers=AUTH).status_code == 400
        assert not future.done()
        assert client.post(prefix + "/faces", json=[], headers=AUTH).status_code == 404
        assert client.post(prefix + "/audio", content=b"0" * (2 * 1024 * 1024 + 1), headers=AUTH).status_code == 413
        assert client.post(prefix + "/error", json={"code": "NO_AUDIO"}, headers=AUTH).status_code == 200
        with pytest.raises(ProviderError, match="no usable audio"):
            future.result(timeout=2)
    finally:
        bridge.close()
        pool.shutdown()


def test_delete_revokes_media_and_late_output(remote, tmp_path):
    _, client, bridge = remote
    pool, future, task = start_task(client, bridge, tmp_path)
    try:
        bridge.repo.deleted = True
        prefix = "/worker/tasks/" + task["task_id"]
        assert client.get(prefix + "/media", headers=AUTH).status_code == 404
        assert client.post(prefix + "/audio", content=wav_bytes(), headers=AUTH).status_code == 404
        with pytest.raises(ProviderError, match="deleted"):
            future.result(timeout=2)
    finally:
        bridge.close()
        pool.shutdown()


def test_timeout_and_shutdown_fail_honestly(remote, tmp_path):
    _, client, bridge = remote
    bridge.timeout_s = 0.2
    pool, future, task = start_task(client, bridge, tmp_path)
    try:
        with pytest.raises(ProviderError, match="timed out"):
            future.result(timeout=2)
        assert client.get("/worker/tasks/" + task["task_id"] + "/media", headers=AUTH).status_code == 404
    finally:
        bridge.close()
        pool.shutdown()


def test_offline_fails_before_sending_private_media(remote, tmp_path):
    _, _, bridge = remote
    with pytest.raises(ProviderError, match="offline"):
        bridge.call(kind="detect", video_id="v", video_path=str(tmp_path / "none"))


def test_failure_does_not_reflect_computer_paths(remote, tmp_path):
    _, client, bridge = remote
    pool, future, task = start_task(client, bridge, tmp_path)
    try:
        assert client.post(
            "/worker/tasks/" + task["task_id"] + "/error",
            json={"code": "private-C:\\user\\file", "message": "private traceback"}, headers=AUTH,
        ).status_code == 200
        with pytest.raises(ProviderError, match="inference failed") as caught:
            future.result(timeout=2)
        assert "private" not in caught.value.message
    finally:
        bridge.close()
        pool.shutdown()


def test_geometry_and_thumbnail_validation():
    good = {
        "bbox": [1, 2, 3, 4], "frame_size": [20, 30], "timestamp_ms": 0,
        "thumbnail": base64.b64encode(b"\xff\xd8synthetic-jpeg").decode(),
    }
    assert decode_faces([good])[0].bbox == (1, 2, 3, 4)
    for patch in (
        {"bbox": [-1, 2, 3, 4]}, {"bbox": [1, 2, 100, 4]},
        {"timestamp_ms": 40}, {"timestamp_ms": False}, {"thumbnail": "bad"},
    ):
        with pytest.raises((ProviderError, ValueError)):
            decode_faces([{**good, **patch}])


def test_kit_contains_only_allowlisted_source(remote):
    _, client, _ = remote
    response = client.get("/worker-kit.zip")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert "Setup-Key.cmd" in names
        assert "Start-Worker.cmd" in names
        assert "product/tools/windows_worker.py" in names
        assert "product/packages/ml/focus_ml/runtime.py" in names
        assert not any(n.endswith((".pt", ".env", ".sqlite3")) for n in names)
        for name in names:
            assert AUTH["Authorization"][7:].encode() not in archive.read(name)


def test_remote_configuration_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="FOCUS_WORKER_TOKEN"):
        create_app(settings=Settings(storage_root=tmp_path, inference_mode="remote"))
