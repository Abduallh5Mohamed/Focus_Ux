"""Single-dispatcher OS lock (stdlib only, Windows + POSIX).

Why: exactly one process may own face detection + extraction. The lock is held
for the lifetime of that dispatcher. A second server process (or a careless
restart) must NOT recover/rewrite live PROCESSING jobs, so it fails to acquire
the lock and stays a read-only API.

Implementation:
  * POSIX: ``fcntl.flock(LOCK_EX | LOCK_NB)`` on a lock file.
  * Windows: ``msvcrt.locking(LK_NBLCK)`` on the first byte of the lock file.
  * A module-level registry additionally makes a second acquire in the SAME
    process fail immediately (two dispatchers in one test process).

The OS lock is advisory and released automatically when the process exits, so
a crashed dispatcher does not leave a permanent stale lock; the next startup
acquires it and performs the worker's ``recover_interrupted()`` pass.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

_REGISTRY_GUARD = threading.Lock()
_HELD: set[str] = set()


class DispatcherLock:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._key = os.path.normcase(str(self.path.resolve()))
        self._handle = None
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self) -> bool:
        with _REGISTRY_GUARD:
            if self._key in _HELD:
                return False
            _HELD.add(self._key)
        try:
            self._open_and_lock()
        except Exception:
            with _REGISTRY_GUARD:
                _HELD.discard(self._key)
            return False
        self._held = True
        return True

    def _open_and_lock(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            handle.close()
            raise
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            finally:
                handle.close()
        if self._held:
            self._held = False
            with _REGISTRY_GUARD:
                _HELD.discard(self._key)

    def __enter__(self) -> "DispatcherLock":
        if not self.acquire():
            raise RuntimeError("dispatcher lock is already held")
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()
