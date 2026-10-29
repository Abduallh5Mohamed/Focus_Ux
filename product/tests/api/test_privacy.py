from pathlib import Path

import pytest

from .fakes import DEFAULT_FACES, FakeExtractionRunner, make_wav_bytes
from .fixtures_media import make_mp4_bytes
from .test_uploads import assert_error


@pytest.fixture
def ready_media(make_api):
    api = make_api()
    data = api.setup_video()
    response = api.create_job(data["video_id"], data["face_id"], "ready", data["token"])
    assert response.status_code == 202
    job = response.json()["job_id"]
    assert api.get_job(job, data["token"]).json()["status"] == "queued"
    api.drain()
    assert api.get_job(job, data["token"]).json()["status"] == "completed"
    _, stranger, _ = api.upload_ok()
    video, face = data["video_id"], data["face_id"]
    return api, data, job, stranger, [
        (f"/videos/{video}/original", make_mp4_bytes(), "video/mp4"),
        (f"/videos/{video}/faces/{face}/thumbnail", DEFAULT_FACES[0].thumbnail_bytes, "image/jpeg"),
        (f"/jobs/{job}/audio", make_wav_bytes(), "audio/wav"),
    ]


def test_all_media_require_owner_bearer_not_query_token(ready_media):
    api, data, job, stranger, media = ready_media
    for path, expected, mime in media:
        owner = api.client.get(path, headers=api.auth(data["token"]))
        assert owner.status_code == 200
        assert owner.content == expected
        assert owner.headers["content-type"] == mime
        assert owner.headers["cache-control"] == "private, no-store"
        for headers in ({}, api.auth("unknown"), {"Authorization": "Basic invalid"}):
            assert_error(api.client.get(path, headers=headers), 401, "UNAUTHORIZED")
        for key in ("token", "session_token"):
            assert_error(api.client.get(path, params={key: data["token"]}), 401, "UNAUTHORIZED")
        assert_error(api.client.get(path, headers=api.auth(stranger)), 404, "NOT_FOUND")
        # A Range request must not bypass ownership checks.
        assert_error(api.client.get(path, headers={**api.auth(stranger), "Range": "bytes=0-3"}),
                     404, "NOT_FOUND")
        partial = api.client.get(path, headers={**api.auth(data["token"]), "Range": "bytes=0-3"})
        assert partial.status_code == 206
        assert partial.content == expected[:4]
        assert partial.headers["content-range"] == f"bytes 0-3/{len(expected)}"
    for path in (f"/videos/{data['video_id']}/faces", f"/jobs/{job}", f"/jobs/{job}/transcript"):
        assert_error(api.client.get(path, headers=api.auth(stranger)), 404, "NOT_FOUND")


def test_delete_revokes_access_before_async_cleanup_and_is_idempotent(ready_media):
    api, data, job, stranger, media = ready_media
    video, token = data["video_id"], data["token"]
    original = Path(api.repo.get_video(video).original_path)
    thumb_dir = api.settings.thumbs_dir / video
    job_dir = api.settings.jobs_dir / job
    assert_error(api.delete_video(video, stranger), 404, "NOT_FOUND")
    assert_error(api.delete_video(video, None), 401, "UNAUTHORIZED")
    assert original.exists()
    for _ in range(2):
        response = api.delete_video(video, token)
        assert response.status_code == 202
        assert response.json() == {"deletion_pending": True}
    assert original.exists() and thumb_dir.exists() and job_dir.exists()
    paths = [path for path, _, _ in media] + [
        f"/videos/{video}/faces", f"/jobs/{job}", f"/jobs/{job}/transcript",
    ]
    for path in paths:
        assert_error(api.client.get(path, headers=api.auth(token)), 404, "NOT_FOUND")
    assert_error(api.create_job(video, data["face_id"], "after-delete", token), 404, "NOT_FOUND")
    api.drain()
    assert not original.exists()
    assert not thumb_dir.exists()
    assert not job_dir.exists()
    for path in paths:
        assert_error(api.client.get(path, headers=api.auth(token)), 404, "NOT_FOUND")


def test_deleting_queued_job_prevents_extraction(make_api):
    runner = FakeExtractionRunner()
    api = make_api(runner=runner)
    data = api.setup_video()
    response = api.create_job(data["video_id"], data["face_id"], "queued", data["token"])
    assert response.status_code == 202
    assert api.delete_video(data["video_id"], data["token"]).status_code == 202
    api.drain()
    assert runner.calls == []
    assert not list(api.settings.media_dir.iterdir())
    assert not list(api.settings.jobs_dir.iterdir())
