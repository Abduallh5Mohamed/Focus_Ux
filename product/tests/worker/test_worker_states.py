"""Worker engine tests: stages, transitions, audio/transcript independence, cancellation."""
from __future__ import annotations

import pytest

from services.worker import (
    AudioStatus,
    Job,
    JobDirectoryLayout,
    JobStatus,
    JobStage,
    SingleWorker,
    TargetRunResult,
    TranscriptStatus,
)
from services.worker.errors import (
    FaceNotFoundError,
    LimitExceededError,
    MediaError,
    ProcessingError,
    TargetLostError,
)
from services.worker.errors import TranscriptUnavailableError
from services.worker.models import TranscriptSegment

from fakes import (
    FakeTargeting,
    FakeTranscriber,
    InMemoryRepository,
    make_job,
)


def build(tmp_path, jobs=None, targeting=None, transcriber=None, is_cancelled=None):
    repo = InMemoryRepository(jobs)
    targeting = targeting or FakeTargeting()
    layout = JobDirectoryLayout(str(tmp_path / "runtime"))
    recorder = []
    worker = SingleWorker(
        repo=repo,
        targeting=targeting,
        layout=layout,
        transcriber=transcriber,
        on_stage=recorder.append,
        is_cancelled=is_cancelled,
    )
    return worker, repo, targeting, recorder


def queued_job(video_file: str) -> Job:
    return make_job(video_path=str(video_file))


def write_media(tmp_path, name="clip.mp4", size=64) -> str:
    p = tmp_path / name
    p.write_bytes(b"\x00" * size)
    return str(p)


def test_happy_path_transcript_ready(tmp_path):
    media = write_media(tmp_path)
    worker, repo, targeting, recorder = build(tmp_path, [queued_job(media)], transcriber=FakeTranscriber())
    out = worker.process("job-1")
    assert out.status is JobStatus.COMPLETED
    assert out.stage is JobStage.READY
    assert out.audio_status is AudioStatus.READY
    assert out.transcript_status is TranscriptStatus.READY
    assert [s.text for s in out.transcript_segments] == ["mar7aba", "salam"]
    assert [s.id for s in out.transcript_segments] == [3, 1]
    out = worker.process("job-1")
    stages = list(dict.fromkeys(stage.stage.value for stage in recorder))
    assert stages == [
        "validating",
        "preparing",
        "tracking",
        "separating",
        "transcribing",
        "ready",
    ]
    assert targeting.calls[0]["video_path"] == media
    assert targeting.calls[0]["face_id"] == "face-9"
    assert ("completed", "ready") in repo.save_history
    assert out.snapshot()["selected_face_id"] == "face-9"


def test_transcriber_missing_audio_still_completes(tmp_path):
    media = write_media(tmp_path)
    worker, repo, targeting, _ = build(tmp_path, [queued_job(media)], transcriber=None)
    out = worker.process("job-1")
    assert out.status is JobStatus.COMPLETED
    assert out.audio_status is AudioStatus.READY
    assert out.transcript_status is TranscriptStatus.FAILED
    assert out.error is None
    assert any(w.startswith("transcript failed:") for w in out.audio_warnings)


def test_transcript_failure_independent_of_audio(tmp_path):
    media = write_media(tmp_path)
    transcriber = FakeTranscriber(raise_with=ProcessingError("asr model crashed", retryable=True))
    worker, repo, _, _recorder = build(tmp_path, [queued_job(media)], transcriber=transcriber)
    out = worker.process("job-1")
    assert out.status is JobStatus.COMPLETED
    assert out.audio_status is AudioStatus.READY
    assert out.transcript_status is TranscriptStatus.FAILED
    assert out.error is None
    assert transcriber.wav_paths == [out.wav_path]


def test_processing_state_persisted_between_stages(tmp_path):
    media = write_media(tmp_path)
    worker, repo, _, recorder = build(tmp_path, [queued_job(media)], transcriber=FakeTranscriber())
    worker.process("job-1")
    assert repo.save_history == [
        ("processing", "validating"),
        ("processing", "preparing"),
        ("processing", "tracking"),
        ("processing", "separating"),
        ("processing", "transcribing"),
        ("completed", "ready"),
    ]


def test_adapter_progress_shifts_stage_within_template(tmp_path):
    media = write_media(tmp_path)
    targeting = FakeTargeting(emit_stages=("tracking", "separating"))
    worker, repo, _, recorder = build(
        tmp_path, [queued_job(media)], targeting=targeting, transcriber=FakeTranscriber()
    )
    worker.process("job-1")
    values = [s.stage.value for s in recorder]
    assert values == [
        "validating",
        "preparing",
        "tracking",
        "tracking",
        "separating",
        "transcribing",
        "ready",
    ]


def test_target_lost_failure(tmp_path):
    media = write_media(tmp_path)
    targeting = FakeTargeting(raise_with=TargetLostError("target left frame"))
    worker, repo, _, _ = build(tmp_path, [queued_job(media)], targeting=targeting)
    out = worker.process("job-1")
    assert out.status is JobStatus.FAILED
    assert out.audio_status is AudioStatus.FAILED
    assert out.transcript_status is TranscriptStatus.PENDING
    assert out.error is not None
    assert out.error.code == "TARGET_LOST"
    assert out.error.retryable is True


def test_unexpected_adapter_exception_becomes_honest_generic_failure(tmp_path):
    media = write_media(tmp_path)
    targeting = FakeTargeting(raise_other=ValueError(f"internal leak {media}"))
    worker, repo, _, _ = build(tmp_path, [queued_job(media)], targeting=targeting)
    out = worker.process("job-1")
    assert out.status is JobStatus.FAILED
    assert out.error.code == "PROCESSING_FAILED"
    assert out.error.retryable is False
    assert media not in out.error.message
    assert out.error.message == "processing failed"


def test_missing_media_file_invalid_media(tmp_path):
    worker, _, _, _ = build(tmp_path, [queued_job(str(tmp_path / "absent.mp4"))])
    out = worker.process("job-1")
    assert out.status is JobStatus.FAILED
    assert out.error.code == "INVALID_MEDIA"
    assert out.audio_status is AudioStatus.FAILED


def test_oversized_media_limit_exceeded(tmp_path):
    media = write_media(tmp_path, size=1024)
    worker, _, _, _ = build(tmp_path, [queued_job(media)])
    worker.max_upload_mb = 0
    out = worker.process("job-1")
    assert out.status is JobStatus.FAILED
    assert out.error.code == "LIMIT_EXCEEDED"


def test_missing_face_selection(tmp_path):
    media = write_media(tmp_path)
    job = make_job(video_path=media, face_id=None)
    worker, _, _, _ = build(tmp_path, [job])
    out = worker.process("job-1")
    assert out.status is JobStatus.FAILED
    assert out.error.code == "FACE_NOT_FOUND"


def test_non_absolute_media_path_rejected(tmp_path):
    job = make_job(video_path="relative/clip.mp4")
    worker, _, _, _ = build(tmp_path, [job])
    out = worker.process("job-1")
    assert out.status is JobStatus.FAILED
    assert out.error.code == "INVALID_MEDIA"


def test_requeuing_failed_job_runs_clean(tmp_path):
    media = write_media(tmp_path)
    repo = InMemoryRepository([queued_job(media)])
    targeting = FakeTargeting(raise_with=TargetLostError("target left frame"))
    worker = SingleWorker(
        repo=repo, targeting=targeting, layout=JobDirectoryLayout(str(tmp_path / "runtime"))
    )
    failed = worker.process("job-1")
    assert failed.status is JobStatus.FAILED
    worker.targeting = FakeTargeting()
    fetch = repo.get("job-1")
    fetch.status = JobStatus.QUEUED
    repo.save(fetch)
    retried = worker.process("job-1")
    assert retried.status is JobStatus.COMPLETED
    assert retried.snapshot()["error"] is None
    assert retried.audio_status is AudioStatus.READY


def test_missing_wav_artifact_is_failed_not_completed(tmp_path):
    media = write_media(tmp_path)
    targeting = FakeTargeting(artifact=False)
    worker, _, _, _ = build(tmp_path, [queued_job(media)], targeting=targeting)
    out = worker.process("job-1")
    assert out.status is JobStatus.FAILED
    assert out.audio_status is AudioStatus.FAILED
    assert out.error is not None
    assert out.error.code == "PROCESSING_FAILED"
    assert out.error.retryable is False


def test_wav_outside_job_dir_rejected(tmp_path):
    media = write_media(tmp_path)
    outside = str(tmp_path / "outside.wav")
    with open(outside, "wb") as fh:
        fh.write(b"k" * 32)
    from services.worker import TargetRunResult as TRR

    targeting = FakeTargeting(result=TRR(wav_path=outside, duration_ms=10))
    worker, _, _, _ = build(tmp_path, [queued_job(media)], targeting=targeting)
    out = worker.process("job-1")
    assert out.status is JobStatus.FAILED
    assert out.error.code == "PROCESSING_FAILED"


def test_cancel_after_audio_ready(tmp_path):
    media = write_media(tmp_path)
    state = {"n": 0}
    worker, _, _, _ = build(
        tmp_path, [queued_job(media)], is_cancelled=lambda: state["n"] > 0
    )
    original_extract = worker.targeting.extract

    def extract_then_flip(job, job_dir, on_progress):
        outcome = original_extract(job, job_dir, on_progress)
        state["n"] = 1
        return outcome

    worker.targeting.extract = extract_then_flip
    out = worker.process("job-1")
    assert out.status is JobStatus.CANCELLED
    assert out.audio_status is AudioStatus.READY
    assert out.transcript_status is TranscriptStatus.PENDING


def test_cancel_between_stages(tmp_path):
    media = write_media(tmp_path)
    targeting = FakeTargeting()
    worker, _, _, _ = build(
        tmp_path, [queued_job(media)], targeting=targeting, is_cancelled=lambda: True
    )
    out = worker.process("job-1")
    assert out.status is JobStatus.CANCELLED
    assert targeting.calls == []
    assert out.audio_status is AudioStatus.PENDING


def test_raisings_listener_does_not_corrupt_job(tmp_path):
    media = write_media(tmp_path)

    def exploding_listener(_job):
        raise RuntimeError("listener bug")

    worker, _, targeting, _ = build(tmp_path, [queued_job(media)], transcriber=FakeTranscriber())
    worker._on_stage = exploding_listener
    out = worker.process("job-1")
    assert out.status is JobStatus.COMPLETED
    assert targeting.calls and worker._listener_failures > 0


def test_request_cancel_queued(tmp_path):
    media = write_media(tmp_path)
    worker, repo, targeting, _ = build(tmp_path, [queued_job(media)])
    assert worker.request_cancel("job-1") is True
    assert worker.process("job-1").status is JobStatus.CANCELLED
    assert targeting.calls == []


def test_request_cancel_running_job_returns_false(tmp_path):
    media = write_media(tmp_path)
    worker, repo, _, _ = build(tmp_path, [queued_job(media)])
    worker.process("job-1")
    assert worker.request_cancel("job-1") is False


def test_process_skips_already_finished_job(tmp_path):
    media = write_media(tmp_path)
    worker, repo, targeting, recorder = build(tmp_path, [queued_job(media)])
    first = worker.process("job-1")
    emissions_after_first = len(recorder)
    second = worker.process("job-1")
    assert first.status is second.status is JobStatus.COMPLETED
    assert len(targeting.calls) == 1
    assert len(recorder) == emissions_after_first


def test_recover_interrupted_after_restart(tmp_path):
    media = write_media(tmp_path)
    from services.worker.models import JobStatus as JS

    job = make_job("stuck-1", status=JS.PROCESSING)
    worker, repo, _, recorder = build(tmp_path, [job], transcriber=FakeTranscriber())
    recovered = worker.recover_interrupted()
    assert recovered == ["stuck-1"]
    stuck = repo.get("stuck-1")
    assert stuck.status is JS.FAILED
    assert stuck.error.code == "PROCESSING_FAILED"
    assert stuck.error.retryable is True
    assert stuck.audio_status is AudioStatus.FAILED


def test_recover_interrupted_keeps_ready_audio_failed_transcript(tmp_path):
    from services.worker.models import AudioStatus as AS
    from services.worker.models import TranscriptStatus as TS
    from services.worker.models import JobStatus as JS

    job = make_job("stuck-2", status=JS.PROCESSING, audio_status=AS.READY, transcript_status=TS.PROCESSING)
    worker, repo, _, _ = build(tmp_path, [job])
    worker.recover_interrupted()
    stuck = repo.get("stuck-2")
    assert stuck.audio_status is AudioStatus.READY
    assert stuck.transcript_status is TranscriptStatus.FAILED
    assert stuck.status is JS.FAILED
    assert stuck.snapshot()["result"] is None
    assert stuck.snapshot()["error"] is not None


def test_layout_never_escapes_root(tmp_path):
    layout = JobDirectoryLayout(str(tmp_path / "runtime"))
    for bad in ("evil/../escape", "..", ".", "", "c:evil", "job id with space"):
        evil = make_job(bad, video_path="x")
        with pytest.raises(MediaError):
            layout.job_dir(evil)


def test_job_snapshot_contract_shape(tmp_path):
    media = write_media(tmp_path)
    worker, _, _, _ = build(tmp_path, [queued_job(media)], transcriber=FakeTranscriber())
    out = worker.process("job-1")
    snap = out.snapshot()
    assert set(snap) == {
        "job_id", "status", "stage", "selected_face_id", "audio_status",
        "transcript_status", "queue_position", "error", "result",
    }
    assert snap["status"] == "completed"
    assert snap["stage"] == "ready"
    assert snap["result"]["duration_ms"] == 14000
    assert "wav_path" not in snap["result"]
    assert str(tmp_path) not in str(snap["result"])
