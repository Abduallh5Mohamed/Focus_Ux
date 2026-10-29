"""Restart regressions: fresh app/repository instances, same on-disk SQLite."""
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from services.api.focus_api.routes import create_app
from services.worker.models import AudioStatus, JobStatus, TranscriptStatus

from .fakes import FakeCandidateProvider, FakeExtractionRunner, make_wav_bytes
from .harness import Harness, make_settings


@contextmanager
def open_api(settings, *, start_dispatcher=False, provider=None, runner=None):
    """Close the repository and discard the in-memory queue on every exit."""
    app = create_app(
        settings=settings,
        start_dispatcher=start_dispatcher,
        candidate_provider=provider if provider is not None else FakeCandidateProvider(),
        extraction_runner=runner if runner is not None else FakeExtractionRunner(),
    )
    with TestClient(app) as client:
        yield Harness(client=client, app=app, settings=settings)


def enqueue_job(api, data, request_id="restart"):
    response = api.create_job(
        data["video_id"], data["face_id"], request_id, data["token"]
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    assert api.get_job(job_id, data["token"]).json()["status"] == "queued"
    return job_id


def test_restart_requeues_persisted_faces_and_jobs_exactly_once(tmp_path):
    settings = make_settings(tmp_path)
    old_runner = FakeExtractionRunner()
    with open_api(settings, runner=old_runner) as before:
        data = before.setup_video()
        jobs = [enqueue_job(before, data, f"queued-{n}") for n in range(2)]
        pending_video, pending_token, _ = before.upload_ok()
        assert before.get_faces(pending_video, pending_token).json()["status"] == "pending"
        assert old_runner.calls == []
    assert settings.db_file.is_file()

    provider, runner = FakeCandidateProvider(), FakeExtractionRunner()
    with open_api(
        settings, start_dispatcher=True, provider=provider, runner=runner
    ) as after:
        assert after.app.state.dispatcher_started
        assert after.dispatcher.wait_idle()
        assert after.dispatcher.recovered == []
        assert [call["video_id"] for call in provider.calls] == [pending_video]
        assert [call["job_id"] for call in runner.calls] == jobs
        assert after.get_faces(pending_video, pending_token).json()["status"] == "ready"
        for job_id in jobs:
            assert after.get_job(job_id, data["token"]).json()["status"] == "completed"
            audio = after.get_audio(job_id, data["token"])
            assert audio.status_code == 200
            assert audio.content == make_wav_bytes()

    # A further restart must not replay terminal jobs or ready face detection.
    provider, runner = FakeCandidateProvider(), FakeExtractionRunner()
    with open_api(
        settings, start_dispatcher=True, provider=provider, runner=runner
    ) as again:
        assert again.dispatcher.wait_idle()
        assert provider.calls == []
        assert runner.calls == []
        assert again.dispatcher.recovered == []


@pytest.mark.parametrize("audio_ready", [False, True])
def test_restart_fails_interrupted_jobs_without_reexecuting(tmp_path, audio_ready):
    settings = make_settings(tmp_path)
    with open_api(settings) as before:
        data = before.setup_video()
        job_id = enqueue_job(before, data)
        # Persist the state left by a crashed worker, not an orderly cancellation.
        job = before.repo.get(job_id)
        job.status = JobStatus.PROCESSING
        job.audio_status = AudioStatus.READY if audio_ready else AudioStatus.PENDING
        job.transcript_status = TranscriptStatus.PROCESSING
        before.repo.save(job)

    runner = FakeExtractionRunner()
    with open_api(settings, start_dispatcher=True, runner=runner) as after:
        assert after.dispatcher.wait_idle()
        assert after.dispatcher.recovered == [job_id]
        job = after.get_job(job_id, data["token"]).json()
        assert job["status"] == "failed"
        assert job["error"]["code"] == "PROCESSING_FAILED"
        assert job["error"]["retryable"] is True
        assert job["audio_status"] == ("ready" if audio_ready else "failed")
        assert job["transcript_status"] == "failed"
        assert runner.calls == []

    with open_api(settings, start_dispatcher=True) as again:
        assert again.dispatcher.wait_idle()
        assert again.dispatcher.recovered == []
        assert again.get_job(job_id, data["token"]).json()["status"] == "failed"


def test_restart_cleans_tombstoned_upload_and_preserves_other_media(tmp_path):
    settings = make_settings(tmp_path)
    with open_api(settings) as before:
        data = before.setup_video()
        completed_job = enqueue_job(before, data, "completed")
        before.drain()
        original = Path(before.repo.get_video(data["video_id"]).original_path)
        thumbs = settings.thumbs_dir / data["video_id"]
        artifacts = settings.jobs_dir / completed_job
        assert original.is_file() and thumbs.is_dir() and artifacts.is_dir()
        survivor = before.setup_video()
        survivor_path = Path(before.repo.get_video(survivor["video_id"]).original_path)
        queued_job = enqueue_job(before, data, "cancel-on-delete")
        assert before.delete_video(data["video_id"], data["token"]).status_code == 202
        assert before.repo.get_video(data["video_id"]).deleted
        # The cleanup queue is intentionally lost on shutdown.
        assert original.exists() and artifacts.exists()

    provider, runner = FakeCandidateProvider(), FakeExtractionRunner()
    for _ in range(2):  # Startup cleanup remains safe after files have gone.
        with open_api(
            settings, start_dispatcher=True, provider=provider, runner=runner
        ) as after:
            assert after.dispatcher.wait_idle()
            assert not original.exists()
            assert not thumbs.exists()
            assert not artifacts.exists()
            assert not (settings.jobs_dir / queued_job).exists()
            video = after.repo.get_video(data["video_id"])
            assert video.deleted
            assert video.original_path is None and video.canonical_path is None
            assert all(
                face.thumbnail_path is None
                for face in after.repo.get_faces(data["video_id"])
            )
            assert after.repo.get(queued_job).status is JobStatus.CANCELLED
            for response in (
                after.get_original(data["video_id"], data["token"]),
                after.get_faces(data["video_id"], data["token"]),
                after.get_thumbnail(data["video_id"], data["face_id"], data["token"]),
                after.get_audio(completed_job, data["token"]),
                after.get_job(queued_job, data["token"]),
            ):
                assert response.status_code == 404
            assert survivor_path.is_file()
            assert after.get_original(survivor["video_id"], survivor["token"]).status_code == 200
            assert provider.calls == []
            assert runner.calls == []


def test_startup_cleanup_failure_releases_lock_and_can_be_retried(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    with open_api(settings) as before:
        video_id, token, _ = before.upload_ok()
        original = Path(before.repo.get_video(video_id).original_path)
        assert before.delete_video(video_id, token).status_code == 202

    with open_api(settings) as failed:
        with monkeypatch.context() as patch:
            patch.setattr(
                failed.app.state.storage, "remove_media",
                Mock(side_effect=OSError("temporary cleanup failure")),
            )
            with pytest.raises(OSError, match="temporary cleanup failure"):
                failed.dispatcher.start()
        assert not failed.dispatcher.lock_acquired
        assert not failed.dispatcher.lock.held
        assert original.exists()
        assert failed.repo.get_video(video_id).deleted

        # A separate dispatcher must be able to obtain the released lock.
        with open_api(settings, start_dispatcher=True) as retry:
            assert retry.app.state.dispatcher_started
            assert retry.dispatcher.wait_idle()
            assert not original.exists()
            assert retry.repo.get_video(video_id).original_path is None


class BlockingRunner(FakeExtractionRunner):
    """Hold a real worker in PROCESSING while a competing app starts."""

    def __init__(self):
        super().__init__()
        self.entered = Event()
        self.resume = Event()

    def extract(self, job, job_dir, on_progress):
        self.entered.set()
        if not self.resume.wait(timeout=10):
            raise TimeoutError("test did not release extraction")
        return super().extract(job, job_dir, on_progress)


def test_competing_dispatcher_cannot_recover_or_execute_live_work(tmp_path):
    settings = make_settings(tmp_path)
    runner = BlockingRunner()
    with open_api(settings, runner=runner) as owner:
        data = owner.setup_video()
        job_id = enqueue_job(owner, data)
        try:
            assert owner.dispatcher.start()
            assert runner.entered.wait(timeout=5)
            assert owner.repo.get(job_id).status is JobStatus.PROCESSING
            other_provider, other_runner = FakeCandidateProvider(), FakeExtractionRunner()
            with open_api(
                settings, provider=other_provider, runner=other_runner
            ) as contender:
                # A lock loser must never even attempt interrupted-job recovery.
                with pytest.MonkeyPatch.context() as patch:
                    recover = Mock(wraps=contender.app.state.worker.recover_interrupted)
                    patch.setattr(contender.app.state.worker, "recover_interrupted", recover)
                    assert contender.dispatcher.start() is False
                    recover.assert_not_called()
                assert not contender.dispatcher.lock_acquired
                assert contender.dispatcher.recovered == []
                assert contender.repo.get(job_id).status is JobStatus.PROCESSING
                assert other_runner.calls == [] and other_provider.calls == []
                runner.resume.set()
                assert owner.dispatcher.wait_idle()
                assert contender.get_job(job_id, data["token"]).json()["status"] == "completed"
                assert [call["job_id"] for call in runner.calls] == [job_id]
                # Handoff after shutdown must not execute the completed job again.
                owner.dispatcher.stop()
                assert contender.dispatcher.start()
                assert contender.dispatcher.wait_idle()
                assert contender.dispatcher.recovered == []
                assert other_runner.calls == [] and other_provider.calls == []
        finally:
            # Never let a failed assertion leave a worker running past repo.close().
            runner.resume.set()
            owner.dispatcher.stop()


@pytest.mark.parametrize("timeout", [0, 0.01])
def test_timed_out_stop_retains_ownership_until_worker_exits(tmp_path, timeout):
    settings = make_settings(tmp_path)
    runner = BlockingRunner()
    with open_api(settings, runner=runner) as owner:
        data = owner.setup_video()
        job_id = enqueue_job(owner, data, "active")
        queued_id = enqueue_job(owner, data, "waiting")
        try:
            assert owner.dispatcher.start()
            assert runner.entered.wait(timeout=5)
            thread = owner.dispatcher._thread
            other_runner = FakeExtractionRunner()
            with open_api(settings, runner=other_runner) as contender:
                recover = Mock(wraps=contender.app.state.worker.recover_interrupted)
                with pytest.MonkeyPatch.context() as patch:
                    patch.setattr(contender.app.state.worker, "recover_interrupted", recover)
                    # Repeated shutdown attempts must not lose the live thread
                    # or unlock it, even when a previous attempt timed out.
                    for _ in range(2):
                        with pytest.raises(TimeoutError, match="ownership retained"):
                            owner.dispatcher.stop(timeout=timeout)
                        assert owner.dispatcher._thread is thread
                        assert thread.is_alive()
                        assert owner.dispatcher.lock_acquired
                        assert owner.dispatcher.lock.held
                        assert contender.dispatcher.start() is False
                        recover.assert_not_called()
                        assert contender.repo.get(job_id).status is JobStatus.PROCESSING
                        assert other_runner.calls == []

                    runner.resume.set()
                    thread.join(timeout=5)
                    assert not thread.is_alive()
                    assert owner.repo.get(job_id).status is JobStatus.COMPLETED
                    assert owner.repo.get(queued_id).status is JobStatus.QUEUED
                    assert [call["job_id"] for call in runner.calls] == [job_id]
                    # Ownership is retained until a successful stop retry,
                    # not merely until the extraction callback returns.
                    assert contender.dispatcher.start() is False
                    recover.assert_not_called()
                    owner.dispatcher.stop()
                    owner.dispatcher.stop()  # Successful shutdown is idempotent.
                    assert owner.dispatcher._thread is None
                    assert not owner.dispatcher.lock_acquired
                    assert not owner.dispatcher.lock.held
                    assert contender.dispatcher.start()
                    assert contender.dispatcher.wait_idle()
                    recover.assert_called_once()
                    assert contender.dispatcher.recovered == []
                    assert [call["job_id"] for call in other_runner.calls] == [queued_id]
        finally:
            runner.resume.set()
            owner.dispatcher.stop()


def test_lifespan_timeout_keeps_live_worker_repository_open(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    runner = BlockingRunner()
    app = create_app(
        settings=settings,
        start_dispatcher=False,
        candidate_provider=FakeCandidateProvider(),
        extraction_runner=runner,
    )
    stop = app.state.dispatcher.stop
    close = Mock(wraps=app.state.repo.close)
    monkeypatch.setattr(app.state.repo, "close", close)
    # Exercise the real lifespan shutdown without waiting its default 5 seconds.
    monkeypatch.setattr(app.state.dispatcher, "stop", lambda: stop(timeout=0))
    try:
        with open_api(settings) as contender:
            with pytest.raises(TimeoutError, match="ownership retained"):
                with TestClient(app) as client:
                    owner = Harness(client=client, app=app, settings=settings)
                    data = owner.setup_video()
                    job_id = enqueue_job(owner, data)
                    assert owner.dispatcher.start()
                    assert runner.entered.wait(timeout=5)
            close.assert_not_called()
            assert app.state.dispatcher.lock.held
            assert contender.dispatcher.start() is False
            assert contender.repo.get(job_id).status is JobStatus.PROCESSING
            runner.resume.set()
            stop()
            # The worker must still be able to persist its result after the
            # failed app shutdown; closing the repo earlier would lose it.
            assert app.state.repo.get(job_id).status is JobStatus.COMPLETED
            assert [call["job_id"] for call in runner.calls] == [job_id]
            assert contender.dispatcher.start()
            assert contender.dispatcher.wait_idle()
            assert contender.dispatcher.recovered == []
    finally:
        runner.resume.set()
        stop()
        app.state.repo.close()
