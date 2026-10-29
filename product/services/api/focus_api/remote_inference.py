"""Single outstanding, outbound-poll inference bridge.

The trusted operator's machine gets only the current task's canonical media.
It cannot enumerate uploads, use browser session tokens or choose output paths.
Tasks are never re-leased: timeout/restart revokes the id and rejects late data.
The SQLite dispatcher remains the owner of job state and recovery.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import FileResponse

from .errors import ApiError, not_found, unauthorized
from .interfaces import ProviderError

ERROR_MESSAGES = {
    "PROCESSING_FAILED": "inference failed on the connected computer",
    "INVALID_MEDIA": "the connected computer could not decode the media",
    "NO_AUDIO": "the clip has no usable audio",
    "LIMIT_EXCEEDED": "the clip exceeds the inference limits",
    "FACE_NOT_FOUND": "the selected face could not be found",
    "TARGET_LOST": "the selected face could not be tracked reliably",
    "GPU_BUSY": "the connected computer's GPU is unavailable",
}
MAX_AUDIO_BYTES = 2 * 1024 * 1024  # 15 s, mono PCM16 @ 16k is < 0.5 MB


@dataclass
class RemoteTask:
    video_id: str
    path: str
    kind: str
    duration_ms: int
    face_id: str | None = None
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    claimed: bool = False
    finished: bool = False
    result: object = None
    error: ProviderError | None = None


class RemoteBridge:
    def __init__(self, token: str, repo, *, timeout_s=900.0):
        if len(token) < 32:
            raise ValueError("FOCUS_WORKER_TOKEN must contain at least 32 characters")
        self._token = token
        self.repo = repo
        self.timeout_s = timeout_s
        self._condition = threading.Condition()
        self._task: RemoteTask | None = None
        self._last_poll = 0.0
        self._closed = False

    def authorize(self, request: Request):
        # A private Replit preview can reserve Authorization for its own access
        # gate. Keep that independent from application-level worker trust.
        dedicated = request.headers.get("x-focus-worker-token")
        bearer = request.headers.get("authorization", "")
        value = (
            dedicated if dedicated is not None
            else bearer[7:] if bearer.startswith("Bearer ") else ""
        )
        if not hmac.compare_digest(value.encode(), self._token.encode()):
            raise unauthorized("a valid inference-worker credential is required")

    def status(self):
        with self._condition:
            return {
                "mode": "remote",
                "connected": not self._closed and time.monotonic() - self._last_poll < 20,
                "busy": self._task is not None,
            }

    def ensure_ready(self):
        if not self.status()["connected"]:
            raise ProviderError(
                "the inference computer is offline; start the Windows worker before uploading",
                retryable=True,
            )

    def call(self, *, kind, video_id, video_path, face_id=None):
        self.ensure_ready()
        video = self.repo.get_video(video_id)
        if video is None or video.deleted:
            raise ProviderError("media was deleted", retryable=False)
        task = RemoteTask(video_id, video_path, kind, video.duration_ms, face_id)
        deadline = time.monotonic() + self.timeout_s
        with self._condition:
            if self._closed or self._task is not None:
                raise ProviderError("inference worker is busy or stopping", code="GPU_BUSY")
            self._task = task
            try:
                while not task.finished:
                    current = self.repo.get_video(video_id)
                    if current is None or current.deleted:
                        raise ProviderError("media was deleted", retryable=False)
                    remaining = deadline - time.monotonic()
                    if self._closed or remaining <= 0:
                        raise ProviderError(
                            "the inference computer disconnected or timed out; no result was accepted"
                        )
                    self._condition.wait(min(remaining, 0.5))
                if task.error:
                    raise task.error
                return task.result
            finally:
                self._task = None

    def _current(self, task_id, *, kind=None):
        task = self._task
        if (
            self._closed or task is None or task.task_id != task_id
            or not task.claimed or task.finished or (kind and task.kind != kind)
        ):
            raise not_found("inference task expired or unavailable")
        video = self.repo.get_video(task.video_id)
        if video is None or video.deleted:
            raise not_found("inference media is unavailable")
        return task

    def poll(self):
        with self._condition:
            self._last_poll = time.monotonic()
            task = self._task
            if self._closed or task is None or task.claimed:
                return None
            video = self.repo.get_video(task.video_id)
            if video is None or video.deleted:
                return None
            # Computed from the actual canonical bytes, not a client filename.
            digest = hashlib.sha256(Path(task.path).read_bytes()).hexdigest()
            task.claimed = True
            return {
                "task_id": task.task_id, "kind": task.kind,
                "video_id": task.video_id, "face_id": task.face_id,
                "sha256": digest,
            }

    def media(self, task_id):
        with self._condition:
            return self._current(task_id).path

    def complete(self, task_id, result, *, kind):
        with self._condition:
            task = self._current(task_id, kind=kind)
            task.result, task.finished = result, True
            self._last_poll = time.monotonic()
            self._condition.notify_all()

    def fail(self, task_id, code):
        with self._condition:
            task = self._current(task_id)
            code = code if code in ERROR_MESSAGES else "PROCESSING_FAILED"
            task.error = ProviderError(
                ERROR_MESSAGES[code], code=code,
                retryable=code not in ("INVALID_MEDIA", "NO_AUDIO", "LIMIT_EXCEEDED"),
            )
            task.finished = True
            self._last_poll = time.monotonic()
            self._condition.notify_all()

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()


async def bounded_body(request: Request, limit: int) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise ApiError("LIMIT_EXCEEDED", "inference result is too large", status_code=413)
        data.extend(chunk)
    return bytes(data)


def validate_wav(data: bytes, expected_ms: int) -> int:
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (1, 16000, 2):
                raise ValueError()
            frames = audio.getnframes()
            if not 0 < frames <= 16_000 * 15:
                raise ValueError()
            if len(audio.readframes(frames + 1)) != frames * 2:
                raise ValueError()
            duration = round(frames / 16)
            if abs(duration - expected_ms) > 80:
                raise ValueError()
            return duration
    except (wave.Error, EOFError, ValueError):
        raise ApiError(
            "INVALID_MEDIA", "worker WAV is invalid or not aligned with the canonical video",
            status_code=400,
        ) from None


def add_remote_routes(app, bridge: RemoteBridge):
    """No CORS additions; token is only for the operator's native worker."""
    @app.get("/worker/check")
    def check(request: Request):
        bridge.authorize(request)
        return {"worker_protocol": 1}

    @app.post("/worker/poll")
    def poll(request: Request):
        bridge.authorize(request)
        result = bridge.poll()
        return result if result else Response(status_code=204)

    @app.get("/worker/tasks/{task_id}/media")
    def media(task_id: str, request: Request):
        bridge.authorize(request)
        return FileResponse(
            bridge.media(task_id), media_type="video/mp4",
            headers={"Cache-Control": "private, no-store"},
        )

    @app.post("/worker/tasks/{task_id}/faces")
    async def faces(task_id: str, request: Request):
        bridge.authorize(request)
        # Validate before consuming a result. Faces are validated at provider
        # boundary too; a malformed result never makes candidates READY.
        with bridge._condition:
            bridge._current(task_id, kind="detect")
        import json
        from .inference import decode_faces
        try:
            result = json.loads(await bounded_body(request, 512 * 1024))
            decode_faces(result)
        except (ValueError, TypeError, KeyError, ProviderError):
            raise ApiError("INVALID_MEDIA", "invalid worker face result", status_code=400) from None
        bridge.complete(task_id, result, kind="detect")
        return {"accepted": True}

    @app.post("/worker/tasks/{task_id}/audio")
    async def audio(task_id: str, request: Request):
        bridge.authorize(request)
        with bridge._condition:
            expected = bridge._current(task_id, kind="extract").duration_ms
        data = await bounded_body(request, MAX_AUDIO_BYTES)
        duration = validate_wav(data, expected)
        bridge.complete(task_id, (data, duration), kind="extract")
        return {"accepted": True}

    @app.post("/worker/tasks/{task_id}/error")
    async def error(task_id: str, request: Request):
        bridge.authorize(request)
        import json
        try:
            data = json.loads(await bounded_body(request, 1024))
            code = data["code"]
            if not isinstance(code, str):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise ApiError("INVALID_REQUEST", "invalid worker failure", status_code=400) from None
        bridge.fail(task_id, code)
        return {"accepted": True}
