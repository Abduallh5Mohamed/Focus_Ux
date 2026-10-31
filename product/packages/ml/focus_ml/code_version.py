"""Fingerprint of the worker-relevant source (focus_ml top level, voice/, overlap/).

The website reports it at the worker handshake and the Windows worker compares it with its own, so a
worker ZIP or checkout that differs from the running backend is refused with a clear message instead of
failing on a changed request or result format. Line endings are normalised (a ZIP may be extracted with
CRLF). Standard library only."""
from __future__ import annotations

import hashlib
from pathlib import Path

PACKAGE_DIRS = ("", "voice", "overlap")
# Bump when the isolate task payload or the routing result format changes incompatibly.
ISOLATE_CONTRACT = 2


def code_version(root: Path | None = None) -> str:
    base = Path(root) if root else Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for sub in PACKAGE_DIRS:
        for path in sorted((base / sub).glob("*.py")):
            digest.update(f"{sub}/{path.name}\0".encode())
            digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:16]
