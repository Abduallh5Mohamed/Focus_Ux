"""Continuous live stream relay (experimental, behind ``live_stream_enabled``).

Browser -> server: batches of mic PCM16 + JPEG frames (``stream_proto``), posted
every ~200 ms. Server -> GPU worker: the same records, long-polled by the
outbound-only worker. Worker -> server: isolated parts in order. Server ->
browser: long-polled parts. One session at a time, one owner, explicit state for
every part, nothing dropped silently (dropped/duplicated/missing input is counted
and fails the gate).
"""
from __future__ import annotations

import io
import logging
import shutil
import threading
import time
import uuid
import wave
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from services.worker import stream_proto as sp

from .errors import ApiError, not_found
from .live_metrics import evaluate_stream_gate, summarize_stream

logger = logging.getLogger("focus_api.live_stream")

INBOX_CAP_BYTES = 6 * 1024 * 1024
WORKER_SILENCE_S = 8.0
CLOSE_GRACE_S = 15.0
PHASES_ACTIVE = ("awaiting_worker", "awaiting_target", "live", "stopping")


@dataclass
class StreamSession:
    live_id: str
    owner: str
    directory: Path
    created: float
    last_seen: float
    phase: str = "awaiting_worker"
    cond: threading.Condition = field(default_factory=threading.Condition)
    inbox: deque = field(default_factory=deque)
    inbox_bytes: int = 0
    controls: list = field(default_factory=list)
    next_batch: int = 0
    batches_duplicate: int = 0
    batches_missing: int = 0
    frames_dropped: int = 0
    audio_samples_in: int = 0
    marks: deque = field(default_factory=lambda: deque(maxlen=4000))  # (end_sample, monotonic)
    faces: list = field(default_factory=list)
    target_bbox: Optional[list] = None
    parts: list = field(default_factory=list)
    next_part: int = 0
    parts_duplicate: int = 0
    parts_missing: int = 0
    worker_claimed: bool = False
    worker_seen: float = 0.0
    worker_stats: Optional[dict] = None
    playback: Optional[dict] = None
    error: Optional[dict] = None
    stop_at: float = 0.0
    wav_path: Optional[Path] = None
    config: dict = field(default_factory=dict)


class StreamHub:
    def __init__(self, *, settings, manager, bridge):
        self.settings, self.manager, self.bridge = settings, manager, bridge
        self.sessions: dict[str, StreamSession] = {}
        self._lock = threading.Lock()
        if bridge is not None:
            bridge.stream_source = self
        manager.extra_active = self.active

    @property
    def root(self) -> Path:
        return self.settings.storage_root / "live-stream"

    # -- helpers -------------------------------------------------------------
    def active(self) -> Optional[StreamSession]:
        return next((s for s in self.sessions.values() if s.phase in PHASES_ACTIVE), None)

    def _get(self, live_id: str, owner: str) -> StreamSession:
        s = self.sessions.get(live_id)
        if s is None or s.owner != owner:
            raise not_found("live stream session not found")
        return s

    @staticmethod
    def _fail(s: StreamSession, code: str, message: str) -> None:
        s.phase = "failed"
        s.error = {"code": code, "message": message, "retryable": False}
        with s.cond:
            s.cond.notify_all()

    def _expire(self) -> None:
        now = time.monotonic()
        for s in list(self.sessions.values()):
            if s.phase not in PHASES_ACTIVE:
                continue
            if s.phase == "stopping" and now - s.stop_at > CLOSE_GRACE_S:
                self._finish(s, "the worker did not confirm the end of the stream")
            elif s.phase != "stopping" and now - s.last_seen > self.settings.live_idle_timeout_s:
                logger.info("stream session %s idle; stopping", s.live_id)
                self._begin_stop(s)
            elif s.worker_claimed and now - s.worker_seen > WORKER_SILENCE_S and s.phase != "stopping":
                self._fail(s, "WORKER_LOST", "the GPU worker stopped answering")

    # -- browser side --------------------------------------------------------
    def create(self, owner: str) -> StreamSession:
        st = self.settings
        if not (st.live_enabled and st.live_stream_enabled):
            raise ApiError("LIVE_DISABLED", "continuous live mode is disabled on this server", status_code=403)
        if self.bridge is None or not self.bridge.status()["connected"]:
            raise ApiError("WORKER_OFFLINE", "the GPU worker is not connected", status_code=503, retryable=True)
        with self._lock:
            self._expire()
            self.manager._expire_idle()
            if self.active() is not None or self.manager._active() is not None:
                raise ApiError("GPU_BUSY", "another live session is using the single worker",
                               status_code=409, retryable=True)
            live_id = uuid.uuid4().hex
            directory = self.root / live_id
            directory.mkdir(parents=True, exist_ok=True)
            now = time.monotonic()
            s = StreamSession(live_id, owner, directory, now, now, worker_seen=now)
            s.config = {
                "sample_rate": sp.SAMPLE_RATE, "fps": sp.FPS, "window_s": st.live_stream_window_s,
                "hop_s": st.live_stream_hop_s, "lookahead_s": st.live_stream_lookahead_s,
                "crossfade_ms": st.live_stream_crossfade_ms,
            }
            self.sessions[live_id] = s
            return s

    def ingest(self, live_id: str, owner: str, body: bytes) -> dict:
        s = self._get(live_id, owner)
        try:
            seq, records = sp.unpack_batch(body)
        except sp.ProtoError as exc:
            raise ApiError("INVALID_REQUEST", f"bad stream batch: {exc}", status_code=400) from None
        now = time.monotonic()
        with s.cond:
            s.last_seen = now
            if s.phase not in ("awaiting_worker", "awaiting_target", "live"):
                raise ApiError("INVALID_REQUEST", "session is not accepting media", status_code=409)
            if seq < s.next_batch:
                s.batches_duplicate += 1
                return {"expected_batch": s.next_batch, "duplicate": True}
            if seq > s.next_batch:
                s.batches_missing += seq - s.next_batch
            s.next_batch = seq + 1
            for rec in records:
                kind, pos, data = rec
                if kind == sp.K_AUDIO:
                    s.audio_samples_in = max(s.audio_samples_in, pos + len(data) // 2)
                    s.marks.append((pos + len(data) // 2, now))
                elif kind != sp.K_FRAME:
                    continue
                if s.audio_samples_in > self.settings.live_stream_max_s * sp.SAMPLE_RATE:
                    self._fail(s, "LIMIT_EXCEEDED", "stream is longer than the allowed session length")
                    raise ApiError("LIMIT_EXCEEDED", "stream is too long", status_code=413)
                s.inbox.append(rec)
                s.inbox_bytes += len(data)
            self._cap_inbox(s)
            s.cond.notify_all()
            return {"expected_batch": s.next_batch, "duplicate": False, "phase": s.phase}

    def _cap_inbox(self, s: StreamSession) -> None:
        """Frames may be shed (counted, visible, fails the gate); audio never is."""
        if s.inbox_bytes <= INBOX_CAP_BYTES:
            return
        kept = deque()
        for rec in s.inbox:
            if rec[0] == sp.K_FRAME and s.inbox_bytes > INBOX_CAP_BYTES:
                s.inbox_bytes -= len(rec[2])
                s.frames_dropped += 1
            else:
                kept.append(rec)
        s.inbox = kept
        if s.inbox_bytes > INBOX_CAP_BYTES:
            self._fail(s, "OVERLOAD", "the GPU worker is not keeping up with the stream")

    def set_target(self, live_id: str, owner: str, bbox: list[int]) -> dict:
        s = self._get(live_id, owner)
        with s.cond:
            if s.target_bbox is not None:
                if s.target_bbox == bbox:
                    return self.view(live_id, owner)
                raise ApiError("INVALID_REQUEST", "target cannot change inside a session; start a new one",
                               status_code=409)
            if s.phase != "awaiting_target" or not s.faces:
                raise ApiError("NOT_READY", "face candidates are not ready", status_code=409, retryable=True)
            if not any(f["bbox"] == bbox for f in s.faces):
                raise ApiError("FACE_NOT_FOUND", "selected face is not a candidate", status_code=404)
            s.target_bbox = bbox
            s.controls.append({"op": "select", "bbox": bbox})
            s.cond.notify_all()
        return self.view(live_id, owner)

    def _begin_stop(self, s: StreamSession) -> None:
        with s.cond:
            if s.phase not in PHASES_ACTIVE or s.phase == "stopping":
                return
            s.phase, s.stop_at = "stopping", time.monotonic()
            s.controls.append({"op": "close"})
            s.cond.notify_all()
        if not s.worker_claimed:
            self._finish(s, None)

    def stop(self, live_id: str, owner: str) -> dict:
        self._begin_stop(self._get(live_id, owner))
        return self.view(live_id, owner)

    def out(self, live_id: str, owner: str, after: int, wait_s: float) -> Optional[bytes]:
        """Parts with index > ``after``; None after the wait when nothing new."""
        s = self._get(live_id, owner)
        self._expire()
        deadline = time.monotonic() + min(max(wait_s, 0.0), 10.0)
        with s.cond:
            s.last_seen = time.monotonic()
            while True:
                fresh = [p for p in s.parts if p["idx"] > after]
                if fresh or s.phase in ("done", "failed"):
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                s.cond.wait(remaining)
        records = []
        for p in fresh[:40]:
            records.append(sp.json_record({k: p[k] for k in ("idx", "start", "samples", "state")}))
            if p["pcm"]:
                records.append((sp.K_OUT_AUDIO, p["start"], p["pcm"]))
        records.append(sp.json_record({"phase": s.phase, "last_part": s.parts[-1]["idx"] if s.parts else -1}))
        return sp.pack_batch(fresh[-1]["idx"] if fresh else max(after, 0), records)

    def set_playback(self, live_id: str, owner: str, report: dict) -> None:
        s = self._get(live_id, owner)
        s.playback = report

    def view(self, live_id: str, owner: str) -> dict:
        s = self._get(live_id, owner)
        with s.cond:
            return {
                "live_session_id": s.live_id, "experimental": True, "transport": "stream",
                "phase": s.phase, "config": s.config, "target_bbox": s.target_bbox,
                "faces": [{"bbox": f["bbox"], "frame_size": f["frame_size"],
                           "thumbnail_url": "data:image/jpeg;base64," + f["thumbnail"]}
                          for f in s.faces],
                "parts": s.next_part, "error": s.error,
                "counts": {
                    "batches_duplicate": s.batches_duplicate, "batches_missing": s.batches_missing,
                    "frames_dropped": s.frames_dropped, "parts_duplicate": s.parts_duplicate,
                    "parts_missing": s.parts_missing,
                },
                "audio_ready": s.wav_path is not None,
                "worker_stats": s.worker_stats,
            }

    def wav(self, live_id: str, owner: str) -> Path:
        s = self._get(live_id, owner)
        if s.wav_path is None or not s.wav_path.is_file():
            raise ApiError("NOT_READY", "isolated recording is not ready", status_code=409, retryable=True)
        return s.wav_path

    def metrics(self, live_id: str, owner: str, quality_delta_db: Optional[float] = None) -> dict:
        s = self._get(live_id, owner)
        with s.cond:
            summary = summarize_stream(
                parts=[{k: p[k] for k in ("idx", "samples", "state", "server_latency_s")} for p in s.parts],
                worker_stats=s.worker_stats, playback=s.playback,
                input_counts={"batches_duplicate": s.batches_duplicate,
                              "batches_missing": s.batches_missing,
                              "frames_dropped": s.frames_dropped,
                              "parts_duplicate": s.parts_duplicate, "parts_missing": s.parts_missing},
                audio_in_s=s.audio_samples_in / sp.SAMPLE_RATE,
            )
        return {"summary": summary, "gate": evaluate_stream_gate(summary, quality_delta_db=quality_delta_db),
                "experimental": True}

    def cleanup(self, live_id: str) -> None:
        s = self.sessions.pop(live_id, None)
        if s is not None:
            shutil.rmtree(s.directory, ignore_errors=True)

    # -- worker side ---------------------------------------------------------
    def claim_pending(self) -> Optional[tuple[str, dict]]:
        """Called by the bridge's poll: hand the unclaimed active session to the worker."""
        with self._lock:
            self._expire()
            for s in self.sessions.values():
                if s.phase == "awaiting_worker" and not s.worker_claimed:
                    s.worker_claimed, s.worker_seen = True, time.monotonic()
                    s.phase = "awaiting_target"
                    return s.live_id, s.config
        return None

    def _worker_session(self, live_id: str) -> StreamSession:
        s = self.sessions.get(live_id)
        if s is None or not s.worker_claimed:
            raise not_found("stream task expired or unavailable")
        return s

    def worker_poll(self, live_id: str, wait_s: float) -> Optional[bytes]:
        s = self._worker_session(live_id)
        self._expire()  # an abandoned browser must not hold the single worker
        deadline = time.monotonic() + min(max(wait_s, 0.0), 5.0)
        with s.cond:
            while True:
                s.worker_seen = time.monotonic()
                if s.inbox or s.controls or s.phase in ("done", "failed"):
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                s.cond.wait(min(remaining, 0.25))
            records, size = [], 0
            while s.inbox and size < 1_500_000 and len(records) < sp.MAX_RECORDS - 8:
                rec = s.inbox.popleft()
                s.inbox_bytes -= len(rec[2])
                size += len(rec[2])
                records.append(rec)
            controls, s.controls = s.controls, []
            if s.phase in ("done", "failed"):
                controls.append({"op": "end"})
            records += [sp.json_record(c) for c in controls]
            return sp.pack_batch(0, records)

    def worker_out(self, live_id: str, body: bytes) -> dict:
        s = self._worker_session(live_id)
        try:
            _seq, records = sp.unpack_batch(body)
        except sp.ProtoError as exc:
            raise ApiError("INVALID_REQUEST", f"bad worker batch: {exc}", status_code=400) from None
        now = time.monotonic()
        with s.cond:
            s.worker_seen = now
            pending, batch_parts = None, []
            for kind, pos, data in records:
                if kind == sp.K_JSON:
                    pending = self._worker_json(s, data, now) or pending
                    if pending is not None and pending not in batch_parts:
                        batch_parts.append(pending)
                elif kind == sp.K_OUT_AUDIO and pending is not None:
                    if len(data) == pending["samples"] * 2 and pending["start"] == pos:
                        pending["pcm"] = data
                    else:
                        pending["state"], pending["pcm"] = "failed", b""
            for part in batch_parts:
                if part["state"] == "ready" and not part["pcm"]:
                    part["state"] = "failed"  # a ready part without audio is never played as ready
            s.cond.notify_all()
        return {"accepted": True}

    def _worker_json(self, s: StreamSession, data: bytes, now: float) -> Optional[dict]:
        import json
        try:
            msg = json.loads(data)
        except ValueError:
            return None
        if "faces" in msg and s.phase == "awaiting_target":
            s.faces = [f for f in msg["faces"] if isinstance(f.get("bbox"), list)]
        elif msg.get("event") == "selected":
            s.phase = "live"
        elif msg.get("event") == "select_failed":
            s.target_bbox = None
            s.controls.clear()
        elif msg.get("event") == "closed":
            s.worker_stats = msg.get("stats")
            self._finish(s, None)
        elif msg.get("event") == "error" and s.phase != "stopping":
            self._fail(s, "PROCESSING_FAILED", "the GPU worker stopped the stream")
        elif "part" in msg:
            idx = int(msg["part"])
            if idx < s.next_part:
                s.parts_duplicate += 1
                return None
            s.parts_missing += idx - s.next_part
            part = {"idx": idx, "start": int(msg["start"]), "samples": int(msg["samples"]),
                    "state": str(msg["state"]), "pcm": b"", "ready_at": now,
                    "compute_s": float(msg.get("compute_s", 0.0)),
                    "server_latency_s": self._latency(s, int(msg["start"]) + int(msg["samples"]), now)}
            s.parts.append(part)
            s.next_part = idx + 1
            return part
        return None

    @staticmethod
    def _latency(s: StreamSession, end_sample: int, now: float) -> Optional[float]:
        """Time from the server receiving the part's last sample to its isolated audio."""
        for end, t in s.marks:
            if end >= end_sample:
                return now - t
        return None

    def _finish(self, s: StreamSession, problem: Optional[str]) -> None:
        pcm = bytearray()
        for p in s.parts:
            pos = p["start"] * 2
            if len(pcm) < pos:
                pcm.extend(bytes(pos - len(pcm)))
            pcm[pos:pos + len(p["pcm"] or bytes(p["samples"] * 2))] = p["pcm"] or bytes(p["samples"] * 2)
        if pcm:
            path = s.directory / "isolated.wav"
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(sp.SAMPLE_RATE)
                out.writeframes(bytes(pcm))
            path.write_bytes(buffer.getvalue())
            s.wav_path = path
        if problem and s.error is None:
            s.error = {"code": "WORKER_LOST", "message": problem, "retryable": False}
        s.phase = "failed" if s.error else "done"
        with s.cond:
            s.cond.notify_all()
        timer = threading.Timer(600.0, self.cleanup, args=(s.live_id,))
        timer.daemon = True
        timer.start()
