"""App-managed storage layout.

Default root: ``A:/Focus_Ux/runtime/round2/api`` (configurable). Nothing is
written under ``A:/focus`` or any original/legacy asset location.

Layout::

    <root>/media/<video_id><ext>          canonical uploaded video
    <root>/thumbs/<video_id>/<face_id>.<ext>
    <root>/jobs/<job_id>/                 worker-owned artifacts (wav, mix)
    <root>/tmp/<random>.upload            in-flight uploads
    <root>/focus.sqlite3                  metadata
    <root>/dispatcher.lock                OS lock
"""
from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from .config import Settings

logger = logging.getLogger("focus_api.storage")

VIDEO_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
}
EXT_MIME = {ext: mime for mime, ext in VIDEO_EXTENSIONS.items()}
THUMB_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png"}


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings

    # -- lifecycle -----------------------------------------------------------
    def ensure(self) -> None:
        for directory in (
            self.settings.storage_root,
            self.settings.media_dir,
            self.settings.jobs_dir,
            self.settings.thumbs_dir,
            self.settings.tmp_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.cleanup_stale_temp()

    def cleanup_stale_temp(self) -> list[str]:
        """Remove stale uploads; log failures and leave them for a later retry."""
        removed: list[str] = []
        cutoff = time.time() - self.settings.cleanup_temp_max_age_s
        if not self.settings.tmp_dir.is_dir():
            return removed
        for entry in self.settings.tmp_dir.glob("*.upload"):
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    removed.append(str(entry))
            except FileNotFoundError:
                # Another cleanup or the upload itself may have moved the file.
                continue
            except OSError:
                logger.warning(
                    "Temporary upload cleanup failed for %s; retained for a later retry",
                    entry,
                    exc_info=True,
                )
        return removed

    # -- paths ---------------------------------------------------------------
    def new_temp_path(self) -> Path:
        self.settings.tmp_dir.mkdir(parents=True, exist_ok=True)
        return self.settings.tmp_dir / f"{uuid.uuid4().hex}.upload"

    def media_path(self, video_id: str, extension: str) -> Path:
        ext = extension if extension.startswith(".") else f".{extension}"
        return self.settings.media_dir / f"{_safe(video_id)}{ext.lower()}"

    def find_media_path(self, video_id: str) -> Path | None:
        prefix = _safe(video_id)
        for ext in sorted(set(VIDEO_EXTENSIONS.values())):
            candidate = self.settings.media_dir / f"{prefix}{ext}"
            if candidate.is_file():
                return candidate
        return None

    def thumbnail_path(self, video_id: str, face_id: str, mime: str) -> Path:
        ext = THUMB_EXTENSIONS.get(mime, ".jpg")
        return self.settings.thumbs_dir / _safe(video_id) / f"{_safe(face_id)}{ext}"

    def job_dir(self, job_id: str) -> Path:
        return self.settings.jobs_dir / _safe(job_id)

    def is_managed(self, path: str | os.PathLike[str]) -> bool:
        try:
            resolved = Path(path).resolve()
            root = self.settings.storage_root.resolve()
            return resolved == root or root in resolved.parents
        except OSError:
            return False

    # -- deletion ------------------------------------------------------------
    def remove_media(self, video_id: str) -> list[str]:
        removed: list[str] = []
        for entry in self.settings.media_dir.glob(f"{_safe(video_id)}.*"):
            removed.append(_unlink(entry))
        thumbs = self.settings.thumbs_dir / _safe(video_id)
        removed.extend(_rmtree(thumbs))
        return [p for p in removed if p]

    def remove_job_dir(self, job_id: str) -> list[str]:
        return _rmtree(self.job_dir(job_id))


def _safe(value: str) -> str:
    """IDs are server-issued UUIDs; reject anything path-like as defense in depth."""
    text = str(value)
    if not text or any(ch not in "0123456789abcdefABCDEF-" for ch in text):
        raise ValueError("unsafe storage id")
    return text


def _unlink(path: Path) -> str:
    try:
        path.unlink()
        return str(path)
    except FileNotFoundError:
        # Already removed is success; all other failures must reach the
        # dispatcher so persisted paths remain available for a later retry.
        return ""


def _rmtree(path: Path) -> list[str]:
    removed: list[str] = []
    for child in path.rglob("*"):
        removed.append(str(child))
    try:
        shutil.rmtree(path)
    except FileNotFoundError as exc:
        # Only a missing root is an idempotent success. A missing child during
        # traversal can leave the rest of the tree behind and needs a retry.
        if exc.filename is not None and Path(exc.filename) == path:
            return []
        raise
    return removed
