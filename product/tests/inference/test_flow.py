"""Real ffmpeg canonicalization + synthetic remote responses, NOT AI evidence."""
import base64
import hashlib
import io
import shutil
import subprocess
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from services.api.focus_api.config import Settings
from services.api.focus_api.routes import create_app


def wait_task(client, auth):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.post("/worker/poll", headers=auth)
        if response.status_code == 200:
            return response.json()
        assert response.status_code == 204, response.text
        time.sleep(0.02)
    pytest.fail("no inference task offered")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
def test_upload_normalize_second_face_and_protected_playable_audio(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=320x240:r=30:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-y", str(source),
    ], check=True, timeout=30)
    auth = {"Authorization": "Bearer " + "flow-test-only-" * 4}
    app = create_app(
        settings=Settings(
            storage_root=tmp_path / "storage", inference_mode="remote",
            worker_token=auth["Authorization"][7:],
        ), start_dispatcher=False,
    )
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        upload = client.post("/videos", files={"file": ("clip.mp4", source.read_bytes(), "video/mp4")})
        assert upload.status_code == 201, upload.text
        body = upload.json()
        video_id = body["video_id"]
        session = {"Authorization": "Bearer " + body["session_token"]}
        client.post("/worker/poll", headers=auth)
        future = pool.submit(app.state.dispatcher.process_one, "faces", video_id)
        task = wait_task(client, auth)
        try:
            prefix = "/worker/tasks/" + task["task_id"]
            media = client.get(prefix + "/media", headers=auth)
            assert hashlib.sha256(media.content).hexdigest() == task["sha256"]
            record = app.state.repo.get_video(video_id)
            assert record.canonical_path.endswith(".canonical.mp4")
            assert record.fps == 25
            # AAC priming/padding can add a few ms to container duration.
            assert abs(record.duration_ms - 1000) <= 80
            assert (record.width, record.height) == (320, 240)
            assert client.get(f"/videos/{video_id}/original", headers=session).content == media.content
            assert client.get(f"/videos/{video_id}/original").status_code == 401
            # Purely synthetic detector output. Deliberately select second face.
            candidates = [{
                "bbox": bbox, "frame_size": [320, 240], "timestamp_ms": 0,
                "thumbnail": base64.b64encode(b"\xff\xd8synthetic-test-image").decode(),
            } for bbox in ([10, 20, 40, 50], [200, 20, 40, 50])]
            assert client.post(prefix + "/faces", json=candidates, headers=auth).status_code == 200
            future.result(timeout=3)
            faces_response = client.get(f"/videos/{video_id}/faces", headers=session).json()
            assert faces_response["status"] == "ready", faces_response
            faces = faces_response["faces"]
            second = next(face for face in faces if face["bbox"]["x"] == 200)
            thumb_url = second["thumbnail_url"]
            assert client.get(thumb_url, headers=session).status_code == 200
            assert client.get(thumb_url).status_code == 401
            created = client.post("/jobs", headers=session, json={
                "video_id": video_id, "face_id": second["face_id"],
                "client_request_id": "flow-second-face",
            })
            assert created.status_code == 202, created.text
            job_id = created.json()["job_id"]
            future = pool.submit(app.state.dispatcher.process_one, "job", job_id)
            extraction = wait_task(client, auth)
            assert extraction["face_id"] == second["face_id"]
            assert extraction["video_id"] == video_id
            assert extraction["sha256"] == task["sha256"]
            data = io.BytesIO()
            with wave.open(data, "wb") as audio:
                audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\x00\x00" * 16000)
            result = client.post(
                "/worker/tasks/" + extraction["task_id"] + "/audio",
                content=data.getvalue(), headers=auth,
            )
            assert result.status_code == 200, result.text
            asr = wait_task(client, auth)
            assert asr["kind"] == "transcribe"
            audio_dl = client.get("/worker/tasks/" + asr["task_id"] + "/media", headers=auth)
            assert audio_dl.content == data.getvalue()
            assert audio_dl.headers["content-type"].startswith("audio/wav")
            assert client.post(
                "/worker/tasks/" + asr["task_id"] + "/error",
                json={"code": "MODEL_UNAVAILABLE"}, headers=auth,
            ).status_code == 200
            future.result(timeout=3)
            state = client.get(f"/jobs/{job_id}", headers=session).json()
            assert state["status"] == "completed", state
            tr = client.get(f"/jobs/{job_id}/transcript", headers=session).json()
            assert tr["status"] == "failed" and tr["segments"] == []
            assert tr["error"]["reason"] == "model_unavailable"
            assert state["audio_status"] == "ready"
            assert state["transcript_status"] == "failed"  # no invented transcript
            assert state["result"]["source_offset_ms"] == 0
            response = client.get(f"/jobs/{job_id}/audio", headers=session)
            assert response.content == data.getvalue()
            assert response.headers["content-type"].startswith("audio/wav")
            partial = client.get(
                f"/jobs/{job_id}/audio", headers={**session, "Range": "bytes=0-43"}
            )
            assert partial.status_code == 206
            assert partial.content == data.getvalue()[:44]
            assert client.get(f"/jobs/{job_id}/audio", headers=auth).status_code == 401
        finally:
            app.state.inference_bridge.close()


def test_transcript_validation_rejects_invented_or_off_timeline_segments():
    from services.api.focus_api.remote_inference import validate_transcript

    ok = validate_transcript({"segments": [{"start_ms": 0, "end_ms": 900, "text": " اهلا "}]}, 1000)
    assert ok == [{"id": 0, "start_ms": 0, "end_ms": 900, "text": "اهلا"}]
    assert validate_transcript({"segments": []}, 1000) == []
    for bad in (
        {"segments": [{"start_ms": 0, "end_ms": 5000, "text": "x"}]},
        {"segments": [{"start_ms": 500, "end_ms": 100, "text": "x"}]},
        {"segments": [{"start_ms": 0, "end_ms": 100, "text": "  "}]},
        {"segments": [{"start_ms": 0.5, "end_ms": 100, "text": "x"}]},
        {"nope": 1},
    ):
        with pytest.raises(ValueError):
            validate_transcript(bad, 1000)


def test_remote_transcriber_maps_failures_to_reasons():
    from types import SimpleNamespace

    from services.api.focus_api.interfaces import ProviderError
    from services.api.focus_api.transcription import RemoteTranscriber
    from services.worker.errors import TranscriptError

    repo = SimpleNamespace(find_job=lambda job_id: SimpleNamespace(video_id="v1"))

    class Bridge:
        def __init__(self, result):
            self.result = result

        def call(self, **kwargs):
            assert kwargs["kind"] == "transcribe" and kwargs["video_id"] == "v1"
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    path = "/jobs/abc123/isolated.wav"
    seg = [{"id": 0, "start_ms": 0, "end_ms": 10, "text": "x"}]
    assert RemoteTranscriber(Bridge(seg), repo).transcribe(path) == seg
    cases = {
        ProviderError("m", code="MODEL_UNAVAILABLE", retryable=False): "model_unavailable",
        ProviderError("m", code="OUT_OF_MEMORY"): "out_of_memory",
        ProviderError("m", code="TIMEOUT"): "timeout",
        ProviderError("the inference computer is offline; start"): "worker_offline",
        ProviderError("boom"): "failed",
    }
    for exc, reason in cases.items():
        with pytest.raises(TranscriptError) as caught:
            RemoteTranscriber(Bridge(exc), repo).transcribe(path)
        assert caught.value.reason == reason
