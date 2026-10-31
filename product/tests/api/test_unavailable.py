from services.api.focus_api.interfaces import (
    UnavailableCandidateProvider, UnavailableExtractionRunner,
)

from .test_uploads import assert_error


def test_unavailable_detector_reports_failure_without_fake_faces(make_api):
    api = make_api(provider=UnavailableCandidateProvider())
    video, token, _ = api.upload_ok()
    assert api.get_faces(video, token).json()["status"] == "pending"
    api.drain()
    response = api.get_faces(video, token)
    assert response.status_code == 200
    assert response.json() == {
        "status": "failed", "faces": [],
        "error": {"code": "PROCESSING_FAILED",
                  "message": "face candidate provider is not configured", "retryable": True},
        "detector": None, "voice_only_fallback": False, "detector_error": None,
    }
    assert not list(api.settings.thumbs_dir.iterdir())


def test_unavailable_extractor_never_marks_audio_ready(make_api):
    api = make_api(runner=UnavailableExtractionRunner())
    data = api.setup_video()
    response = api.create_job(data["video_id"], data["face_id"], "unavailable", data["token"])
    assert response.status_code == 202
    job = response.json()["job_id"]
    api.drain()
    state = api.get_job(job, data["token"]).json()
    assert state["status"] == "failed"
    assert state["audio_status"] == "failed"
    assert state["result"] is None
    assert state["error"] == {
        "code": "PROCESSING_FAILED", "message": "extraction runner is not configured",
        "retryable": True,
    }
    assert_error(api.get_audio(job, data["token"]), 409, "NO_AUDIO")
    assert not list(api.settings.jobs_dir.rglob("*.wav"))
