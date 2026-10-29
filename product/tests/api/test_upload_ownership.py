"""Real processes must not mistake a paused upload for abandoned data."""
import logging
import multiprocessing
import os
import queue
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from threading import BrokenBarrierError

import pytest

from services.api.focus_api import storage as storage_module
from services.api.focus_api.storage import Storage
from services.api.focus_api.upload_ownership import file_lock

from .harness import make_settings


OWNER = r"""
import io
import sys
from pathlib import Path
from fastapi.testclient import TestClient
from api.fixtures_media import make_mp4_bytes
from services.api.focus_api import service
from services.api.focus_api.config import Settings
from services.api.focus_api.routes import create_app
from services.api.focus_api.storage import Storage

root, phase = Path(sys.argv[1]), sys.argv[2]
settings = Settings(storage_root=root, cleanup_temp_max_age_s=0.02)

def pause():
    (root / "paused").write_text("ready")
    assert sys.stdin.readline().strip() == "resume"

if phase == "before-file":
    storage = Storage(settings)
    storage.ensure()
    with storage.own_temp_upload() as path:
        pause()
    sys.exit(0)

class PausedStream(io.BytesIO):
    def read(self, size=-1):
        if phase == "read" and self.tell():
            pause()
        return super().read(size)

original_probe = service.probe_video
def probe(path):
    if phase == "probe":
        pause()
    return original_probe(path)
service.probe_video = probe

original_replace = service.os.replace
def replace(source, target):
    if phase == "move":
        pause()
    return original_replace(source, target)
service.os.replace = replace

app = create_app(settings=settings, start_dispatcher=False)
with TestClient(app):
    body, _ = app.state.service.upload(
        stream=PausedStream(make_mp4_bytes()), content_type="video/mp4", token=None
    )
    assert app.state.storage.find_media_path(body["video_id"]).is_file()
"""


@pytest.mark.parametrize("phase", ["read", "probe", "move", "before-file"])
@pytest.mark.parametrize("crash", [False, True], ids=["resume", "owner-killed"])
def test_startup_preserves_paused_owner_and_recovers_after_exit(
    tmp_path, make_api, phase, crash
):
    settings = make_settings(tmp_path, cleanup_temp_max_age_s=0.02)
    product = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(product), str(product / "tests"), env.get("PYTHONPATH", "")]
    )
    owner = subprocess.Popen(
        [sys.executable, "-c", OWNER, str(tmp_path), phase],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not (tmp_path / "paused").exists():
            if owner.poll() is not None:
                stdout, stderr = owner.communicate()
                pytest.fail(f"Owner exited before pause:\n{stdout}\n{stderr}")
            assert time.monotonic() < deadline, "owner did not reach upload pause"
            time.sleep(0.01)

        files = list(settings.tmp_dir.glob("*.upload"))
        assert len(files) == (0 if phase == "before-file" else 1)
        leases = list(settings.tmp_dir.glob("*.upload.lock"))
        assert len(leases) == 1
        # The owner remains blocked longer than the configured age. Backdate
        # as well to make the cutoff deterministic on coarse timestamp filesystems.
        for path in files:
            os.utime(path, (1, 1))
        time.sleep(settings.cleanup_temp_max_age_s * 2)
        if files:
            assert time.time() - files[0].stat().st_mtime > settings.cleanup_temp_max_age_s
        abandoned = settings.tmp_dir / "abandoned.upload"
        abandoned.write_bytes(b"unowned")
        os.utime(abandoned, (1, 1))

        # A genuinely separate API instance performs its normal startup pass.
        cleaner = make_api(settings=settings)
        assert not abandoned.exists()
        assert all(path.exists() for path in files + leases)
        assert cleaner.app.state.storage.cleanup_stale_temp() == []
        assert all(path.exists() for path in files + leases)

        if crash:
            # No context-manager/finally cleanup is run by the owner.
            owner.kill()
            owner.communicate(timeout=10)
            removed = cleaner.app.state.storage.cleanup_stale_temp()
            assert removed == [str(path) for path in files]
            assert not list(settings.media_dir.iterdir())
        else:
            stdout, stderr = owner.communicate("resume\n", timeout=15)
            assert owner.returncode == 0, f"{stdout}\n{stderr}"
            assert len(list(settings.media_dir.iterdir())) == (0 if phase == "before-file" else 1)

        assert not list(settings.tmp_dir.iterdir())
        assert cleaner.app.state.storage.cleanup_stale_temp() == []
        # Another startup is safe after the recovery and does not remove media.
        Storage(settings).ensure()
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=10)


def test_lease_protects_against_another_storage_in_same_process(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    storage.ensure()
    with storage.own_temp_upload() as path:
        path.write_bytes(b"paused")
        os.utime(path, (1, 1))
        Storage(settings).ensure()
        assert path.read_bytes() == b"paused"
    # A failed upload whose file could not be deleted is no longer protected.
    assert Storage(settings).cleanup_stale_temp() == [str(path)]
    assert not list(settings.tmp_dir.iterdir())


@pytest.mark.parametrize("failure_point", ["gate", "sidecar-unlink"])
@pytest.mark.parametrize("upload_fails", [False, True], ids=["success", "upload-error"])
def test_exit_housekeeping_failure_preserves_result_and_releases_lease(
    tmp_path, monkeypatch, caplog, failure_point, upload_fails
):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    storage.ensure()
    housekeeping_error = PermissionError("injected lease housekeeping failure")
    upload_error = RuntimeError("original upload failure")
    result = object()
    original_unlink = Path.unlink
    path = None
    lease_path = None
    armed = False
    injected = []

    @contextmanager
    def failing_gate(lock_path, *, blocking=True):
        if armed and lock_path == storage._temp_gate:
            injected.append("gate")
            raise housekeeping_error
        with file_lock(lock_path, blocking=blocking):
            yield

    def failing_unlink(target, *args, **kwargs):
        if armed and target == lease_path:
            injected.append("sidecar-unlink")
            raise housekeeping_error
        return original_unlink(target, *args, **kwargs)

    def upload():
        nonlocal path, lease_path, armed
        with storage.own_temp_upload() as owned_path:
            path = owned_path
            lease_path = path.with_suffix(".upload.lock")
            path.write_bytes(b"abandoned upload data")
            os.utime(path, (1, 1))
            # Prove that a real OS lease is held before injecting an exit fault.
            with pytest.raises(BlockingIOError):
                with file_lock(lease_path, blocking=False):
                    pytest.fail("upload did not hold its lease")
            armed = True
            if upload_fails:
                raise upload_error
        return result

    with caplog.at_level(logging.WARNING, logger="focus_api.storage"):
        with monkeypatch.context() as patch:
            if failure_point == "gate":
                patch.setattr(storage_module, "file_lock", failing_gate)
            else:
                patch.setattr(Path, "unlink", failing_unlink)
            if upload_fails:
                with pytest.raises(RuntimeError) as raised:
                    upload()
                assert raised.value is upload_error
            else:
                assert upload() is result

    assert injected == [failure_point]
    assert path.read_bytes() == b"abandoned upload data"
    assert lease_path.exists()
    warnings = [
        record for record in caplog.records
        if record.name == "focus_api.storage" and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "Temporary upload lease cleanup failed" in warnings[0].getMessage()
    assert str(lease_path) in warnings[0].getMessage()
    assert warnings[0].exc_info[1] is housekeeping_error

    # Reacquire the leftover sidecar, not a replacement: both exit failure
    # branches must release the OS lease even though its file remains.
    with file_lock(lease_path, blocking=False):
        assert lease_path.exists()

    cleaner = Storage(settings)
    assert cleaner.cleanup_stale_temp() == [str(path)]
    assert not path.exists()
    assert not lease_path.exists()
    assert cleaner.cleanup_stale_temp() == []
    assert not list(settings.tmp_dir.iterdir())


def _paused_cleaner(root, connection):
    """Expose real gate opens/locks and pause immediately before sidecar unlink."""
    import builtins

    from services.api.focus_api import storage as storage_module
    from services.api.focus_api import upload_ownership

    storage = Storage(make_settings(root, cleanup_temp_max_age_s=0.02))
    gate = storage._temp_gate
    original_lock = storage_module.file_lock
    original_unlink = Path.unlink

    def traced_open(path, *args, **kwargs):
        handle = builtins.open(path, *args, **kwargs)
        if path == gate:
            stat = os.fstat(handle.fileno())
            connection.send(("opened", (stat.st_dev, stat.st_ino)))
        return handle

    @contextmanager
    def traced_lock(path, **kwargs):
        with original_lock(path, **kwargs):
            if path == gate:
                connection.send(("held", None))
                assert connection.poll(15), "gate holder was not resumed"
                assert connection.recv() == "continue"
            yield

    def traced_unlink(path, *args, **kwargs):
        if path.suffix == ".lock" and path != gate:
            connection.send(("unlink", str(path)))
            assert connection.poll(15), "sidecar removal was not resumed"
            assert connection.recv() == "continue"
        return original_unlink(path, *args, **kwargs)

    upload_ownership.open = traced_open
    storage_module.file_lock = traced_lock
    Path.unlink = traced_unlink
    try:
        connection.send(("done", storage.cleanup_stale_temp()))
    except BaseException:
        connection.send(("error", traceback.format_exc()))
        raise
    finally:
        connection.close()


def _ownership_contender(root, role, rounds, barrier, results):
    """All processes cross the same five boundaries; no scheduling sleeps."""
    storage = Storage(make_settings(root, cleanup_temp_max_age_s=0.02))
    try:
        for cycle in range(rounds):
            if role == "cleaner":
                for _ in range(5):
                    barrier.wait(timeout=15)
                    # Exercise startup and repeated cleanup from each process.
                    storage.ensure()
                    storage.cleanup_stale_temp()
                    barrier.wait(timeout=15)
                continue

            barrier.wait(timeout=15)
            with storage.own_temp_upload() as path:
                # Pause with a sidecar but no data, while cleaners are starting.
                barrier.wait(timeout=15)
                barrier.wait(timeout=15)
                payload = f"{role}:{cycle}".encode()
                path.write_bytes(payload)
                os.utime(path, (1, 1))
                barrier.wait(timeout=15)
                assert path.read_bytes() == payload
                assert path.with_suffix(".upload.lock").is_file()

                # A complete cleanup wave must inspect the backdated active file.
                barrier.wait(timeout=15)
                barrier.wait(timeout=15)
                assert path.read_bytes() == payload
                assert path.with_suffix(".upload.lock").is_file()

                barrier.wait(timeout=15)
                if role == "promote":
                    target = storage.settings.media_dir / f"{cycle}.mp4"
                    os.replace(path, target)
                # The other owner leaves a failed upload for the recovery wave.
            barrier.wait(timeout=15)
            barrier.wait(timeout=15)
            barrier.wait(timeout=15)
            assert not path.exists()
            assert not path.with_suffix(".upload.lock").exists()
        results.put((role, None))
    except BaseException:
        results.put((role, traceback.format_exc()))
        barrier.abort()
        raise


@pytest.fixture
def upload_processes():
    """Use spawn even on Unix: each contender has independent lock state."""
    context = multiprocessing.get_context("spawn")
    processes = []
    connections = []

    def start(target, *args):
        process = context.Process(target=target, args=args)
        processes.append(process)
        process.start()
        return process

    def cleaner(root):
        parent, child = context.Pipe()
        connections.append(parent)
        process = start(_paused_cleaner, root, child)
        child.close()
        return process, parent

    yield context, start, cleaner

    # A failed assertion must not leave blocked cleaners running in later tests.
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=10)
        if process.is_alive():
            process.kill()
            process.join(timeout=10)
        process.close()
    for connection in connections:
        connection.close()


def _receive(connection, expected):
    assert connection.poll(15), f"cleaner did not report {expected}"
    event, value = connection.recv()
    assert event == expected, f"expected {expected}, received {event}: {value}"
    return value


def test_simultaneous_cleaners_keep_one_gate_identity(tmp_path, upload_processes):
    settings = make_settings(tmp_path, cleanup_temp_max_age_s=0.02)
    storage = Storage(settings)
    storage.ensure()
    abandoned = settings.tmp_dir / "abandoned.upload"
    abandoned.write_bytes(b"abandoned")
    os.utime(abandoned, (1, 1))
    lease = abandoned.with_suffix(".upload.lock")
    lease.touch()
    _, _, start_cleaner = upload_processes

    # Keep a handle to the original gate, so unlink/recreation cannot silently
    # pass by reusing its inode. This is the identity every contender must lock.
    with storage._temp_gate.open("a+b") as gate_handle:
        stat = os.fstat(gate_handle.fileno())
        identity = (stat.st_dev, stat.st_ino)
        first, first_pipe = start_cleaner(tmp_path)
        assert _receive(first_pipe, "opened") == identity
        _receive(first_pipe, "held")
        first_pipe.send("continue")
        assert _receive(first_pipe, "unlink") == str(lease)
        assert not abandoned.exists()
        assert lease.exists()

        # The second cleaner has snapshotted the still-existing sidecar and
        # opened the gate while the first is between lease unlock and unlink.
        second, second_pipe = start_cleaner(tmp_path)
        assert _receive(second_pipe, "opened") == identity
        with pytest.raises(BlockingIOError):
            with file_lock(storage._temp_gate, blocking=False):
                pytest.fail("first cleaner released the gate before sidecar removal")
        assert not second_pipe.poll(0.1), "second cleaner bypassed the held gate"

        first_pipe.send("continue")
        assert _receive(first_pipe, "done") == [str(abandoned)]
        first.join(timeout=15)
        assert first.exitcode == 0
        _receive(second_pipe, "held")
        stat = storage._temp_gate.stat()
        assert (stat.st_dev, stat.st_ino) == identity
        with pytest.raises(BlockingIOError):
            with file_lock(storage._temp_gate, blocking=False):
                pytest.fail("second cleaner locked a different gate identity")

        second_pipe.send("continue")
        # Its stale snapshot may recreate the removed lease, but must remove it
        # again, without reporting the abandoned upload twice.
        assert _receive(second_pipe, "unlink") == str(lease)
        second_pipe.send("continue")
        assert _receive(second_pipe, "done") == []
        second.join(timeout=15)
        assert second.exitcode == 0
        assert not list(settings.tmp_dir.iterdir())
        stat = storage._temp_gate.stat()
        assert (stat.st_dev, stat.st_ino) == identity


def test_cleanup_contenders_race_upload_creation_and_release(
    tmp_path, upload_processes
):
    settings = make_settings(tmp_path, cleanup_temp_max_age_s=0.02)
    storage = Storage(settings)
    storage.ensure()
    # Cover both old data with a leftover lease and a lease without data.
    abandoned = settings.tmp_dir / "abandoned.upload"
    abandoned.write_bytes(b"abandoned")
    os.utime(abandoned, (1, 1))
    abandoned.with_suffix(".upload.lock").touch()
    (settings.tmp_dir / "orphan.upload.lock").touch()

    context, start, _ = upload_processes
    roles = ["cleaner"] * 3 + ["failed", "promote"]
    barrier = context.Barrier(len(roles) + 1)
    results = context.Queue()
    rounds = 8
    processes = [
        start(_ownership_contender, tmp_path, role, rounds, barrier, results)
        for role in roles
    ]
    try:
        # Holding the original gate open also detects unlink/recreation here.
        with storage._temp_gate.open("a+b") as gate_handle:
            stat = os.fstat(gate_handle.fileno())
            identity = (stat.st_dev, stat.st_ino)
            for cycle in range(rounds):
                for phase in range(5):
                    barrier.wait(timeout=15)
                    barrier.wait(timeout=15)
                    stat = storage._temp_gate.stat()
                    assert (stat.st_dev, stat.st_ino) == identity
                    if phase in (0, 1, 2):
                        assert len(list(settings.tmp_dir.glob("*.upload.lock"))) == 2
                        files = list(settings.tmp_dir.glob("*.upload"))
                        assert len(files) == (0 if phase == 0 else 2)
                        if files:
                            assert {path.read_bytes() for path in files} == {
                                f"failed:{cycle}".encode(), f"promote:{cycle}".encode()
                            }
                    if phase == 4:
                        assert not list(settings.tmp_dir.iterdir())
            for cycle in range(rounds):
                assert (settings.media_dir / f"{cycle}.mp4").read_bytes() == (
                    f"promote:{cycle}".encode()
                )
            assert len(list(settings.media_dir.iterdir())) == rounds
            assert storage.cleanup_stale_temp() == []
            assert not list(settings.tmp_dir.iterdir())
        reports = [results.get(timeout=15) for _ in processes]
        assert all(error is None for _, error in reports), reports
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
    except BrokenBarrierError:
        reports = []
        while True:
            try:
                reports.append(results.get(timeout=0.2))
            except queue.Empty:
                break
        pytest.fail(f"upload/cleanup coordination failed: {reports}")
    finally:
        barrier.abort()
        results.close()
        results.join_thread()
