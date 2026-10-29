"""Temporary cleanup is observable, retryable, and isolated from new uploads."""
import errno
import logging
import os
from pathlib import Path

import pytest

from services.api.focus_api import storage as storage_module

from .harness import make_settings


def seed_uploads(settings, monkeypatch):
    now = 2_000_000_000.0
    monkeypatch.setattr(storage_module.time, "time", lambda: now)
    settings.tmp_dir.mkdir(parents=True)
    cutoff = now - settings.cleanup_temp_max_age_s
    files = {
        "failed.upload": cutoff - 10,
        "other.upload": cutoff - 10,
        "fresh.upload": now,
        "boundary.upload": cutoff,
        "unrelated.txt": cutoff - 10,
    }
    for name, modified in files.items():
        path = settings.tmp_dir / name
        path.write_bytes(name.encode())
        os.utime(path, (modified, modified))
    return {name: settings.tmp_dir / name for name in files}


@pytest.mark.parametrize("phase", ["cleanup", "startup"])
@pytest.mark.parametrize("operation", ["stat", "unlink"])
@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO], ids=["permission", "io"])
def test_temp_cleanup_failure_is_logged_and_retried(
    tmp_path, monkeypatch, caplog, make_api, phase, operation, error_number
):
    settings = make_settings(tmp_path)
    paths = seed_uploads(settings, monkeypatch)
    storage = storage_module.Storage(settings)
    target = paths["failed.upload"]
    original = getattr(Path, operation)
    attempted = []

    def fail_one(path, *args, **kwargs):
        attempted.append(path)
        if path == target:
            raise OSError(error_number, "injected temporary cleanup failure", str(path))
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, operation, fail_one)
        with caplog.at_level(logging.WARNING, logger="focus_api.storage"):
            if phase == "startup":
                api = make_api(settings=settings)
            else:
                assert storage.cleanup_stale_temp() == [str(paths["other.upload"])]
                api = make_api(settings=make_settings(tmp_path / "other-api"))
        # An unrelated upload still succeeds while the temporary-file error is active.
        video_id, token, _ = api.upload_ok()
        assert api.get_original(video_id, token).status_code == 200

    assert target in attempted
    records = [r for r in caplog.records if r.name == "focus_api.storage"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.WARNING
    assert str(target) in record.getMessage()
    assert "retained for a later retry" in record.getMessage()
    assert record.exc_info[1].errno == error_number
    assert "injected temporary cleanup failure" in caplog.text
    assert target.read_bytes() == b"failed.upload"
    assert not paths["other.upload"].exists()
    for name in ("fresh.upload", "boundary.upload", "unrelated.txt"):
        assert paths[name].read_bytes() == name.encode()
        if operation == "unlink":
            assert paths[name] not in attempted

    caplog.clear()
    assert storage.cleanup_stale_temp() == [str(target)]
    assert not target.exists()
    assert storage.cleanup_stale_temp() == []
    assert not caplog.records
    for name in ("fresh.upload", "boundary.upload", "unrelated.txt"):
        assert paths[name].read_bytes() == name.encode()
    assert api.get_original(video_id, token).status_code == 200


@pytest.mark.parametrize("operation", ["stat", "unlink"])
def test_temp_cleanup_disappearing_file_is_benign(
    tmp_path, monkeypatch, caplog, operation
):
    settings = make_settings(tmp_path)
    paths = seed_uploads(settings, monkeypatch)
    storage = storage_module.Storage(settings)
    target = paths["failed.upload"]
    original = getattr(Path, operation)
    real_unlink = Path.unlink

    def disappear(path, *args, **kwargs):
        if path == target:
            real_unlink(path)
            raise FileNotFoundError(errno.ENOENT, "concurrently moved", str(path))
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, operation, disappear)
        assert storage.cleanup_stale_temp() == [str(paths["other.upload"])]
    assert not target.exists()
    assert not caplog.records
    for name in ("fresh.upload", "boundary.upload", "unrelated.txt"):
        assert paths[name].read_bytes() == name.encode()


def test_temp_cleanup_missing_directory_is_noop(tmp_path):
    storage = storage_module.Storage(make_settings(tmp_path))
    assert storage.cleanup_stale_temp() == []
