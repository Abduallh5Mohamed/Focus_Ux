"""Exercise the in-process registry and the actual cross-process OS lock."""
import os
import subprocess
import sys
from pathlib import Path

from services.api.focus_api.lock import DispatcherLock


def test_lock_excludes_same_process_and_allows_handoff(tmp_path):
    path = tmp_path / "dispatcher.lock"
    owner = DispatcherLock(path)
    contender = DispatcherLock(path.parent / "." / path.name)
    try:
        assert owner.acquire()
        assert owner.held
        assert owner.acquire() is False
        assert contender.acquire() is False
        assert not contender.held
        # Releasing a failed contender must not free another dispatcher's lock.
        contender.release()
        assert DispatcherLock(path).acquire() is False
        owner.release()
        owner.release()
        assert not owner.held
        assert contender.acquire()
        assert contender.held
        assert owner.acquire() is False
    finally:
        contender.release()
        owner.release()
    with DispatcherLock(path) as acquired:
        assert acquired.held
    assert not acquired.held


def try_lock_in_fresh_process(path):
    # Fresh interpreter avoids inheriting the module registry (or lock handles).
    # os._exit deliberately skips Python cleanup to model process death.
    code = """
import os
import sys
from services.api.focus_api.lock import DispatcherLock
lock = DispatcherLock(sys.argv[1])
os._exit(0 if lock.acquire() else 73)
"""
    env = os.environ.copy()
    product = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = product + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-c", code, str(path)],
        env=env, capture_output=True, text=True, timeout=10,
    )


def test_os_lock_excludes_other_process_and_is_released_on_process_exit(tmp_path):
    path = tmp_path / "dispatcher.lock"
    with DispatcherLock(path):
        blocked = try_lock_in_fresh_process(path)
        assert blocked.returncode == 73, blocked.stderr
    crashed = try_lock_in_fresh_process(path)
    assert crashed.returncode == 0, crashed.stderr
    # The file remains, but a dead process must not leave a permanent stale lock.
    assert path.is_file()
    with DispatcherLock(path) as successor:
        assert successor.held
