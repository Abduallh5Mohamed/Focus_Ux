"""Browser -> server -> worker -> server -> browser relay with a fake engine (protocol only)."""
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "ml"))

from services.api.focus_api.config import Settings  # noqa: E402
from services.api.focus_api.routes import create_app  # noqa: E402
from services.worker import stream_proto as sp  # noqa: E402
from tools.stream_worker import run_stream  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml"))
from fake_stream_backend import FakeBackend, pcm  # noqa: E402

KEY = "synthetic-test-key-" * 3
WORKER = {"Authorization": "Bearer " + KEY}
SR = 16000


class Direct:
    """Worker client that talks to the app in-process."""

    def __init__(self, client):
        self.c = client

    def stream_poll(self, live_id):
        r = self.c.post(f"/worker/stream/{live_id}/poll", headers=WORKER)
        return r.content if r.status_code == 200 else None

    def stream_out(self, live_id, body):
        assert self.c.post(f"/worker/stream/{live_id}/out", content=body, headers=WORKER).status_code == 200


@pytest.fixture
def app_client(tmp_path):
    app = create_app(settings=Settings(
        storage_root=tmp_path, inference_mode="remote", worker_token=KEY,
        live_enabled=True, live_stream_enabled=True), start_dispatcher=False)
    with TestClient(app) as client:
        yield app, client


def test_full_relay_in_order_and_gate_blocks_without_measurements(app_client):
    app, c = app_client
    assert c.post("/worker/poll", headers=WORKER).status_code == 204  # worker online
    created = c.post("/live/stream/sessions")
    assert created.status_code == 201
    live_id, auth = created.json()["live_session_id"], {"Authorization": "Bearer " + created.json()["session_token"]}
    task = c.post("/worker/poll", headers=WORKER).json()
    assert task["kind"] == "stream" and task["task_id"] == live_id and task["config"]["hop_s"] == 0.5

    backend = FakeBackend()
    backend.detect = lambda jpeg: [{"bbox": [10, 10, 50, 50], "frame_size": [640, 360], "thumbnail": "AAAA"}]
    box = {}
    thread = threading.Thread(target=lambda: run_stream(Direct(c), live_id, backend, task["config"]), daemon=True)
    thread.start()

    # a first frame arrives; the picker needs candidates
    c.post(f"/live/stream/sessions/{live_id}/in", content=sp.pack_batch(0, [(sp.K_FRAME, 0, b"j")]), headers=auth)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        view = c.get(f"/live/stream/sessions/{live_id}", headers=auth).json()
        if view["faces"]:
            break
        time.sleep(0.05)
    assert view["phase"] == "awaiting_target" and view["faces"][0]["thumbnail_url"].startswith("data:image/jpeg")
    assert c.post(f"/live/stream/sessions/{live_id}/target", json={"bbox": [1, 1, 1, 1]}, headers=auth).status_code == 404
    assert c.post(f"/live/stream/sessions/{live_id}/target", json={"bbox": [10, 10, 50, 50]}, headers=auth).status_code == 200

    seq, sig = 1, []
    for i in range(30):  # 6 s, 200 ms per batch
        t = np.arange(i * 3200, (i + 1) * 3200)
        samples = 0.3 * np.sin(2 * np.pi * 200 * t / SR)
        sig.append(samples)
        recs = [(sp.K_AUDIO, int(t[0]), pcm(samples))] + [
            (sp.K_FRAME, int(i * 200 + f * 40), b"j") for f in range(1, 6)]
        body = sp.pack_batch(seq, recs)
        assert c.post(f"/live/stream/sessions/{live_id}/in", content=body, headers=auth).status_code == 200
        assert c.post(f"/live/stream/sessions/{live_id}/in", content=body, headers=auth).json()["duplicate"]
        seq += 1
        time.sleep(0.02)
    assert c.post(f"/live/stream/sessions/{live_id}/stop", headers=auth).status_code == 200

    got, after = [], -1
    deadline = time.monotonic() + 10
    phase = None
    while time.monotonic() < deadline and phase != "done":
        r = c.get(f"/live/stream/sessions/{live_id}/out?after={after}&wait_ms=300", headers=auth)
        if r.status_code != 200:
            continue
        _s, records = sp.unpack_batch(r.content)
        meta = None
        for kind, pos, data in records:
            if kind == sp.K_JSON:
                import json
                m = json.loads(data)
                if "idx" in m:
                    meta = m
                    got.append(m)
                    after = max(after, m["idx"])
                else:
                    phase = m["phase"]
    thread.join(5)
    assert [p["idx"] for p in got] == list(range(len(got)))
    assert all(a["start"] + a["samples"] == b["start"] for a, b in zip(got, got[1:]))
    assert sum(p["samples"] for p in got) == 30 * 3200
    view = c.get(f"/live/stream/sessions/{live_id}", headers=auth).json()
    assert view["phase"] == "done" and view["counts"]["parts_missing"] == 0
    assert c.get(f"/live/stream/sessions/{live_id}/audio", headers=auth).status_code == 200
    m = c.get(f"/live/stream/sessions/{live_id}/metrics", headers=auth).json()
    assert m["summary"]["rtf"] is not None
    assert m["gate"]["decision"] == "internal_only"  # no browser playback/quality numbers yet
    assert any("capture-to-play" in r for r in m["gate"]["reasons"])


def test_disabled_by_default_and_busy_rules(tmp_path):
    app = create_app(settings=Settings(storage_root=tmp_path, inference_mode="remote", worker_token=KEY,
                                       live_enabled=True), start_dispatcher=False)
    with TestClient(app) as c:
        assert c.get("/live/status").json()["stream_enabled"] is False
        assert c.post("/live/stream/sessions").status_code == 403


def test_gate_thresholds():
    from services.api.focus_api.live_metrics import evaluate_stream_gate, summarize_stream
    parts = [{"idx": i, "samples": 8000, "state": "ready", "server_latency_s": 0.4} for i in range(130)]
    playback = {"chunks": [{"seq": i, "capture_wall_ms": 0, "audible_wall_ms": 1200} for i in range(130)],
                "underruns": 0, "rebuffers": 0}
    ok = summarize_stream(parts=parts, worker_stats={"rtf": 0.4}, playback=playback,
                          input_counts={}, audio_in_s=65)
    assert evaluate_stream_gate(ok, quality_delta_db=1.5)["decision"] == "enable_experimental"
    assert "SI-SDRi" in " ".join(evaluate_stream_gate(ok, quality_delta_db=2.5)["reasons"])
    slow = summarize_stream(parts=parts, worker_stats={"rtf": 0.6}, playback=playback,
                            input_counts={"frames_dropped": 1}, audio_in_s=65)
    assert len(evaluate_stream_gate(slow, quality_delta_db=1.0)["reasons"]) == 2


def test_gate_tool_helpers():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    from stream_gate import parts_from, si_sdr
    ref = np.sin(np.arange(16000) / 7.0)
    assert si_sdr(ref * 0.5, ref) > 60
    assert si_sdr(ref + np.random.default_rng(0).normal(0, 0.5, ref.size), ref) < 10
    body = sp.pack_batch(0, [sp.json_record({"idx": 0, "start": 0, "samples": 2, "state": "ready"}),
                             (sp.K_OUT_AUDIO, 0, b"\x01\x00\x02\x00")])
    assert parts_from(body)[0]["pcm"] == b"\x01\x00\x02\x00"


def test_abandoned_session_releases_the_worker(app_client):
    app, c = app_client
    c.post("/worker/poll", headers=WORKER)
    created = c.post("/live/stream/sessions").json()
    live_id = created["live_session_id"]
    task = c.post("/worker/poll", headers=WORKER).json()
    assert task["task_id"] == live_id
    hub = app.state.live_stream
    hub.sessions[live_id].last_seen -= hub.settings.live_idle_timeout_s + 5  # browser vanished
    r = c.post(f"/worker/stream/{live_id}/poll", headers=WORKER)
    _s, records = sp.unpack_batch(r.content)
    assert {"op": "close"} in list(sp.iter_json(records))
    c.post(f"/worker/stream/{live_id}/out", headers=WORKER, content=sp.pack_batch(
        0, [sp.json_record({"event": "closed", "stats": {"rtf": 0.1}})]))
    assert hub.sessions[live_id].phase == "done"
    assert hub.active() is None  # uploads/other sessions can use the worker again
