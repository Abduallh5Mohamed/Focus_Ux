"""Owner-loop recovery without browser requests; all inference here is fake."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from services.api.focus_api.live import Chunk

from .harness import make_settings


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "background recovery did not finish"


def live_api(make_api, tmp_path, **kwargs):
    return make_api(
        settings=make_settings(tmp_path / "live", live_enabled=True, live_idle_timeout_s=3600),
        start_dispatcher=True, **kwargs,
    )


def abandon(s):
    with s.lock:
        s.last_seen = time.monotonic() - 7200


@pytest.mark.parametrize("phase", ["awaiting_chunk", "awaiting_target", "live"])
def test_empty_hard_close_expires_without_another_request(make_api, tmp_path, phase):
    api = live_api(make_api, tmp_path)
    live = api.app.state.live
    body = api.client.post("/live/sessions").json()
    s = live.sessions[body["live_session_id"]]
    with s.lock:
        s.phase = phase
    abandon(s)
    # No HTTP, create, drain, or manual maintenance triggers recovery.
    wait_for(lambda: s.phase == "failed")
    assert s.final_error["code"] == "NO_AUDIO"
    wait_for(lambda: s.cleanup_at is not None)
    assert s.cleanup_at > time.monotonic() + 58
    assert live._active() is None
    assert api.dispatcher.lock_acquired and api.dispatcher.lock.held
    replacement = api.client.post("/live/sessions")
    assert replacement.status_code == 201
    current = live.sessions[replacement.json()["live_session_id"]]
    # Old cleanup and a delayed browser stop cannot affect the new owner/id.
    with s.lock:
        s.cleanup_at = 0
    wait_for(lambda: not s.directory.exists())
    assert api.client.post(
        f"/live/sessions/{s.live_id}/stop",
        headers={"Authorization": f'Bearer {body["session_token"]}'},
    ).status_code == 200
    assert current.phase == "awaiting_chunk" and current.directory.is_dir()


def test_failed_idle_stop_is_logged_and_retried(make_api, tmp_path, monkeypatch, caplog):
    api = live_api(make_api, tmp_path)
    live = api.app.state.live
    s = live.create("abandoned")
    enqueue = api.dispatcher.enqueue_live
    attempted = threading.Event()
    attempts = []

    def fail_once(ident):
        attempts.append(ident)
        if len(attempts) == 1:
            attempted.set()
            raise OSError("queue unavailable")
        enqueue(ident)

    monkeypatch.setattr(api.dispatcher, "enqueue_live", fail_once)
    abandon(s)
    assert attempted.wait(5)
    wait_for(lambda: s.phase == "failed")
    assert len(attempts) == 2
    assert s.final_error["code"] == "NO_AUDIO"
    assert "idle stop failed" in caplog.text
    assert api.dispatcher.lock.held


@pytest.mark.parametrize("failure", ["repository", "enqueue", "directory"])
def test_cleanup_retries_and_preserves_final_and_replacement(
    make_api, tmp_path, monkeypatch, caplog, failure,
):
    api = live_api(make_api, tmp_path)
    live = api.app.state.live
    chunk_id, _token, _ = api.upload_ok()
    full_id, _token, _ = api.upload_ok()
    assert api.dispatcher.wait_idle()
    full_path = Path(api.repo.get_video(full_id).original_path)
    s = live.create("old-owner")
    with s.lock:
        s.chunks[0] = Chunk(0, 0, 2000, state="awaiting_target", video_id=chunk_id)
        s.full_video_id = full_id
        s.phase = "done"
    replacement = live.create("new-owner")
    failed = threading.Event()
    attempts = []

    if failure == "repository":
        target, name = api.repo, "mark_video_deleted"
    elif failure == "enqueue":
        target, name = api.dispatcher, "enqueue_cleanup"
    else:
        from services.api.focus_api import live as live_module
        target, name = live_module.shutil, "rmtree"
    original = getattr(target, name)

    def fail_once(*args, **kwargs):
        attempts.append(args)
        if len(attempts) == 1:
            failed.set()
            raise OSError("cleanup unavailable")
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, fail_once)
    with s.lock:
        s.cleanup_at = 0
    assert failed.wait(5)
    wait_for(lambda: s.cleanup_at is None)
    wait_for(lambda: api.repo.get_video(chunk_id).original_path is None)
    assert len(attempts) >= 2 and "live cleanup failed" in caplog.text
    assert not s.directory.exists()
    assert api.repo.get_video(chunk_id).deleted
    assert not api.repo.get_video(full_id).deleted and full_path.is_file()
    assert replacement.phase == "awaiting_chunk" and replacement.directory.is_dir()
    assert api.dispatcher.lock.held


def test_non_owner_does_not_recover_or_clean_live_sessions(make_api, tmp_path):
    settings = make_settings(tmp_path / "shared", live_enabled=True, live_idle_timeout_s=3600)
    owner = make_api(settings=settings, start_dispatcher=True)
    other = make_api(settings=settings, start_dispatcher=True)
    assert owner.dispatcher.lock.held and not other.dispatcher.lock_acquired
    live = other.app.state.live
    finished = live.create("finished-owner")
    with finished.lock:
        finished.phase = "done"
        finished.cleanup_at = 0
    stale = live.create("non-owner")
    abandon(stale)
    live.maintain()
    time.sleep(0.3)
    assert stale.phase == "awaiting_chunk"
    assert finished.directory.exists()
    assert owner.dispatcher.lock.held


@pytest.mark.parametrize("shutdown", [False, True])
def test_recovery_waits_for_inflight_work_and_shutdown_retains_ownership(
    make_api, tmp_path, monkeypatch, shutdown,
):
    api = live_api(make_api, tmp_path)
    live = api.app.state.live
    s = live.create("abandoned")
    entered, resume = threading.Event(), threading.Event()

    def blocking_chunk(session, chunk):
        entered.set()
        assert resume.wait(5)
        chunk.state = "failed"

    monkeypatch.setattr(live, "_process_chunk", blocking_chunk)
    s.chunks[0] = Chunk(0, 0, 2000, state="received")
    api.dispatcher.enqueue_live(f"chunk:{s.live_id}:0:1")
    try:
        assert entered.wait(5)
        abandon(s)
        if shutdown:
            with pytest.raises(TimeoutError):
                api.dispatcher.stop(timeout=0.01)
        else:
            time.sleep(0.3)  # spans an idle-loop wait while inference is blocked
        assert api.dispatcher.lock.held and api.dispatcher.lock_acquired
        assert s.phase == "awaiting_chunk" and s.directory.exists()
    finally:
        resume.set()
    if not shutdown:
        wait_for(lambda: s.phase == "failed")
        assert s.final_error["code"] == "NO_AUDIO"
        assert api.dispatcher.lock.held
        return
    wait_for(lambda: not api.dispatcher._thread.is_alive())
    # A timed-out shutdown never runs maintenance or releases ownership.
    assert s.phase == "awaiting_chunk"
    api.dispatcher.stop()
    assert not api.dispatcher.lock_acquired
    live.maintain()
    assert s.directory.exists()
