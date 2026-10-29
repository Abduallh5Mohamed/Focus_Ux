"""Temporary cleanup is observable, retryable, and isolated from new uploads."""
import errno
import logging
import os
from pathlib import Path

import pytest

from services.api.focus_api import storage as storage_module
from services.api.focus_api import upload_ownership

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


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO], ids=["permission", "io"])
def test_temp_cleanup_sidecar_open_failure_is_isolated_and_retried(
    tmp_path, monkeypatch, caplog, error_number
):
    settings = make_settings(tmp_path)
    paths = seed_uploads(settings, monkeypatch)
    storage = storage_module.Storage(settings)
    target = paths["failed.upload"]
    lease = target.with_suffix(".upload.lock")
    lease.write_bytes(b"abandoned lease")
    other_lease = paths["other.upload"].with_suffix(".upload.lock")
    other_lease.write_bytes(b"other abandoned lease")
    real_open = open
    attempted = []
    injected_error = OSError(error_number, "injected sidecar open failure", str(lease))

    def fail_one_sidecar(path, *args, **kwargs):
        if path == lease:
            attempted.append(path)
            raise injected_error
        return real_open(path, *args, **kwargs)

    # Keep the original gate open so unlink/recreation cannot hide a leaked lock.
    with storage._temp_gate.open("a+b") as gate_handle:
        gate_stat = os.fstat(gate_handle.fileno())
        gate_identity = (gate_stat.st_dev, gate_stat.st_ino)
        with caplog.at_level(logging.WARNING, logger="focus_api.storage"):
            with monkeypatch.context() as patch:
                # Inject at the actual open, not at Storage's lock wrapper.
                patch.setattr(upload_ownership, "open", fail_one_sidecar, raising=False)
                assert storage.cleanup_stale_temp() == [str(paths["other.upload"])]
                assert attempted == [lease]
                assert target.read_bytes() == b"failed.upload"
                assert lease.read_bytes() == b"abandoned lease"
                assert not paths["other.upload"].exists()
                assert not other_lease.exists()

                # Fail promptly if cleanup leaked the gate, before the creator
                # takes its normal blocking lock on that same storage root.
                with upload_ownership.file_lock(storage._temp_gate, blocking=False):
                    pass
                creator = storage_module.Storage(settings)
                with creator.own_temp_upload() as created:
                    created.write_bytes(b"new upload")
                    now = storage_module.time.time()
                    os.utime(created, (now, now))
                    created_lease = created.with_suffix(".upload.lock")
                    assert created_lease.exists()
                assert created.read_bytes() == b"new upload"
                assert not created_lease.exists()

        records = [r for r in caplog.records if r.name == "focus_api.storage"]
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert str(target) in records[0].getMessage()
        assert "retained for a later retry" in records[0].getMessage()
        assert records[0].exc_info[1] is injected_error
        assert records[0].exc_info[1].errno == error_number
        assert "injected sidecar open failure" in caplog.text
        for name in ("fresh.upload", "boundary.upload", "unrelated.txt"):
            assert paths[name].read_bytes() == name.encode()

        caplog.clear()
        assert storage.cleanup_stale_temp() == [str(target)]
        assert not target.exists()
        assert not lease.exists()
        assert storage.cleanup_stale_temp() == []
        assert not caplog.records
        assert created.read_bytes() == b"new upload"
        for name in ("fresh.upload", "boundary.upload", "unrelated.txt"):
            assert paths[name].read_bytes() == name.encode()
        gate_stat = storage._temp_gate.stat()
        assert (gate_stat.st_dev, gate_stat.st_ino) == gate_identity
        with upload_ownership.file_lock(storage._temp_gate, blocking=False):
            pass


def test_temp_cleanup_missing_directory_is_noop(tmp_path):
    storage = storage_module.Storage(make_settings(tmp_path))
    assert storage.cleanup_stale_temp() == []


@pytest.mark.parametrize("has_data", [True, False], ids=["abandoned-data", "orphan-lease"])
@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO], ids=["permission", "io"])
def test_cleaner_sidecar_unlink_failure_releases_gate_and_recovers(
    tmp_path, monkeypatch, caplog, make_api, has_data, error_number
):
    settings = make_settings(tmp_path)
    api = make_api(settings=settings)
    storage = api.app.state.storage
    target = settings.tmp_dir / "000-abandoned.upload"
    lease_path = target.with_suffix(".upload.lock")
    lease_path.touch()
    if has_data:
        target.write_bytes(b"abandoned")
        os.utime(target, (1, 1))
    other = settings.tmp_dir / "zzz-other.upload"
    other.write_bytes(b"other abandoned upload")
    os.utime(other, (1, 1))
    other_lease = other.with_suffix(".upload.lock")
    other_lease.touch()
    gate = storage._temp_gate
    with storage_module.file_lock(gate, blocking=False):
        pass
    gate_identity = (gate.stat().st_dev, gate.stat().st_ino)
    real_unlink = Path.unlink
    failed_attempts = []

    def fail_sidecar_unlink(path, *args, **kwargs):
        if path == lease_path:
            # This is the cleaner's post-unlock removal, not owner release.
            # Real nonblocking locks fail promptly if either lease leaked.
            with storage_module.file_lock(lease_path, blocking=False):
                pass
            with pytest.raises(BlockingIOError):
                with storage_module.file_lock(gate, blocking=False):
                    pytest.fail("cleaner removed a sidecar without holding the gate")
            assert not target.exists()
            failed_attempts.append(path)
            raise OSError(error_number, "injected cleaner sidecar failure", str(path))
        return real_unlink(path, *args, **kwargs)

    with storage.own_temp_upload() as active:
        active.write_bytes(b"paused active upload")
        os.utime(active, (1, 1))
        active_lease = active.with_suffix(".upload.lock")
        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", fail_sidecar_unlink)
            with caplog.at_level(logging.WARNING, logger="focus_api.storage"):
                expected = [str(target), str(other)] if has_data else [str(other)]
                assert storage.cleanup_stale_temp() == expected
                assert failed_attempts == [lease_path]
                assert lease_path.exists()
                assert not other.exists()
                assert not other_lease.exists()

                # Check before any blocking API operation so a leaked gate
                # produces a failure instead of hanging the upload request.
                with storage_module.file_lock(gate, blocking=False):
                    pass
                video_id, token, _ = api.upload_ok()
                assert api.get_original(video_id, token).status_code == 200

                # Failure persists, but another stale entry is still cleaned.
                later = settings.tmp_dir / "zzz-later.upload"
                later.write_bytes(b"later abandoned upload")
                os.utime(later, (1, 1))
                assert storage.cleanup_stale_temp() == [str(later)]
                assert not later.with_suffix(".upload.lock").exists()
                assert failed_attempts == [lease_path, lease_path]
                with storage_module.file_lock(gate, blocking=False):
                    pass

            records = [r for r in caplog.records if r.name == "focus_api.storage"]
            assert len(records) == 2
            for record in records:
                assert record.levelno == logging.WARNING
                assert str(target) in record.getMessage()
                assert "retained for a later retry" in record.getMessage()
                assert record.exc_info[1].errno == error_number
                assert record.exc_info[1].filename == str(lease_path)
            assert "injected cleaner sidecar failure" in caplog.text
            assert active.read_bytes() == b"paused active upload"
            assert active_lease.exists()
            assert lease_path.exists()

        caplog.clear()
        # The data is already gone: recovery must discover the orphan sidecar.
        assert storage.cleanup_stale_temp() == []
        assert not lease_path.exists()
        assert storage.cleanup_stale_temp() == []
        assert not caplog.records
        assert active.read_bytes() == b"paused active upload"
        assert active_lease.exists()
        with pytest.raises(BlockingIOError):
            with storage_module.file_lock(active_lease, blocking=False):
                pytest.fail("cleanup released the active upload's ownership")
        assert api.get_original(video_id, token).status_code == 200
        assert (gate.stat().st_dev, gate.stat().st_ino) == gate_identity

    assert not active_lease.exists()
    assert storage.cleanup_stale_temp() == [str(active)]
    assert storage.cleanup_stale_temp() == []
    assert not list(settings.tmp_dir.iterdir())
    assert (gate.stat().st_dev, gate.stat().st_ino) == gate_identity
