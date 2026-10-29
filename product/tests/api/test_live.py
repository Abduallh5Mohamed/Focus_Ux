"""Live sessions with a REAL decoder: MediaRecorder-style byte slices cut mid-cluster."""
from __future__ import annotations

import subprocess

import pytest

from services.api.focus_api import live_decode
from services.api.focus_api.live import match_anchor
from services.api.focus_api.live_metrics import evaluate_gate, summarize

from .fakes import FakeTranscriber

H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731


@pytest.fixture(scope="module")
def stream(tmp_path_factory):
    out = tmp_path_factory.mktemp("live") / "s.webm"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
         "-t", "8", "-c:v", "libvpx", "-g", "25", "-c:a", "libopus",
         "-f", "webm", "-cluster_time_limit", "1000", str(out)], check=True)
    data = out.read_bytes()
    marks = live_decode.find_clusters(data)
    assert len(marks) >= 8
    cuts = [0] + [marks[i] + 50 for i in range(2, 8, 2)] + [len(data)]
    return [data[a:b] for a, b in zip(cuts, cuts[1:])]


@pytest.fixture
def make_api(make_api, tmp_path):
    """Live mode is an explicit opt-in, so these tests switch it on."""
    from .harness import make_settings
    count = {"n": 0}

    def factory(**kw):
        if "settings" not in kw:
            count["n"] += 1
            kw["settings"] = make_settings(tmp_path / f"live{count['n']}", live_enabled=True)
        return make_api(**kw)
    return factory


def start(api, stream, n=None):
    r = api.client.post("/live/sessions")
    assert r.status_code == 201, r.text
    body = r.json()
    return body["live_session_id"], body["session_token"]


def put(api, sid, tok, seq, data, dur=2000):
    return api.client.put(
        f"/live/sessions/{sid}/chunks/{seq}?capture_start_ms={seq * 2000}&duration_ms={dur}",
        content=data, headers=H(tok))


def test_chunk_alone_is_undecodable_but_stream_decodes(make_api, stream):
    api = make_api()
    sid, tok = start(api, stream)
    assert put(api, sid, tok, 0, stream[0]).json()["state"] == "received"
    api.drain()
    # second chunk starts mid-cluster: only decodable with header + tail
    assert put(api, sid, tok, 1, stream[1]).json()["state"] == "awaiting_target"
    with pytest.raises(live_decode.DecodeError):
        live_decode.decode_window(stream[1], api.settings.storage_root / "x.mp4", start_s=0, duration_s=2)


def test_interrupted_empty_startup_releases_slot_without_stopping_replacement(make_api):
    api = make_api()
    created = api.client.post("/live/sessions").json()
    sid, token = created["live_session_id"], created["session_token"]
    path = f"/live/sessions/{sid}/stop"
    assert api.client.post(path, headers=H(token)).status_code == 200
    api.drain()
    abandoned = api.client.get(f"/live/sessions/{sid}", headers=H(token)).json()
    assert abandoned["phase"] == "failed"
    assert abandoned["final"]["error"]["code"] == "NO_AUDIO"
    replacement = api.client.post("/live/sessions")
    assert replacement.status_code == 201
    body = replacement.json()
    # Repeated cleanup is idempotent and remains scoped to the abandoned owner/id.
    assert api.client.post(path, headers=H(token)).status_code == 200
    assert api.client.post(path, headers=H(body["session_token"])).status_code == 404
    api.drain()
    current = api.client.get(f'/live/sessions/{body["live_session_id"]}',
                             headers=H(body["session_token"])).json()
    assert current["phase"] == "awaiting_chunk"


def test_full_session_flow_and_final_transcript(make_api, stream):
    api = make_api(transcriber=FakeTranscriber())
    api.settings.live_max_queue_depth = 10
    sid, tok = start(api, stream)
    put(api, sid, tok, 0, stream[0])
    api.drain()
    view = api.client.get(f"/live/sessions/{sid}", headers=H(tok)).json()
    assert view["phase"] == "awaiting_target" and view["faces_status"] == "ready"
    faces = api.get_faces(view["first_video_id"], tok).json()["faces"]
    assert api.client.post(f"/live/sessions/{sid}/target", json={"face_id": faces[1]["face_id"]},
                           headers=H(tok)).status_code == 200
    # a second session is refused: one worker, one live user
    assert api.client.post("/live/sessions", headers=H(tok)).status_code == 409
    for seq in (1, 2, 3):
        assert put(api, sid, tok, seq, stream[seq]).json()["state"] == "queued"
    dup = put(api, sid, tok, 3, stream[3]).json()
    assert dup["duplicate"] is True
    assert put(api, sid, tok, 3, b"other").status_code == 409
    api.drain()
    view = api.client.get(f"/live/sessions/{sid}", headers=H(tok)).json()
    assert [c["state"] for c in view["chunks"]] == ["ready"] * 4, view["chunks"]
    audio = api.client.get(f"/live/sessions/{sid}/chunks/2/audio", headers=H(tok))
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"
    # target cannot change inside a session
    assert api.client.post(f"/live/sessions/{sid}/target", json={"face_id": faces[0]["face_id"]},
                           headers=H(tok)).status_code == 409
    api.client.post(f"/live/sessions/{sid}/stop", headers=H(tok))
    api.drain()
    view = api.client.get(f"/live/sessions/{sid}", headers=H(tok)).json()
    assert view["final"]["status"] == "ready", view["final"]
    job = api.get_job(view["final"]["job_id"], tok).json()
    assert job["audio_status"] == "ready" and job["transcript_status"] == "ready"
    assert api.get_original(view["final"]["video_id"], tok).status_code == 200
    # per-chunk jobs were never transcribed
    transcriber_calls = api.app.state.worker.transcriber.calls
    assert len(transcriber_calls) == 1
    m = api.client.get(f"/live/sessions/{sid}/metrics", headers=H(tok)).json()
    assert m["gate"]["decision"] == "internal_only"
    # a new session is allowed after stop
    assert api.client.post("/live/sessions", headers=H(tok)).status_code == 201


def test_missing_chunk_is_explicit(make_api, stream):
    api = make_api()
    sid, tok = start(api, stream)
    put(api, sid, tok, 0, stream[0])
    api.drain()
    view = api.client.get(f"/live/sessions/{sid}", headers=H(tok)).json()
    faces = api.get_faces(view["first_video_id"], tok).json()["faces"]
    api.client.post(f"/live/sessions/{sid}/target", json={"face_id": faces[0]["face_id"]}, headers=H(tok))
    put(api, sid, tok, 2, stream[2])  # chunk 1 never arrives
    assert put(api, sid, tok, 1, stream[1]).status_code == 409
    api.drain()
    states = {c["seq"]: c["state"] for c in
              api.client.get(f"/live/sessions/{sid}", headers=H(tok)).json()["chunks"]}
    assert states[1] == "missing" and states[2] in ("ready", "undecodable")


def test_overload_defers_instead_of_dropping(make_api, stream):
    from .harness import make_settings
    from pathlib import Path
    api = make_api()
    api.settings.live_max_queue_depth = 1
    sid, tok = start(api, stream)
    put(api, sid, tok, 0, stream[0])
    api.drain()
    view = api.client.get(f"/live/sessions/{sid}", headers=H(tok)).json()
    faces = api.get_faces(view["first_video_id"], tok).json()["faces"]
    api.client.post(f"/live/sessions/{sid}/target", json={"face_id": faces[0]["face_id"]}, headers=H(tok))
    api.drain()
    put(api, sid, tok, 1, stream[1])
    put(api, sid, tok, 2, stream[2])
    view = api.client.get(f"/live/sessions/{sid}", headers=H(tok)).json()
    assert view["mode"] == "record_then_process" and view["overload_at_seq"] == 2
    assert view["chunks"][2]["state"] == "deferred"
    api.client.post(f"/live/sessions/{sid}/stop", headers=H(tok))
    api.drain()
    view = api.client.get(f"/live/sessions/{sid}", headers=H(tok)).json()
    assert [c["state"] for c in view["chunks"]] == ["ready"] * 3


def test_other_session_cannot_touch_live(make_api, stream):
    api = make_api()
    sid, tok = start(api, stream)
    _v, other, _ = api.upload_ok()
    assert api.client.get(f"/live/sessions/{sid}", headers=H(other)).status_code == 404


def test_anchor_matching():
    class F:
        def __init__(self, b): self.bbox = b
    assert match_anchor((0, 0, 10, 10), [F((100, 100, 10, 10))])[1] == "target_lost"
    assert match_anchor((0, 0, 10, 10), [])[1] == "target_lost"
    assert match_anchor((0, 0, 10, 10), [F((1, 0, 10, 10)), F((0, 1, 10, 10))])[1] == "uncertain"
    face, state = match_anchor((0, 0, 10, 10), [F((0, 0, 10, 10)), F((50, 50, 10, 10))])
    assert state == "ok" and face.bbox == (0, 0, 10, 10)


def test_gate_never_passes_without_measurements():
    s = summarize(chunks=[], depth_samples=[], duplicates_ingested=0, playback=None, overload_seq=None)
    g = evaluate_gate(s)
    assert g["decision"] == "internal_only" and "capture-to-play not measured in a browser" in g["reasons"]


def test_gate_passes_only_with_all_numbers():
    chunks = [{"seq": i, "state": "ready", "duration_ms": 2000, "processing_s": 1.0,
               "server_latency_s": 1.0} for i in range(31)]
    pb = {"chunks": [{"seq": i, "capture_wall_ms": i * 2000, "audible_wall_ms": i * 2000 + 2800}
                     for i in range(31)]}
    s = summarize(chunks=chunks, depth_samples=[0, 1], duplicates_ingested=0, playback=pb, overload_seq=None)
    assert evaluate_gate(s, quality_checked=True)["decision"] == "enable_experimental"
    assert evaluate_gate(s)["decision"] == "internal_only"
    for i in range(5, 10):
        pb["chunks"][i]["audible_wall_ms"] = i * 2000 + 4000
    s = summarize(chunks=chunks, depth_samples=[0], duplicates_ingested=0, playback=pb, overload_seq=None)
    assert evaluate_gate(s, quality_checked=True)["decision"] == "internal_only"


def test_live_is_off_by_default(make_api, tmp_path):
    from .harness import make_settings
    api = make_api(settings=make_settings(tmp_path / "off"))
    assert api.client.post("/live/sessions").status_code == 403


def test_recover_keeps_final_media_and_only_cleans_orphan_chunks(make_api):
    api = make_api()
    live = api.app.state.live
    root = live.root / "dead"
    root.mkdir(parents=True)
    (root / "manifest.txt").write_text("chunk:aaa\nfull:bbb\n")
    seen = []
    live.repo.get_video = lambda vid: object()
    live.repo.mark_video_deleted = lambda vid: seen.append(vid)
    live.dispatcher.enqueue_cleanup = lambda vid: None
    live.recover()
    assert seen == ["aaa"] and not root.exists()
