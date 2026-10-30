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
    "MODEL_UNAVAILABLE": "the transcription model is not installed on the connected computer",
    "OUT_OF_MEMORY": "the connected computer ran out of GPU memory",
    "TIMEOUT": "the connected computer timed out",
}
NON_RETRYABLE = ("INVALID_MEDIA", "NO_AUDIO", "LIMIT_EXCEEDED", "MODEL_UNAVAILABLE")
KNOWN_ENGINES = ("dolphin", "av_mossformer2", "separate_select", "audio_only")
AUDIO_KINDS = ("analyze", "enroll", "isolate")  # tasks that transfer audio only, never video
MAX_TRANSCRIPT_SEGMENTS = 500
MAX_SEGMENT_CHARS = 2000
MAX_AUDIO_BYTES = 2 * 1024 * 1024  # 15 s, mono PCM16 @ 16k is < 0.5 MB


@dataclass
class RemoteTask:
    video_id: str
    path: str
    kind: str
    duration_ms: int
    face_id: str | None = None
    payload: dict | None = None
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    claimed: bool = False
    finished: bool = False
    result: object = None
    error: ProviderError | None = None
    regions: list | None = None


class RemoteBridge:
    def __init__(self, token: str, repo, *, timeout_s=900.0, max_audio_s=15.0):
        if len(token) < 32:
            raise ValueError("FOCUS_WORKER_TOKEN must contain at least 32 characters")
        self._token = token
        self.repo = repo
        self.timeout_s = timeout_s
        self._condition = threading.Condition()
        # One outstanding task per kind: face detection and audio analysis of the
        # same upload can be pending together; the worker takes them in order.
        self._tasks: dict[str, RemoteTask] = {}
        self.max_audio_s = max_audio_s
        self._last_poll = 0.0
        self._closed = False
        self.stream_source = None  # StreamHub, set when the continuous live path is built

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
                "busy": bool(self._tasks),
            }

    def ensure_ready(self):
        if not self.status()["connected"]:
            raise ProviderError(
                "the inference computer is offline; start the Windows worker before uploading",
                retryable=True,
            )

    @property
    def max_audio_bytes(self) -> int:
        return int(self.max_audio_s * 16_000 * 2) + 4096

    def call(self, *, kind, video_id, video_path, face_id=None, timeout_s=None, payload=None):
        self.ensure_ready()
        video = self.repo.get_video(video_id)
        if video is None or video.deleted:
            raise ProviderError("media was deleted", retryable=False)
        task = RemoteTask(video_id, video_path, kind, video.duration_ms, face_id, payload)
        deadline = time.monotonic() + (timeout_s or self.timeout_s)
        with self._condition:
            if self._closed or kind in self._tasks:
                raise ProviderError("inference worker is busy or stopping", code="GPU_BUSY")
            self._tasks[kind] = task
            try:
                while not task.finished:
                    current = self.repo.get_video(video_id)
                    if current is None or current.deleted:
                        raise ProviderError("media was deleted", retryable=False)
                    remaining = deadline - time.monotonic()
                    if self._closed or remaining <= 0:
                        raise ProviderError(
                            "the inference computer disconnected or timed out; no result was accepted",
                            code="TIMEOUT" if kind in ("transcribe", "analyze", "isolate") else "PROCESSING_FAILED",
                        )
                    self._condition.wait(min(remaining, 0.5))
                if task.error:
                    raise task.error
                return task.result
            finally:
                if self._tasks.get(kind) is task:
                    del self._tasks[kind]

    def _find(self, task_id):
        return next((t for t in self._tasks.values() if t.task_id == task_id), None)

    def _current(self, task_id, *, kind=None):
        task = self._find(task_id)
        kinds = (kind,) if isinstance(kind, str) else tuple(kind or ())
        if (
            self._closed or task is None
            or not task.claimed or task.finished or (kinds and task.kind not in kinds)
        ):
            raise not_found("inference task expired or unavailable")
        video = self.repo.get_video(task.video_id)
        if video is None or video.deleted:
            raise not_found("inference media is unavailable")
        return task

    def poll(self):
        with self._condition:
            self._last_poll = time.monotonic()
            if self.stream_source is not None and not self._closed:
                claimed = self.stream_source.claim_pending()
                if claimed:
                    return {"task_id": claimed[0], "kind": "stream", "config": claimed[1]}
            task = next((t for t in self._tasks.values() if not t.claimed and not t.finished), None)
            if self._closed or task is None:
                return None
            video = self.repo.get_video(task.video_id)
            if video is None or video.deleted:
                return None
            # Computed from the actual canonical bytes, not a client filename.
            digest = hashlib.sha256(Path(task.path).read_bytes()).hexdigest()
            task.claimed = True
            body = {
                "task_id": task.task_id, "kind": task.kind,
                "video_id": task.video_id, "face_id": task.face_id,
                "sha256": digest,
            }
            if task.payload is not None:
                body["payload"] = task.payload
            return body

    def media(self, task_id):
        with self._condition:
            task = self._current(task_id)
            is_audio = task.kind == "transcribe" or task.kind in AUDIO_KINDS
            return task.path, ("audio/wav" if is_audio else "video/mp4")

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
                retryable=code not in NON_RETRYABLE,
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


def validate_wav(data: bytes, expected_ms: int, max_seconds: float = 15.0) -> int:
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (1, 16000, 2):
                raise ValueError()
            frames = audio.getnframes()
            if not 0 < frames <= int(16_000 * max_seconds):
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


def validate_transcript(body, expected_ms: int) -> list[dict]:
    """Segments must be real text on the clip timeline; nothing is invented or repaired."""
    if not isinstance(body, dict) or not isinstance(body.get("segments"), list):
        raise ValueError("segments missing")
    items = body["segments"]
    if len(items) > MAX_TRANSCRIPT_SEGMENTS:
        raise ValueError("too many segments")
    out, last_end = [], 0
    for index, item in enumerate(items):
        start, end, text = item["start_ms"], item["end_ms"], item["text"]
        if type(start) is not int or type(end) is not int or not isinstance(text, str):
            raise ValueError("bad segment types")
        text = text.strip()
        if not text or len(text) > MAX_SEGMENT_CHARS:
            raise ValueError("bad segment text")
        if start < last_end - 80 or end < start or end > expected_ms + 200:
            raise ValueError("segment is off the clip timeline")
        last_end = max(last_end, end)
        out.append({"id": index, "start_ms": start, "end_ms": end, "text": text})
    return out


MAX_ANALYSIS_BYTES = 8 * 1024 * 1024
MAX_TURNS = 4000
MAX_SPEAKERS = 8
MAX_VECTOR = 1024
MAX_REGIONS = 4000
MAX_CLIP_B64 = 400_000  # an 8 s, 16 kHz, mono PCM16 clip is about 340 kB in base64
_STR = 120


def _num(value, lo=None, hi=None):
    import math
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("bad number")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise ValueError("number out of range")
    return float(value)


def _text(value, limit=_STR):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("bad text")
    return value


def validate_voiceprint(vp) -> dict:
    if not isinstance(vp, dict) or vp.get("format") != "focus-voiceprint/1":
        raise ValueError("voiceprint missing")
    vec = vp.get("vector")
    if not isinstance(vec, list) or not 8 <= len(vec) <= MAX_VECTOR:
        raise ValueError("bad vector")
    source = vp.get("source") if isinstance(vp.get("source"), dict) else {}
    clean_source = {}
    for key, value in list(source.items())[:16]:
        if isinstance(value, list):
            # e.g. the clean speech spans an enrollment used: [{start, end, speaker}]
            spans = []
            for item in value[:MAX_TURNS]:
                if not isinstance(item, dict):
                    raise ValueError("bad voiceprint source")
                spans.append({_text(k, 40): (_text(v, 200) if isinstance(v, str)
                                             else None if v is None else _num(v))
                              for k, v in list(item.items())[:6]})
            clean_source[_text(key, 40)] = spans
        elif isinstance(value, dict):
            # e.g. the measured sample level {rms_dbfs, clip_fraction}
            clean_source[_text(key, 40)] = {
                _text(k, 40): (_text(v, 200) if isinstance(v, str) else None if v is None else _num(v))
                for k, v in list(value.items())[:8]}
        else:
            clean_source[_text(key, 40)] = (
                _text(value, 200) if isinstance(value, str)
                else None if value is None else _num(value))
    return {
        "format": "focus-voiceprint/1",
        "vector": [_num(v, -1e6, 1e6) for v in vec], "embedder": _text(vp.get("embedder")),
        "dim": len(vec), "duration_s": _num(vp.get("duration_s"), 0, 3600),
        "source": clean_source,
        "warnings": [_text(w, 400) for w in (vp.get("warnings") or [])[:10]],
    }


def validate_diarization(d, expected_ms: int) -> dict:
    if not isinstance(d, dict):
        raise ValueError("diarization missing")
    out = {}
    for key in ("turns", "overlaps", "speech"):
        items = d.get(key, [])
        if not isinstance(items, list) or len(items) > MAX_TURNS:
            raise ValueError("too many turns")
        clean = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("bad turn")
            row = {"start": _num(item.get("start"), 0, expected_ms / 1000 + 1),
                   "end": _num(item.get("end"), 0, expected_ms / 1000 + 1)}
            if row["end"] < row["start"]:
                raise ValueError("bad turn")
            row["speaker"] = None if item.get("speaker") is None else _text(item["speaker"])
            clean.append(row)
        out[key] = clean
    out["speakers"] = [_text(x) for x in (d.get("speakers") or [])[:MAX_SPEAKERS * 4]]
    return out


def validate_analysis(body, expected_ms: int) -> dict:
    """Speakers, sample spans, warnings and clip audio, checked and never repaired."""
    import base64
    if not isinstance(body, dict) or not isinstance(body.get("speakers"), list):
        raise ValueError("speakers missing")
    if len(body["speakers"]) > MAX_SPEAKERS:
        raise ValueError("too many speakers")
    duration = body.get("duration_ms")
    if type(duration) is not int or abs(duration - expected_ms) > 80:
        raise ValueError("analysis is not aligned with the canonical video")
    speakers = []
    for item in body["speakers"]:
        sample = item.get("sample")
        if sample is not None:
            sample = {"start": _num(sample.get("start"), 0, duration / 1000 + 0.1),
                      "end": _num(sample.get("end"), 0, duration / 1000 + 0.1)}
            if not 0 < sample["end"] - sample["start"] <= 8.5:
                raise ValueError("bad sample span")
        clip = item.get("sample_wav_b64")
        if clip is not None:
            if not isinstance(clip, str) or len(clip) > MAX_CLIP_B64:
                raise ValueError("bad clip")
            if sample is None:
                raise ValueError("clip without span")
            raw = base64.b64decode(clip, validate=True)
            try:
                validate_wav(raw, round((sample["end"] - sample["start"]) * 1000), 8.5)
            except ApiError:
                raise ValueError("bad clip audio") from None
        usable = item.get("usable")
        if not isinstance(usable, bool):
            raise ValueError("bad usable flag")
        vp = validate_voiceprint(item["voiceprint"]) if item.get("voiceprint") else None
        if usable and vp is None:
            raise ValueError("usable speaker without voiceprint")
        refusal = item.get("refusal")
        speakers.append({
            "speaker": _text(item.get("speaker")),
            "speech_s": _num(item.get("speech_s"), 0, 3600), "clean_s": _num(item.get("clean_s"), 0, 3600),
            "overlap_fraction": _num(item.get("overlap_fraction"), 0, 1),
            "usable": usable, "refusal": _text(refusal, 400) if refusal else None,
            "warnings": [_text(w, 400) for w in (item.get("warnings") or [])[:10]],
            "sample": sample, "sample_wav_b64": clip, "voiceprint": vp,
        })
    return {
        "duration_ms": duration, "diarization": validate_diarization(body.get("diarization"), duration),
        "speakers": speakers, "embedder": _text(body.get("embedder")),
        "warnings": [_text(w, 400) for w in (body.get("warnings") or [])[:10]],
    }


def validate_enrollment(body) -> dict:
    """Either a refusal message from the enrollment rules or a checked voiceprint."""
    if not isinstance(body, dict):
        raise ValueError("bad enrollment")
    if body.get("refused") is not None:
        return {"refused": _text(body["refused"], 400)}
    return {"voiceprint": validate_voiceprint(body.get("voiceprint")),
            "warnings": [_text(w, 400) for w in (body.get("warnings") or [])[:10]]}


def validate_visibility(body, expected_ms: int) -> list[dict]:
    items = body.get("visible") if isinstance(body, dict) else None
    if not isinstance(items, list) or len(items) > MAX_TURNS:
        raise ValueError("visible spans missing")
    out = []
    for item in items:
        start, end = item["start_ms"], item["end_ms"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= expected_ms + 1000:
            raise ValueError("bad span")
        out.append({"start_ms": start, "end_ms": min(end, expected_ms)})
    return out


def validate_regions(body, expected_ms: int) -> list[dict]:
    items = body.get("regions") if isinstance(body, dict) else None
    if not isinstance(items, list) or len(items) > MAX_REGIONS:
        raise ValueError("regions missing")
    out = []
    for item in items:
        start, end, label = item["start_ms"], item["end_ms"], item["label"]
        if (type(start) is not int or type(end) is not int or label not in ("target", "uncertain")
                or not 0 <= start < end <= expected_ms + 200):
            raise ValueError("bad region")
        out.append({"start_ms": start, "end_ms": min(end, expected_ms), "label": label,
                    "reason": _text(item.get("reason", ""), 80)})
    return out


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
        path, media_type = bridge.media(task_id)
        return FileResponse(
            path, media_type=media_type,
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
            task = bridge._current(task_id, kind=("extract", "isolate"))
            expected, kind, regions = task.duration_ms, task.kind, task.regions
            if kind == "isolate" and regions is None:
                raise ApiError("INVALID_REQUEST", "regions must be sent before the audio",
                               status_code=400)
        limit = bridge.max_audio_bytes if kind == "isolate" else MAX_AUDIO_BYTES
        data = await bounded_body(request, limit)
        duration = validate_wav(data, expected, bridge.max_audio_s if kind == "isolate" else 15.0)
        engine = request.headers.get("x-focus-engine", "audio_only" if kind == "isolate" else "dolphin")
        if engine not in KNOWN_ENGINES or (kind == "isolate") != (engine == "audio_only"):
            raise ApiError("INVALID_REQUEST", "unknown isolation engine", status_code=400)
        result = (data, duration, engine, regions) if kind == "isolate" else (data, duration, engine)
        bridge.complete(task_id, result, kind=kind)
        return {"accepted": True}

    async def _json_result(task_id: str, request: Request, kind: str, limit: int, validate):
        import json
        bridge.authorize(request)
        with bridge._condition:
            expected = bridge._current(task_id, kind=kind).duration_ms
        try:
            return json.loads(await bounded_body(request, limit)), expected, validate
        except ValueError:
            raise ApiError("INVALID_REQUEST", f"invalid worker {kind} result", status_code=400) from None

    async def _accept(task_id: str, request: Request, kind: str, limit: int, validate, *, store=None):
        body, expected, validate = await _json_result(task_id, request, kind, limit, validate)
        try:
            checked = validate(body, expected)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ApiError("INVALID_REQUEST", f"invalid worker {kind} result", status_code=400) from None
        if store is not None:
            with bridge._condition:
                store(bridge._current(task_id, kind=kind), checked)
        else:
            bridge.complete(task_id, checked, kind=kind)
        return {"accepted": True}

    @app.post("/worker/tasks/{task_id}/analysis")
    async def analysis(task_id: str, request: Request):
        return await _accept(task_id, request, "analyze", MAX_ANALYSIS_BYTES, validate_analysis)

    @app.post("/worker/tasks/{task_id}/enrollment")
    async def enrollment(task_id: str, request: Request):
        return await _accept(task_id, request, "enroll", 256 * 1024,
                             lambda body, _ms: validate_enrollment(body))

    @app.post("/worker/tasks/{task_id}/visibility")
    async def visibility(task_id: str, request: Request):
        return await _accept(task_id, request, "visibility", 256 * 1024, validate_visibility)

    @app.post("/worker/tasks/{task_id}/regions")
    async def regions(task_id: str, request: Request):
        def store(task, checked):
            task.regions = checked
        return await _accept(task_id, request, "isolate", 512 * 1024, validate_regions, store=store)

    @app.post("/worker/tasks/{task_id}/transcript")
    async def transcript(task_id: str, request: Request):
        bridge.authorize(request)
        with bridge._condition:
            expected = bridge._current(task_id, kind="transcribe").duration_ms
        import json
        try:
            body = json.loads(await bounded_body(request, 1024 * 1024))
            segments = validate_transcript(body, expected)
        except (ValueError, TypeError, KeyError):
            raise ApiError(
                "INVALID_REQUEST", "invalid worker transcript", status_code=400
            ) from None
        bridge.complete(task_id, segments, kind="transcribe")
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


def add_stream_worker_routes(app, bridge: RemoteBridge, hub) -> None:
    """Outbound-poll relay for the continuous live path (same worker credential)."""
    def check_id(live_id: str):
        if len(live_id) != 32 or any(c not in "0123456789abcdef" for c in live_id):
            raise not_found("stream task expired or unavailable")

    @app.post("/worker/stream/{live_id}/poll")
    def stream_poll(live_id: str, request: Request):
        bridge.authorize(request)
        check_id(live_id)
        body = hub.worker_poll(live_id, 0.4)
        if body is None:
            return Response(status_code=204)
        return Response(body, media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store"})

    @app.post("/worker/stream/{live_id}/out")
    async def stream_out(live_id: str, request: Request):
        bridge.authorize(request)
        check_id(live_id)
        data = await bounded_body(request, 4 * 1024 * 1024)
        return hub.worker_out(live_id, data)
