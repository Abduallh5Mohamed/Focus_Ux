"""Experimental near-live sessions (docs/04_REALTIME_GATE.md).

Sessions live in memory; chunk media and jobs use the normal repository, so the
single dispatcher thread executes every chunk with the same worker, the same
selected target and the same tracking/voice-follow path as an upload.

Honest-state rules: every chunk ends in an explicit state (ready, missing,
target_lost, uncertain, failed, undecodable, deferred); nothing is dropped
silently. Overload switches the session to record-then-process.
"""
from __future__ import annotations

import hashlib
import io
import logging
import shutil
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from services.worker.models import AudioStatus, Job, JobStage, JobStatus, TranscriptStatus
from services.worker.worker import LIVE_CHUNK_PREFIX

from . import live_decode
from .db import VideoRecord
from .errors import ApiError, not_found
from .live_metrics import evaluate_gate, summarize
from .media_probe import ProbeError, probe_video

logger = logging.getLogger("focus_api.live")

IOU_MIN = 0.2
AMBIGUITY_MARGIN = 0.1
TAIL_CAP = 8 * 1024 * 1024
FINAL_PREFIX = "live-final:"
CHUNK_AUDIO_STATES = ("ready",)


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def match_anchor(anchor, faces):
    """Pick the face continuing ``anchor``. Returns (face|None, state)."""
    scored = sorted(((_iou(anchor, f.bbox), f) for f in faces), key=lambda t: -t[0])
    if not scored or scored[0][0] < IOU_MIN:
        return None, "target_lost"
    if len(scored) > 1 and scored[1][0] >= IOU_MIN and scored[0][0] - scored[1][0] < AMBIGUITY_MARGIN:
        return None, "uncertain"
    return scored[0][1], "ok"


@dataclass
class Chunk:
    seq: int
    capture_start_ms: int
    duration_ms: int
    digest: str = ""
    state: str = "received"
    video_id: Optional[str] = None
    job_id: Optional[str] = None
    wav_path: Optional[str] = None
    error: Optional[dict] = None
    ingested_at: float = 0.0
    ready_at: Optional[float] = None
    processing_s: Optional[float] = None
    detect_s: Optional[float] = None
    warnings: list = field(default_factory=list)


@dataclass
class LiveSession:
    live_id: str
    owner: str
    directory: Path
    created: float
    last_seen: float
    phase: str = "awaiting_chunk"  # awaiting_chunk|awaiting_target|live|stopped|finalizing|done|failed
    mode: str = "live"  # live | record_then_process
    target_face_id: Optional[str] = None
    anchor: Optional[tuple] = None
    first_video_id: Optional[str] = None
    chunks: dict = field(default_factory=dict)
    next_seq: int = 0
    header: bytes = b""
    header_done: bool = False
    tail: bytes = b""
    gap: bool = False
    dispatches: int = 0
    duplicates: int = 0
    late_rejected: int = 0
    out_of_order: int = 0
    depth_samples: list = field(default_factory=list)
    overload_seq: Optional[int] = None
    playback: Optional[dict] = None
    full_video_id: Optional[str] = None
    final_job_id: Optional[str] = None
    final_error: Optional[dict] = None
    error: Optional[dict] = None
    lock: threading.RLock = field(default_factory=threading.RLock)


class LiveManager:
    def __init__(self, *, settings, storage, repo, dispatcher, worker, ffmpeg="ffmpeg"):
        self.settings, self.storage, self.repo = settings, storage, repo
        self.dispatcher, self.worker, self.ffmpeg = dispatcher, worker, ffmpeg
        self.sessions: dict[str, LiveSession] = {}
        self._lock = threading.Lock()
        dispatcher.live_handler = self.handle

    @property
    def root(self) -> Path:
        return self.settings.storage_root / "live"

    # -- startup -------------------------------------------------------------
    def recover(self) -> None:
        """Sessions are memory-only: delete the media a dead process left behind."""
        if not self.root.is_dir():
            return
        for manifest in self.root.glob("*/manifest.txt"):
            for line in manifest.read_text().splitlines():
                if line.startswith("full:"):
                    continue  # a finished recording stays available to its result page
                video_id = line.split(":", 1)[-1].strip()
                if video_id and self.repo.get_video(video_id) is not None:
                    self.repo.mark_video_deleted(video_id)
                    self.dispatcher.enqueue_cleanup(video_id)
            shutil.rmtree(manifest.parent, ignore_errors=True)

    # -- helpers -------------------------------------------------------------
    def _get(self, live_id: str, owner: str) -> LiveSession:
        s = self.sessions.get(live_id)
        if s is None or s.owner != owner:
            raise not_found("live session not found")
        return s

    def _manifest(self, s: LiveSession, kind: str, video_id: str) -> None:
        with open(s.directory / "manifest.txt", "a", encoding="utf-8") as handle:
            handle.write(f"{kind}:{video_id}\n")

    def _expire_idle(self) -> None:
        now = time.monotonic()
        for s in list(self.sessions.values()):
            if s.phase in ("awaiting_chunk", "awaiting_target", "live") and (
                now - s.last_seen > self.settings.live_idle_timeout_s
            ):
                logger.info("live session %s idle; stopping", s.live_id)
                try:
                    self.stop(s.live_id, s.owner)
                except ApiError:
                    pass

    def _active(self) -> Optional[LiveSession]:
        return next(
            (s for s in self.sessions.values()
             if s.phase in ("awaiting_chunk", "awaiting_target", "live", "stopped", "finalizing")),
            None,
        )

    # -- session -------------------------------------------------------------
    def create(self, owner: str) -> LiveSession:
        if not self.settings.live_enabled:
            raise ApiError("LIVE_DISABLED", "live mode is disabled on this server", status_code=403)
        with self._lock:
            self._expire_idle()
            if self._active() is not None:
                raise ApiError(
                    "GPU_BUSY",
                    "another live session is using the single worker; try again when it ends",
                    status_code=409, retryable=True,
                )
            live_id = uuid.uuid4().hex
            directory = self.root / live_id
            directory.mkdir(parents=True, exist_ok=True)
            now = time.monotonic()
            s = LiveSession(live_id, owner, directory, now, now)
            self.sessions[live_id] = s
            return s

    # -- ingest --------------------------------------------------------------
    def ingest(self, live_id, owner, seq, capture_start_ms, duration_ms, data: bytes) -> dict:
        s = self._get(live_id, owner)
        st = self.settings
        if not 0 <= seq < st.live_max_chunks:
            raise ApiError("LIMIT_EXCEEDED", "chunk sequence out of range", status_code=400)
        if not (100 <= duration_ms <= 10_000) or capture_start_ms < 0 or not data:
            raise ApiError("INVALID_REQUEST", "invalid chunk timing or empty body", status_code=400)
        digest = hashlib.sha256(data).hexdigest()
        with s.lock:
            s.last_seen = time.monotonic()
            if seq in s.chunks:
                prior = s.chunks[seq]
                if prior.state == "missing":
                    s.late_rejected += 1
                    raise ApiError("CHUNK_TOO_LATE", "chunk was already declared missing", status_code=409)
                if prior.digest and prior.digest != digest:
                    raise ApiError("CHUNK_CONFLICT", "sequence already received with other bytes", status_code=409)
                s.duplicates += 1
                return {"seq": seq, "state": prior.state, "duplicate": True, "expected_seq": s.next_seq}
            if s.phase not in ("awaiting_chunk", "awaiting_target", "live"):
                raise ApiError("INVALID_REQUEST", "session is not accepting chunks", status_code=409)
            if seq < s.next_seq:
                s.late_rejected += 1
                raise ApiError("CHUNK_TOO_LATE", "chunk was already declared missing", status_code=409)
            if seq > s.next_seq:
                s.out_of_order += 1
                for gone in range(s.next_seq, seq):
                    s.chunks[gone] = Chunk(gone, 0, 0, state="missing", error={
                        "code": "CHUNK_MISSING", "message": "chunk never arrived", "retryable": False})
                s.gap = True
            chunk = Chunk(seq, capture_start_ms, duration_ms, digest, ingested_at=time.monotonic())
            s.chunks[seq] = chunk
            s.next_seq = seq + 1
            with open(s.directory / "stream.webm", "ab") as spool:
                spool.write(data)
            self._decode_into(s, chunk, data)
            if chunk.state == "received":
                self._schedule(s, chunk)
            elif seq == 0:
                s.phase = "failed"
                s.error = chunk.error
            return {"seq": seq, "state": chunk.state, "duplicate": False, "expected_seq": s.next_seq}

    def _decode_into(self, s: LiveSession, chunk: Chunk, data: bytes) -> None:
        def fail(code, message):
            chunk.state = "undecodable"
            chunk.error = {"code": code, "message": message, "retryable": False}

        if not s.header_done:
            clusters = live_decode.find_clusters(data)
            if not clusters:
                if chunk.seq == 0 and not data.startswith(live_decode.EBML_MAGIC):
                    return fail("INVALID_MEDIA", "stream does not start with a WebM header")
                s.header += data
                return fail("INVALID_MEDIA", "no media cluster in this chunk yet")
            s.header += data[:clusters[0]]
            s.header_done = True
            region = data[clusters[0]:]
        elif s.gap:
            clusters = live_decode.find_clusters(data)
            if not clusters:
                s.tail = b""
                return fail("INVALID_MEDIA", "no cluster boundary after a missing chunk")
            region = data[clusters[0]:]
            s.gap = False
        else:
            region = s.tail + data
        if not s.header.startswith(live_decode.EBML_MAGIC):
            return fail("INVALID_MEDIA", "stream header missing")
        timecode = live_decode.cluster_timecode_ms(region, 0)
        if timecode is None:
            chunk.warnings.append("cluster timecode unreadable; window assumed at cluster start")
            timecode = chunk.capture_start_ms
        start_s = max(0.0, (chunk.capture_start_ms - timecode) / 1000)
        video_id = uuid.uuid4().hex
        path = self.storage.media_path(video_id, ".mp4")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            live_decode.decode_window(
                s.header + region, path, start_s=start_s,
                duration_s=chunk.duration_ms / 1000, ffmpeg=self.ffmpeg,
            )
            probe = probe_video(path)
        except (live_decode.DecodeError, ProbeError):
            path.unlink(missing_ok=True)
            fail("INVALID_MEDIA", "chunk could not be decoded")
        else:
            self._register_video(s, video_id, path, probe, "chunk")
            chunk.video_id = video_id
            if abs(probe.duration_ms - chunk.duration_ms) > 300:
                chunk.warnings.append(
                    f"decoded {probe.duration_ms} ms for a {chunk.duration_ms} ms window"
                )
        # Keep bytes since the last cluster start for the next, non-independent chunk.
        marks = live_decode.find_clusters(region)
        keep = region[marks[-1]:] if marks else region
        s.tail = keep if len(keep) <= TAIL_CAP else b""
        if not s.tail:
            s.gap = True

    def _register_video(self, s, video_id, path, probe, kind) -> None:
        self.repo.create_video(VideoRecord(
            video_id=video_id, session_id=s.owner, original_path=str(path),
            canonical_path=str(path), mime_type="video/mp4", size_bytes=path.stat().st_size,
            duration_ms=probe.duration_ms, width=probe.width, height=probe.height,
            fps=probe.fps, faces_status="pending", faces_error_code=None,
            faces_error_message=None, faces_error_retryable=False,
            created_at=time.time(), deleted_at=None,
        ))
        self._manifest(s, kind, video_id)

    def _depth(self, s: LiveSession) -> int:
        return sum(1 for c in s.chunks.values() if c.state in ("queued", "processing"))

    def _dispatch(self, s: LiveSession, seq: int, tag: str = "chunk") -> None:
        s.dispatches += 1
        self.dispatcher.enqueue_live(f"{tag}:{s.live_id}:{seq}:{s.dispatches}")

    def _schedule(self, s: LiveSession, chunk: Chunk) -> None:
        if chunk.seq == 0:
            s.phase = "awaiting_target"
            self._dispatch(s, 0)  # detection only until a target is chosen
            return
        if s.mode == "live" and self._depth(s) >= self.settings.live_max_queue_depth:
            s.mode, s.overload_seq = "record_then_process", chunk.seq
        if s.mode == "record_then_process":
            chunk.state = "deferred"
        elif s.target_face_id is None:
            chunk.state = "awaiting_target"
        else:
            chunk.state = "queued"
            self._dispatch(s, chunk.seq)
        s.depth_samples.append(self._depth(s))

    # -- target / stop -------------------------------------------------------
    def set_target(self, live_id, owner, face_id: str) -> LiveSession:
        s = self._get(live_id, owner)
        with s.lock:
            if s.target_face_id is not None:
                if s.target_face_id == face_id:
                    return s
                raise ApiError(
                    "INVALID_REQUEST",
                    "target cannot change inside a session; start a new session",
                    status_code=409,
                )
            first = s.chunks.get(0)
            if s.phase != "awaiting_target" or first is None or first.video_id is None:
                raise ApiError("NOT_READY", "face candidates are not ready", status_code=409, retryable=True)
            face = self.repo.get_face(first.video_id, face_id)
            if face is None:
                raise ApiError("FACE_NOT_FOUND", "selected face is not a candidate", status_code=404)
            s.target_face_id, s.anchor, s.first_video_id = face_id, tuple(face.bbox), first.video_id
            s.phase = "live"
            first.state = "queued"
            self._dispatch(s, 0)
            for seq in sorted(s.chunks):
                c = s.chunks[seq]
                if seq and c.state == "awaiting_target":
                    c.state = "queued"
                    self._dispatch(s, seq)
            return s

    def stop(self, live_id, owner) -> LiveSession:
        s = self._get(live_id, owner)
        with s.lock:
            if s.phase in ("stopped", "finalizing", "done", "failed"):
                return s
            s.phase = "stopped"
            for seq in sorted(s.chunks):
                c = s.chunks[seq]
                if c.state == "deferred":
                    c.state = "queued"
                    self._dispatch(s, seq)
            self._dispatch(s, 0, tag="final")
        return s

    def set_playback(self, live_id, owner, report: dict) -> None:
        s = self._get(live_id, owner)
        with s.lock:
            s.playback = report

    def chunk_audio(self, live_id, owner, seq: int) -> Path:
        s = self._get(live_id, owner)
        c = s.chunks.get(seq)
        if c is None:
            raise not_found("chunk not found")
        if c.state != "ready" or not c.wav_path or not Path(c.wav_path).is_file():
            raise ApiError("NOT_READY", f"chunk audio is {c.state}", status_code=409, retryable=c.state in (
                "received", "queued", "processing", "deferred", "awaiting_target"))
        return Path(c.wav_path)

    # -- dispatcher thread ---------------------------------------------------
    def handle(self, ident: str) -> None:
        tag, live_id, seq, _n = ident.split(":")
        s = self.sessions.get(live_id)
        if s is None:
            return
        try:
            if tag == "final":
                self._finalize(s)
            else:
                self._process_chunk(s, s.chunks[int(seq)])
        except Exception:
            logger.exception("live task failed: %s", ident)
            if tag == "final":
                s.phase, s.final_error = "failed", {
                    "code": "PROCESSING_FAILED", "message": "final transcript failed", "retryable": True}

    def _process_chunk(self, s: LiveSession, c: Chunk) -> None:
        if s.phase in ("failed", "done"):
            c.state = "failed"
            return
        started = time.monotonic()
        c.state = "processing" if s.target_face_id else c.state
        video = self.repo.get_video(c.video_id)
        if not (c.seq == 0 and video is not None and video.faces_status == "ready"):
            self.dispatcher.process_one("faces", c.video_id)
            video = self.repo.get_video(c.video_id)
        if video is None or video.deleted:
            c.state = "failed"
            return
        if video.faces_status != "ready":
            c.state = "failed"
            c.error = {"code": video.faces_error_code or "PROCESSING_FAILED",
                       "message": video.faces_error_message or "face detection failed",
                       "retryable": bool(video.faces_error_retryable)}
            return
        c.detect_s = time.monotonic() - started
        if s.target_face_id is None:
            c.state = "awaiting_target"  # seq 0 detection for the picker
            return
        faces = self.repo.get_faces(c.video_id)
        if c.seq == 0:
            face = self.repo.get_face(c.video_id, s.target_face_id)
            outcome = "ok" if face else "target_lost"
        else:
            face, outcome = match_anchor(s.anchor, faces)
        if face is None:
            c.state = outcome
            c.error = {
                "code": "TARGET_LOST" if outcome == "target_lost" else "TARGET_UNCERTAIN",
                "message": "الوجه المختار مش ظاهر في المقطع ده" if outcome == "target_lost"
                else "مش متأكدين من الوجه في المقطع ده",
                "retryable": False,
            }
            c.ready_at = time.monotonic()
            return
        job_id = uuid.uuid4().hex
        self.repo.create_job(Job(
            job_id=job_id, video_id=c.video_id, face_id=face.face_id,
            client_request_id=f"{LIVE_CHUNK_PREFIX}{s.live_id}:{c.seq}",
            video_path=video.canonical_path, job_dir=str(self.storage.job_dir(job_id)),
        ))
        c.job_id = job_id
        job = self.worker.process(job_id)
        c.processing_s = time.monotonic() - started
        c.ready_at = time.monotonic()
        if job.status is JobStatus.COMPLETED and job.audio_status is AudioStatus.READY:
            c.state, c.wav_path = "ready", job.wav_path
            s.anchor = tuple(face.bbox)
            c.warnings.extend(job.audio_warnings)
        else:
            c.state = "failed"
            e = job.error
            c.error = {"code": e.code, "message": e.message, "retryable": e.retryable} if e else {
                "code": "PROCESSING_FAILED", "message": "chunk failed", "retryable": True}

    # -- final transcript ----------------------------------------------------
    def _finalize(self, s: LiveSession) -> None:
        with s.lock:
            s.phase = "finalizing"
        try:
            self._build_final(s)
            s.phase = "done"
        except ApiError as exc:
            s.phase, s.final_error = "failed", exc.payload()["error"]
        finally:
            timer = threading.Timer(60.0, self.cleanup_chunks, args=(s.live_id,))
            timer.daemon = True
            timer.start()

    def _build_final(self, s: LiveSession) -> None:
        stream = s.directory / "stream.webm"
        ready = [c for c in s.chunks.values() if c.state == "ready"]
        if not ready or not stream.is_file():
            raise ApiError("NO_AUDIO", "no chunk produced isolated audio", status_code=422)
        full_id = uuid.uuid4().hex
        path = self.storage.media_path(full_id, ".mp4")
        path.parent.mkdir(parents=True, exist_ok=True)
        total_s = max(c.capture_start_ms + c.duration_ms for c in s.chunks.values()) / 1000
        try:
            live_decode.decode_window(stream.read_bytes(), path, start_s=0, duration_s=total_s + 1,
                                      ffmpeg=self.ffmpeg)
            probe = probe_video(path)
        except (live_decode.DecodeError, ProbeError) as exc:
            path.unlink(missing_ok=True)
            raise ApiError("INVALID_MEDIA", "the full recording could not be decoded", status_code=422) from exc
        self._register_video(s, full_id, path, probe, "full")
        s.full_video_id = full_id
        samples = int(probe.duration_ms * 16)
        pcm = bytearray(samples * 2)
        for c in ready:
            with wave.open(c.wav_path, "rb") as wav:
                if (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) != (1, 16000, 2):
                    raise ApiError("PROCESSING_FAILED", "unexpected chunk audio format", status_code=500)
                frames = wav.readframes(wav.getnframes())
            offset = c.capture_start_ms * 16 * 2
            frames = frames[:max(0, len(pcm) - offset)]
            pcm[offset:offset + len(frames)] = frames
        job_id = uuid.uuid4().hex
        job_dir = self.storage.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        wav_path = job_dir / "isolated.wav"
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(bytes(pcm))
        wav_path.write_bytes(buffer.getvalue())
        gaps = [c.seq for c in s.chunks.values() if c.state != "ready"]
        job = Job(
            job_id=job_id, video_id=full_id, face_id=s.target_face_id,
            client_request_id=f"{FINAL_PREFIX}{s.live_id}", video_path=str(path),
            job_dir=str(job_dir), status=JobStatus.COMPLETED, stage=JobStage.TRANSCRIBING,
            audio_status=AudioStatus.READY, transcript_status=TranscriptStatus.PENDING,
            wav_path=str(wav_path), duration_ms=probe.duration_ms,
            audio_warnings=[f"live recording: chunks without audio: {gaps}"] if gaps else [],
        )
        self.repo.create_job(job)
        s.final_job_id = job_id
        self.worker.transcribe_completed(job_id)
        (s.directory / "stream.webm").unlink(missing_ok=True)

    def cleanup_chunks(self, live_id: str) -> None:
        s = self.sessions.get(live_id)
        if s is None:
            return
        for c in s.chunks.values():
            if c.video_id:
                self.repo.mark_video_deleted(c.video_id)
                self.dispatcher.enqueue_cleanup(c.video_id)
                c.state = c.state if c.state != "ready" else "ready"
                c.wav_path = None
        if s.first_video_id:
            s.first_video_id = None
        shutil.rmtree(s.directory, ignore_errors=True)

    # -- views ---------------------------------------------------------------
    def view(self, live_id, owner) -> dict:
        s = self._get(live_id, owner)
        with s.lock:
            first = self.repo.get_video(s.chunks[0].video_id) if 0 in s.chunks and s.chunks[0].video_id else None
            return {
                "live_session_id": s.live_id, "experimental": True, "phase": s.phase,
                "mode": s.mode, "chunk_ms": self.settings.live_chunk_ms,
                "target_face_id": s.target_face_id,
                "first_video_id": s.chunks[0].video_id if 0 in s.chunks else s.first_video_id,
                "faces_status": first.faces_status if first else "pending",
                "queue_depth": self._depth(s), "expected_seq": s.next_seq,
                "overload_at_seq": s.overload_seq, "error": s.error,
                "counts": {"duplicates": s.duplicates, "out_of_order": s.out_of_order,
                           "late_rejected": s.late_rejected},
                "chunks": [
                    {"seq": c.seq, "state": c.state, "capture_start_ms": c.capture_start_ms,
                     "duration_ms": c.duration_ms, "error": c.error, "warnings": c.warnings}
                    for _, c in sorted(s.chunks.items())
                ],
                "final": {"status": {"done": "ready", "failed": "failed"}.get(
                              s.phase, "pending" if s.phase in ("stopped", "finalizing") else None),
                          "video_id": s.full_video_id, "job_id": s.final_job_id,
                          "error": s.final_error},
            }

    def metrics(self, live_id, owner, *, quality_checked=False) -> dict:
        s = self._get(live_id, owner)
        with s.lock:
            rows = [{
                "seq": c.seq, "state": c.state, "duration_ms": c.duration_ms,
                "processing_s": c.processing_s,
                "server_latency_s": (c.ready_at - c.ingested_at) if c.ready_at and c.ingested_at else None,
            } for c in s.chunks.values()]
            summary = summarize(
                chunks=rows, depth_samples=s.depth_samples, duplicates_ingested=s.duplicates,
                playback=s.playback, overload_seq=s.overload_seq,
            )
        return {"summary": summary, "gate": evaluate_gate(summary, quality_checked=quality_checked),
                "experimental": True}
