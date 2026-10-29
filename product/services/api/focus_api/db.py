"""SQLite persistence, including the worker's ``JobRepository`` boundary.

Claim safety (ROUND2_INTEGRATION_DECISIONS #4): the worker is the sole
performer of QUEUED -> PROCESSING. ``save()`` therefore implements a
transactional compare-and-set:

  * the ``Job`` handed out by :meth:`SqliteRepository.get` carries the revision
    and status that were persisted at read time;
  * when a read-queued job is saved with status ``processing``, the UPDATE has
    the literal precondition ``status='queued'`` (plus the revision);
  * ``rowcount != 1`` raises :class:`ClaimConflict` instead of silently running
    the same job twice.

JOURNAL: WAL + ``BEGIN IMMEDIATE`` for write transactions, so the CAS is atomic
across the API thread pool and the dispatcher thread (and across processes if a
second one ever wrote, though the OS lock prevents two dispatchers).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from services.worker.interfaces import TargetRunResult  # noqa: F401  (re-exported docs)
from services.worker.models import (
    AudioStatus,
    ErrorPayload,
    Job,
    JobStage,
    JobStatus,
    TranscriptSegment,
    TranscriptStatus,
)


class JobNotFound(KeyError):
    pass


class RepositoryConflict(RuntimeError):
    """Optimistic concurrency conflict (stale revision)."""


class ClaimConflict(RuntimeError):
    """Another worker already moved this job out of QUEUED."""


@dataclass
class VideoRecord:
    video_id: str
    session_id: str
    original_path: Optional[str]
    canonical_path: Optional[str]
    mime_type: str
    size_bytes: int
    duration_ms: int
    width: int
    height: int
    fps: Optional[float]
    faces_status: str
    faces_error_code: Optional[str]
    faces_error_message: Optional[str]
    faces_error_retryable: bool
    created_at: float
    deleted_at: Optional[float]

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None


@dataclass
class FaceRecord:
    video_id: str
    face_id: str
    timestamp_ms: int
    bbox: tuple[int, int, int, int]
    frame_size: tuple[int, int]
    thumbnail_path: Optional[str]
    thumbnail_mime: Optional[str]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    original_path TEXT,
    canonical_path TEXT,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    fps REAL,
    faces_status TEXT NOT NULL DEFAULT 'pending',
    faces_error_code TEXT,
    faces_error_message TEXT,
    faces_error_retryable INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    deleted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_videos_session ON videos(session_id);
CREATE INDEX IF NOT EXISTS idx_videos_faces ON videos(faces_status);

CREATE TABLE IF NOT EXISTS faces (
    video_id TEXT NOT NULL,
    face_id TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    bbox_x INTEGER NOT NULL,
    bbox_y INTEGER NOT NULL,
    bbox_w INTEGER NOT NULL,
    bbox_h INTEGER NOT NULL,
    frame_w INTEGER NOT NULL,
    frame_h INTEGER NOT NULL,
    thumbnail_path TEXT,
    thumbnail_mime TEXT,
    PRIMARY KEY (video_id, face_id),
    FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    face_id TEXT,
    client_request_id TEXT,
    video_path TEXT,
    job_dir TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'validating',
    audio_status TEXT NOT NULL DEFAULT 'pending',
    transcript_status TEXT NOT NULL DEFAULT 'pending',
    wav_path TEXT,
    duration_ms INTEGER,
    source_offset_ms INTEGER NOT NULL DEFAULT 0,
    audio_warnings TEXT NOT NULL DEFAULT '[]',
    transcript_segments TEXT NOT NULL DEFAULT '[]',
    error_code TEXT,
    error_message TEXT,
    error_retryable INTEGER NOT NULL DEFAULT 0,
    queue_position INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency
    ON jobs(video_id, face_id, client_request_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_video ON jobs(video_id);
"""


class SqliteRepository:
    """Persistent repository shared by the API routes and the worker."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.path, timeout=30.0, isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=10000")
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- sessions ------------------------------------------------------------
    def create_session(self, token_hash: str, session_id: str, now: float | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions(token_hash, session_id, created_at) VALUES(?,?,?)",
                (token_hash, session_id, time.time() if now is None else now),
            )

    def get_session_id(self, token_hash: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id FROM sessions WHERE token_hash=?", (token_hash,)
            ).fetchone()
        return row["session_id"] if row else None

    # -- videos --------------------------------------------------------------
    def create_video(self, video: VideoRecord) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO videos(
                    video_id, session_id, original_path, canonical_path, mime_type,
                    size_bytes, duration_ms, width, height, fps, faces_status,
                    faces_error_code, faces_error_message, faces_error_retryable,
                    created_at, deleted_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    video.video_id,
                    video.session_id,
                    video.original_path,
                    video.canonical_path,
                    video.mime_type,
                    video.size_bytes,
                    video.duration_ms,
                    video.width,
                    video.height,
                    video.fps,
                    video.faces_status,
                    video.faces_error_code,
                    video.faces_error_message,
                    1 if video.faces_error_retryable else 0,
                    video.created_at,
                    video.deleted_at,
                ),
            )

    def get_video(self, video_id: str) -> Optional[VideoRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM videos WHERE video_id=?", (video_id,)
            ).fetchone()
        return _row_to_video(row) if row else None

    def set_faces_status(
        self,
        video_id: str,
        status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        retryable: bool = False,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE videos SET faces_status=?, faces_error_code=?,
                    faces_error_message=?, faces_error_retryable=?
                WHERE video_id=?
                """,
                (status, error_code, error_message, 1 if retryable else 0, video_id),
            )

    def replace_faces(self, video_id: str, faces: list[FaceRecord]) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("DELETE FROM faces WHERE video_id=?", (video_id,))
                self._conn.executemany(
                    """
                    INSERT INTO faces(
                        video_id, face_id, timestamp_ms, bbox_x, bbox_y, bbox_w,
                        bbox_h, frame_w, frame_h, thumbnail_path, thumbnail_mime
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        (
                            f.video_id,
                            f.face_id,
                            f.timestamp_ms,
                            f.bbox[0],
                            f.bbox[1],
                            f.bbox[2],
                            f.bbox[3],
                            f.frame_size[0],
                            f.frame_size[1],
                            f.thumbnail_path,
                            f.thumbnail_mime,
                        )
                        for f in faces
                    ],
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def get_faces(self, video_id: str) -> list[FaceRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM faces WHERE video_id=? ORDER BY rowid", (video_id,)
            ).fetchall()
        return [_row_to_face(row) for row in rows]

    def get_face(self, video_id: str, face_id: str) -> Optional[FaceRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM faces WHERE video_id=? AND face_id=?",
                (video_id, face_id),
            ).fetchone()
        return _row_to_face(row) if row else None

    def mark_video_deleted(self, video_id: str, now: float | None = None) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE videos SET deleted_at=COALESCE(deleted_at, ?) WHERE video_id=?",
                (time.time() if now is None else now, video_id),
            )
            return cur.rowcount == 1

    def clear_media_paths(self, video_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE videos SET original_path=NULL, canonical_path=NULL WHERE video_id=?",
                (video_id,),
            )
            self._conn.execute(
                "UPDATE faces SET thumbnail_path=NULL, thumbnail_mime=NULL WHERE video_id=?",
                (video_id,),
            )

    def pending_face_videos(self) -> list[tuple[str, float]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT video_id, created_at FROM videos "
                "WHERE faces_status='pending' AND deleted_at IS NULL "
                "ORDER BY created_at, video_id"
            ).fetchall()
        return [(row["video_id"], row["created_at"]) for row in rows]

    def all_videos(self) -> list[VideoRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM videos ORDER BY created_at, video_id"
            ).fetchall()
        return [_row_to_video(row) for row in rows]

    # -- worker JobRepository protocol --------------------------------------
    def get(self, job_id: str) -> Job:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return _row_to_job(row)

    def find_job(self, job_id: str) -> Optional[Job]:
        try:
            return self.get(job_id)
        except JobNotFound:
            return None

    def all(self) -> list[Job]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY created_at, job_id"
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def save(self, job: Job) -> None:
        values = _job_values(job)
        revision = getattr(job, "_db_revision", None)
        persisted_status = getattr(job, "_persisted_status", None)
        incoming_status = job.status.value
        claim = persisted_status == "queued" and incoming_status == "processing"
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT status, revision FROM jobs WHERE job_id=?", (job.job_id,)
                ).fetchone()
                if row is None:
                    raise JobNotFound(job.job_id)
                if revision is None:
                    revision = row["revision"]
                sql = (
                    "UPDATE jobs SET video_id=?, face_id=?, client_request_id=?, "
                    "video_path=?, job_dir=?, status=?, stage=?, audio_status=?, "
                    "transcript_status=?, wav_path=?, duration_ms=?, source_offset_ms=?, "
                    "audio_warnings=?, transcript_segments=?, error_code=?, "
                    "error_message=?, error_retryable=?, queue_position=?, updated_at=?, "
                    "revision=revision+1 WHERE job_id=? AND revision=?"
                )
                params = values + (job.job_id, revision)
                if claim:
                    sql += " AND status='queued'"
                cur = self._conn.execute(sql, params)
                if cur.rowcount != 1:
                    self._conn.execute("ROLLBACK")
                    if claim:
                        raise ClaimConflict(
                            f"job {job.job_id!r} is no longer queued; another "
                            f"worker owns the claim"
                        )
                    raise RepositoryConflict(
                        f"job {job.job_id!r} changed concurrently (stale revision)"
                    )
                self._conn.execute("COMMIT")
            except Exception:
                try:
                    if self._conn.in_transaction:
                        self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
        job._db_revision = int(revision) + 1
        job._persisted_status = incoming_status

    # -- jobs (API side) -----------------------------------------------------
    def create_job(self, job: Job, now: float | None = None) -> bool:
        values = _job_values(job)
        stamp = time.time() if now is None else now
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO jobs(
                    video_id, face_id, client_request_id, video_path, job_dir,
                    status, stage, audio_status, transcript_status, wav_path,
                    duration_ms, source_offset_ms, audio_warnings,
                    transcript_segments, error_code, error_message,
                    error_retryable, queue_position, updated_at, job_id,
                    created_at, revision
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                """,
                values + (job.job_id, stamp),
            )
            return cur.rowcount == 1

    def find_job_id(
        self, video_id: str, face_id: str, client_request_id: str
    ) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT job_id FROM jobs WHERE video_id=? AND face_id=? AND client_request_id=?",
                (video_id, face_id, client_request_id),
            ).fetchone()
        return row["job_id"] if row else None

    def queued_jobs(self) -> list[tuple[str, float]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT job_id, created_at FROM jobs WHERE status='queued' "
                "ORDER BY created_at, job_id"
            ).fetchall()
        return [(row["job_id"], row["created_at"]) for row in rows]

    def queued_position(self, job_id: str) -> int:
        with self._lock:
            rows = self._conn.execute(
                "SELECT job_id FROM jobs WHERE status='queued' "
                "ORDER BY created_at, job_id"
            ).fetchall()
        for index, row in enumerate(rows):
            if row["job_id"] == job_id:
                return index
        return 0

    def jobs_for_video(self, video_id: str) -> list[Job]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE video_id=? ORDER BY created_at, job_id",
                (video_id,),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def cancel_queued_for_video(self, video_id: str, now: float | None = None) -> list[str]:
        stamp = time.time() if now is None else now
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self._conn.execute(
                    "SELECT job_id FROM jobs WHERE video_id=? AND status='queued'",
                    (video_id,),
                ).fetchall()
                ids = [row["job_id"] for row in rows]
                if ids:
                    self._conn.executemany(
                        "UPDATE jobs SET status='cancelled', updated_at=?, "
                        "revision=revision+1 WHERE job_id=?",
                        [(stamp, job_id) for job_id in ids],
                    )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return ids

    def job_status(self, job_id: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return row["status"] if row else None

    def count_jobs(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"])


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def _row_to_video(row: sqlite3.Row) -> VideoRecord:
    return VideoRecord(
        video_id=row["video_id"],
        session_id=row["session_id"],
        original_path=row["original_path"],
        canonical_path=row["canonical_path"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"],
        duration_ms=row["duration_ms"],
        width=row["width"],
        height=row["height"],
        fps=row["fps"],
        faces_status=row["faces_status"],
        faces_error_code=row["faces_error_code"],
        faces_error_message=row["faces_error_message"],
        faces_error_retryable=bool(row["faces_error_retryable"]),
        created_at=row["created_at"],
        deleted_at=row["deleted_at"],
    )


def _row_to_face(row: sqlite3.Row) -> FaceRecord:
    return FaceRecord(
        video_id=row["video_id"],
        face_id=row["face_id"],
        timestamp_ms=row["timestamp_ms"],
        bbox=(row["bbox_x"], row["bbox_y"], row["bbox_w"], row["bbox_h"]),
        frame_size=(row["frame_w"], row["frame_h"]),
        thumbnail_path=row["thumbnail_path"],
        thumbnail_mime=row["thumbnail_mime"],
    )


def _row_to_job(row: sqlite3.Row) -> Job:
    warnings = json.loads(row["audio_warnings"] or "[]")
    raw_segments = json.loads(row["transcript_segments"] or "[]")
    segments = [
        TranscriptSegment(
            id=int(seg["id"]),
            start_ms=int(seg["start_ms"]),
            end_ms=int(seg["end_ms"]),
            text=str(seg["text"]),
        )
        for seg in raw_segments
    ]
    error = None
    if row["error_code"]:
        error = ErrorPayload(
            row["error_code"], row["error_message"] or "", bool(row["error_retryable"])
        )
    job = Job(
        job_id=row["job_id"],
        video_id=row["video_id"],
        face_id=row["face_id"],
        client_request_id=row["client_request_id"],
        video_path=row["video_path"],
        job_dir=row["job_dir"],
        status=JobStatus(row["status"]),
        stage=JobStage(row["stage"]),
        audio_status=AudioStatus(row["audio_status"]),
        transcript_status=TranscriptStatus(row["transcript_status"]),
        wav_path=row["wav_path"],
        duration_ms=row["duration_ms"],
        source_offset_ms=row["source_offset_ms"] or 0,
        audio_warnings=list(warnings),
        transcript_segments=segments,
        error=error,
        queue_position=row["queue_position"] or 0,
    )
    # Revision/status are transport metadata for the compare-and-set save(); they
    # are copied with the Job dataclass and never exposed on the wire.
    job._db_revision = int(row["revision"])
    job._persisted_status = row["status"]
    return job


def _job_values(job: Job) -> tuple:
    """Column order for INSERT/UPDATE shared helpers (excludes created_at/revision)."""
    error = job.error
    segments = [
        {
            "id": seg.id,
            "start_ms": seg.start_ms,
            "end_ms": seg.end_ms,
            "text": seg.text,
        }
        for seg in job.transcript_segments
    ]
    return (
        job.video_id,
        job.face_id,
        job.client_request_id,
        job.video_path,
        job.job_dir,
        job.status.value,
        job.stage.value,
        job.audio_status.value,
        job.transcript_status.value,
        job.wav_path,
        job.duration_ms,
        job.source_offset_ms,
        json.dumps(list(job.audio_warnings)),
        json.dumps(segments),
        error.code if error else None,
        error.message if error else None,
        1 if error and error.retryable else 0,
        job.queue_position,
        time.time(),
    )
