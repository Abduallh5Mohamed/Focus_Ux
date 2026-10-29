"""Real storage failures must retain private tombstones and retry information."""
import errno
import logging
from pathlib import Path

import pytest

from services.api.focus_api import storage as storage_module

from .harness import make_settings
from .test_recovery import enqueue_job, open_api


def test_storage_missing_paths_are_idempotent_but_missing_children_are_not(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    assert storage_module._unlink(missing) == ""
    assert storage_module._rmtree(missing) == []
    tree = tmp_path / "tree"
    tree.mkdir()
    retained = tree / "retained"
    retained.write_bytes(b"private")

    def missing_child(path):
        raise FileNotFoundError(errno.ENOENT, "child disappeared", str(tree / "child"))

    monkeypatch.setattr(storage_module.shutil, "rmtree", missing_child)
    with pytest.raises(FileNotFoundError, match="child disappeared"):
        storage_module._rmtree(tree)
    assert retained.read_bytes() == b"private"


def assert_private(api, data, job_id):
    paths = [
        f"/videos/{data['video_id']}/original",
        f"/videos/{data['video_id']}/faces",
        f"/videos/{data['video_id']}/faces/{data['face_id']}/thumbnail",
        f"/jobs/{job_id}",
        f"/jobs/{job_id}/audio",
        f"/jobs/{job_id}/transcript",
    ]
    for path in paths:
        for extra in ({}, {"Range": "bytes=0-3"}):
            response = api.client.get(path, headers={**api.auth(data["token"]), **extra})
            assert response.status_code == 404, (path, response.text)


def assert_paths_retained(api, data, original, canonical, thumbnail_paths):
    video = api.repo.get_video(data["video_id"])
    assert video.deleted
    assert video.original_path == original
    assert video.canonical_path == canonical
    assert [face.thumbnail_path for face in api.repo.get_faces(data["video_id"])] == thumbnail_paths


def assert_cleaned(api, data, job_id, original, thumbs, artifacts):
    assert not Path(original).exists()
    assert not thumbs.exists()
    assert not artifacts.exists()
    video = api.repo.get_video(data["video_id"])
    assert video.deleted
    assert video.original_path is None and video.canonical_path is None
    assert all(face.thumbnail_path is None for face in api.repo.get_faces(data["video_id"]))
    assert_private(api, data, job_id)


@pytest.mark.parametrize("phase", ["queued", "startup"])
@pytest.mark.parametrize("target_kind", ["unlink", "thumbs", "jobs"])
@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO], ids=["permission", "io"])
def test_cleanup_failure_retains_paths_and_retries(
    tmp_path, monkeypatch, caplog, phase, target_kind, error_number
):
    settings = make_settings(tmp_path)
    with open_api(settings) as api:
        data = api.setup_video()
        job_id = enqueue_job(api, data)
        api.drain()
        video = api.repo.get_video(data["video_id"])
        original, canonical = video.original_path, video.canonical_path
        thumbnail_paths = [face.thumbnail_path for face in api.repo.get_faces(data["video_id"])]
        thumbs = settings.thumbs_dir / data["video_id"]
        artifacts = settings.jobs_dir / job_id
        survivor = api.setup_video()
        survivor_job = enqueue_job(api, survivor, "survivor")
        api.drain()
        survivor_files = {
            path: path.read_bytes()
            for root in (
                Path(api.repo.get_video(survivor["video_id"]).original_path),
                settings.thumbs_dir / survivor["video_id"],
                settings.jobs_dir / survivor_job,
            )
            for path in ([root] if root.is_file() else root.rglob("*"))
            if path.is_file()
        }
        target = {"unlink": Path(original), "thumbs": thumbs, "jobs": artifacts}[target_kind]
        # Leave multiple files so rmtree can fail after a partial removal.
        if target_kind != "unlink":
            (target / "partial-artifact").write_bytes(b"private")
        assert api.delete_video(data["video_id"], data["token"]).status_code == 202

        with monkeypatch.context() as patch:
            if target_kind == "unlink":
                real_unlink = Path.unlink

                def failing_unlink(path, *args, **kwargs):
                    if path == target:
                        raise OSError(error_number, "injected cleanup failure", str(path))
                    return real_unlink(path, *args, **kwargs)

                patch.setattr(Path, "unlink", failing_unlink)
            else:
                real_rmtree = storage_module.shutil.rmtree

                def failing_rmtree(path, *args, **kwargs):
                    if Path(path) == target:
                        (target / "partial-artifact").unlink(missing_ok=True)
                        raise OSError(error_number, "injected cleanup failure", str(path))
                    return real_rmtree(path, *args, **kwargs)

                patch.setattr(storage_module.shutil, "rmtree", failing_rmtree)

            if phase == "queued":
                with caplog.at_level(logging.ERROR, logger="focus_api.dispatcher"):
                    assert api.drain() == 0
                assert "dispatcher task failed: cleanup" in caplog.text
                assert "injected cleanup failure" in caplog.text
            else:
                # Use a fresh app: startup must exercise the actual helpers,
                # not a mock of remove_media or remove_job_dir.
                with open_api(settings) as failed:
                    with pytest.raises(OSError, match="injected cleanup failure") as exc:
                        failed.dispatcher.start()
                    assert exc.value.errno == error_number
                    assert not failed.dispatcher.lock_acquired
                    assert not failed.dispatcher.lock.held
                    assert_private(failed, data, job_id)
                    assert_paths_retained(failed, data, original, canonical, thumbnail_paths)

            assert target.exists()
            if target_kind != "unlink":
                assert not (target / "partial-artifact").exists()
                assert any(target.iterdir())
            assert_private(api, data, job_id)
            assert_paths_retained(api, data, original, canonical, thumbnail_paths)
            assert all(path.read_bytes() == content for path, content in survivor_files.items())

        if phase == "queued":
            # No restart or private dispatcher API is needed to retry.
            assert api.delete_video(data["video_id"], data["token"]).status_code == 202
            assert api.drain() == 1
            assert_cleaned(api, data, job_id, original, thumbs, artifacts)

    # Retry persisted tombstones after losing the queue, then check idempotence.
    for _ in range(2):
        with open_api(settings, start_dispatcher=True) as restarted:
            assert restarted.dispatcher.wait_idle()
            assert_cleaned(restarted, data, job_id, original, thumbs, artifacts)
            assert all(path.read_bytes() == content for path, content in survivor_files.items())
            assert restarted.get_original(survivor["video_id"], survivor["token"]).status_code == 200
            assert restarted.get_audio(survivor_job, survivor["token"]).status_code == 200
