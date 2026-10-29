"""Cross-process upload leases, released by the OS even after abrupt exit."""
from __future__ import annotations

import errno
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(path: Path, *, blocking: bool = True):
    """Lock a stable sidecar, not the media being renamed or deleted.

    Callers serialize sidecar creation/removal with a persistent directory gate.
    Never unlink that gate: locking different inodes would defeat exclusion.
    """
    with open(path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(
                    handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1
                )
            except OSError as exc:
                if not blocking and exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise BlockingIOError(exc.errno, "upload is owned", str(path)) from exc
                raise
        else:
            import fcntl

            fcntl.flock(
                handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            )
        try:
            yield
        finally:
            # Closing the handle also unlocks if explicit unlocking fails.
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
