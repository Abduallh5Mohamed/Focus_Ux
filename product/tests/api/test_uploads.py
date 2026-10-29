"""HTTP upload/session contracts; fixtures contain metadata, not real inference."""
import pytest

from .fakes import FakeCandidateProvider
from .fixtures_media import make_mp4_bytes


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert error["retryable"] is False


def test_anonymous_upload_creates_session_and_reuses_bearer(make_api):
    provider = FakeCandidateProvider()
    api = make_api(provider=provider)
    video, token, body = api.upload_ok()
    assert token and body["faces_status"] == "pending"
    assert body["metadata"] == {
        "duration_ms": 1000, "width": 640, "height": 360,
        "mime_type": "video/mp4", "size_bytes": len(make_mp4_bytes()),
    }
    assert provider.calls == []  # requests enqueue; they do not run inference
    assert api.get_faces(video, token).json()["status"] == "pending"
    second = api.upload(token=token)
    assert second.status_code == 201
    assert "session_token" not in second.json()
    assert api.get_original(second.json()["video_id"], token).status_code == 200
    _, other_token, _ = api.upload_ok()
    assert token != other_token
    api.drain()
    assert len(provider.calls) == 3


@pytest.mark.parametrize("authorization", ["Bearer unknown", "Basic abc", "Bearer "])
def test_invalid_authorization_cannot_create_upload(make_api, authorization):
    api = make_api()
    response = api.client.post(
        "/videos", headers={"Authorization": authorization},
        files={"file": ("clip.mp4", make_mp4_bytes(), "video/mp4")},
    )
    assert_error(response, 401, "UNAUTHORIZED")
    assert not list(api.settings.media_dir.iterdir())


@pytest.mark.parametrize("payload,mime", [
    (b"", "video/mp4"),
    (b"not a video", "video/mp4"),
    (make_mp4_bytes()[:40], "video/mp4"),
    (make_mp4_bytes(), "text/plain"),
])
def test_invalid_upload_leaves_no_media_or_queued_work(make_api, payload, mime):
    api = make_api()
    assert_error(api.upload(payload, content_type=mime), 400, "INVALID_MEDIA")
    assert not list(api.settings.tmp_dir.iterdir())
    assert not list(api.settings.media_dir.iterdir())
    assert api.drain() == 0


def test_missing_file_is_structured_validation_error(make_api):
    assert_error(make_api().client.post("/videos"), 422, "INVALID_REQUEST")


@pytest.mark.parametrize("overrides,payload", [
    ({"max_upload_bytes": len(make_mp4_bytes()) - 1}, make_mp4_bytes()),
    ({"max_video_ms": 1000}, make_mp4_bytes(duration_ms=1001)),
    # Cross the service's 1 MiB read boundary, not just a single tiny chunk.
    ({"max_upload_bytes": 1024 * 1024}, make_mp4_bytes() + b"\0" * (1024 * 1024)),
])
def test_over_limit_upload_is_rejected_and_temp_file_removed(
    make_api, make_settings_for, overrides, payload,
):
    api = make_api(settings=make_settings_for(**overrides))
    assert_error(api.upload(payload), 413, "LIMIT_EXCEEDED")
    assert not list(api.settings.tmp_dir.iterdir())
    assert not list(api.settings.media_dir.iterdir())
    assert api.drain() == 0


def test_exact_size_and_duration_limits_are_accepted(make_api, make_settings_for):
    payload = make_mp4_bytes(duration_ms=15_000)
    api = make_api(settings=make_settings_for(
        max_upload_bytes=len(payload), max_video_ms=15_000,
    ))
    video, token, _ = api.upload_ok(data=payload, filename="../../unsafe.mp4")
    assert api.get_original(video, token).content == payload
    assert [p.name for p in api.settings.media_dir.iterdir()] == [f"{video}.mp4"]
    assert not list(api.settings.tmp_dir.iterdir())
