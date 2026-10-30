"""Worker-side loop for the continuous live path. No model imports here: the
backend (``DolphinStreamBackend`` or a test fake) is injected, the client only needs
``stream_poll(id) -> bytes | None`` and ``stream_out(id, bytes)``."""
from __future__ import annotations

import queue
import threading
import time

from services.worker import stream_proto as sp

DETECT_EVERY_S = 1.5
SELECT_IOU_MIN = 0.3


def _iou(a, b) -> float:
    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


class _Sender(threading.Thread):
    """Posting results must never block the next window from starting."""

    def __init__(self, client, live_id):
        super().__init__(daemon=True)
        self.client, self.live_id, self.q, self.failure = client, live_id, queue.Queue(), None

    def run(self):
        while True:
            records = self.q.get()
            if records is None:
                return
            while not self.q.empty() and len(records) < 200:
                nxt = self.q.get()
                if nxt is None:
                    self.q.put(None)
                    break
                records += nxt
            try:
                self.client.stream_out(self.live_id, sp.pack_batch(0, records))
            except Exception as exc:  # reported by the loop, never swallowed
                self.failure = exc
                return


def run_stream(client, live_id, backend, config, *, accel=None, log=print):
    from focus_ml.live_stream import LiveStreamSession, StreamConfig

    session = LiveStreamSession(backend, StreamConfig(**config))
    sender = _Sender(client, live_id)
    sender.start()
    state = {"part": 0, "last": None, "detected": 0.0}

    def send(records):
        sender.q.put(records)

    def emit(parts):
        for p in parts:
            records = [sp.json_record({"part": state["part"], "start": p.start_sample, "samples": p.samples,
                                       "state": p.state, "compute_s": round(p.compute_s, 4)})]
            if p.pcm:
                records.append((sp.K_OUT_AUDIO, p.start_sample, p.pcm))
            state["part"] += 1
            send(records)

    def stats():
        d = session.stats.as_dict()
        d["accel"] = accel or {}
        return d

    def select(bbox):
        last = state["last"]
        match = None
        if last is not None:
            ranked = sorted(((_iou(bbox, f["bbox"]), f["bbox"]) for f in session.detect(last[1])),
                            key=lambda t: -t[0])
            if ranked and ranked[0][0] >= SELECT_IOU_MIN:
                match = ranked[0][1]
        if match is None:
            send([sp.json_record({"event": "select_failed"})])
            return
        session.select(int(round(last[0] * sp.FPS / 1000)), last[1], match)
        send([sp.json_record({"event": "selected"})])

    try:
        while True:
            if sender.failure:
                raise sender.failure
            body = client.stream_poll(live_id)
            if body is None:
                continue
            _seq, records = sp.unpack_batch(body)
            closing = ending = False
            for kind, pos, data in records:
                if kind == sp.K_AUDIO:
                    session.push_audio(pos, data)
                elif kind == sp.K_FRAME:
                    state["last"] = (pos, data)
                    if session.selected:
                        session.push_frame(pos, data)
                    elif time.monotonic() - state["detected"] > DETECT_EVERY_S:
                        state["detected"] = time.monotonic()
                        send([sp.json_record({"faces": session.detect(data)})])
            for ctl in sp.iter_json(records):
                op = ctl.get("op")
                if op == "select" and not session.selected:
                    select([int(v) for v in ctl["bbox"]])
                elif op == "close":
                    closing = True
                elif op == "end":
                    ending = True
            emit(session.step())
            if closing:
                emit(session.flush())
                send([sp.json_record({"event": "closed", "stats": stats()})])
                return
            if ending:
                return
    except Exception as exc:
        log("Live stream failed: " + type(exc).__name__)
        send([sp.json_record({"event": "error"})])
        raise
    finally:
        sender.q.put(None)
        sender.join(timeout=10)
