"""Mix analysis cache and MP4 export jobs.

Exports live under ``jobs/<job_id>/exports/`` so the video's existing deletion
flow (``Storage.remove_job_dir``) removes them. Export state is in memory: a
restart forgets in-flight renders (the web client simply asks again).
"""
from __future__ import annotations

import logging
import subprocess
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import mix
from .mix import Alignment, MixError, MixSettings

logger = logging.getLogger("focus_api.mix")

_CACHE_SIZE = 4
_MAX_EXPORTS_PER_JOB = 5
_MUX_TIMEOUT_S = 120.0


@dataclass
class ExportRecord:
    export_id: str
    job_id: str
    status: str = "rendering"  # rendering | ready | failed
    path: Path | None = None
    error_code: str | None = None
    error_message: str | None = None
    cancelled: bool = False
    process: subprocess.Popen | None = field(default=None, repr=False)


class MixService:
    def __init__(self, ffmpeg: str = "ffmpeg"):
        self.ffmpeg = ffmpeg
        self._cache: "OrderedDict[tuple, Alignment]" = OrderedDict()
        self._cache_lock = threading.Lock()
        self._exports: dict[str, ExportRecord] = {}
        self._exports_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="focus-export")
        self._futures: dict[str, object] = {}

    # -- analysis ------------------------------------------------------------
    def analysis(self, *, job_id: str, video_path: Path, wav_path: Path,
                 offset_ms: float, duration_ms: int) -> Alignment:
        key = (job_id, video_path.stat().st_mtime_ns, wav_path.stat().st_mtime_ns, offset_ms)
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
        original = mix.decode_mono(video_path, ffmpeg=self.ffmpeg)
        if len(original) == 0:
            raise MixError("the video has no audio track", "NO_AUDIO")
        isolated = mix.decode_mono(wav_path, ffmpeg=self.ffmpeg)
        length = int(round(duration_ms * mix.WORK_RATE / 1000.0))
        original = mix.fit_length(original, length)
        result = mix.align(original, isolated, offset_ms=offset_ms)
        with self._cache_lock:
            self._cache[key] = result
            while len(self._cache) > _CACHE_SIZE:
                self._cache.popitem(last=False)
        return result

    def forget_jobs(self, job_ids: list[str]) -> None:
        wanted = set(job_ids)
        with self._cache_lock:
            for key in [k for k in self._cache if k[0] in wanted]:
                del self._cache[key]

    # -- exports -------------------------------------------------------------
    def start_export(self, *, job_id: str, video_path: Path, wav_path: Path, offset_ms: float,
                     duration_ms: int, settings: MixSettings, export_dir: Path) -> ExportRecord:
        settings = settings.validated()
        # Fail fast (and synchronously) on an unreliable residual request.
        alignment = self.analysis(job_id=job_id, video_path=video_path, wav_path=wav_path,
                                  offset_ms=offset_ms, duration_ms=duration_ms)
        if settings.others_level > 0 and not alignment.reliable:
            raise MixError("the other-voices track is unreliable for this job", "MIX_UNRELIABLE")
        record = ExportRecord(export_id=uuid.uuid4().hex, job_id=job_id)
        with self._exports_lock:
            self._prune(job_id)
            self._exports[record.export_id] = record
        self._futures[record.export_id] = self._pool.submit(
            self._render, record, alignment, settings, video_path, duration_ms, export_dir
        )
        return record

    def get_export(self, job_id: str, export_id: str) -> ExportRecord | None:
        with self._exports_lock:
            record = self._exports.get(export_id)
        if record is None or record.job_id != job_id:
            return None
        if record.status == "ready" and (record.path is None or not record.path.is_file()):
            return None
        return record

    def _prune(self, job_id: str) -> None:
        finished = [r for r in self._exports.values() if r.job_id == job_id and r.status != "rendering"]
        for record in finished[: max(0, len(finished) - _MAX_EXPORTS_PER_JOB + 1)]:
            if record.path is not None:
                record.path.unlink(missing_ok=True)
            del self._exports[record.export_id]

    def cancel_jobs(self, job_ids: list[str], timeout: float = 15.0) -> None:
        """Stop renders for these jobs and wait, so directory removal is safe."""
        wanted = set(job_ids)
        with self._exports_lock:
            records = [r for r in self._exports.values() if r.job_id in wanted]
            for record in records:
                record.cancelled = True
                proc = record.process
                if proc is not None and proc.poll() is None:
                    proc.kill()
        for record in records:
            future = self._futures.get(record.export_id)
            if future is not None:
                try:
                    future.result(timeout=timeout)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 - render errors are recorded on the record
                    pass
        with self._exports_lock:
            for record in records:
                self._exports.pop(record.export_id, None)
                self._futures.pop(record.export_id, None)
        self.forget_jobs(job_ids)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _render(self, record: ExportRecord, alignment: Alignment, settings: MixSettings,
                video_path: Path, duration_ms: int, export_dir: Path) -> None:
        wav_tmp = export_dir / f"{record.export_id}.mix.wav"
        out_tmp = export_dir / f"{record.export_id}.partial.mp4"
        final = export_dir / f"{record.export_id}.mp4"
        try:
            if record.cancelled:
                raise MixError("export cancelled", "CANCELLED")
            export_dir.mkdir(parents=True, exist_ok=True)
            mixed = mix.render_mix(alignment, settings)
            wav_tmp.write_bytes(mix.to_float_wav(mixed))
            command = [
                self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
                "-i", str(video_path), "-i", str(wav_tmp),
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", str(mix.WORK_RATE),
                "-t", f"{duration_ms / 1000.0:.3f}", "-movflags", "+faststart", str(out_tmp),
            ]
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            record.process = proc
            try:
                _, stderr = proc.communicate(timeout=_MUX_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise MixError("export timed out") from None
            if record.cancelled:
                raise MixError("export cancelled", "CANCELLED")
            if proc.returncode != 0 or not out_tmp.is_file() or out_tmp.stat().st_size <= 0:
                logger.warning("export ffmpeg failed: %s", stderr.decode("utf-8", "replace")[-500:])
                raise MixError(
                    "the video picture could not be copied into an MP4 unchanged",
                    "EXPORT_UNSUPPORTED",
                )
            out_tmp.replace(final)
            record.path = final
            record.status = "ready"
        except MixError as exc:
            record.status, record.error_code, record.error_message = "failed", exc.code, exc.message
        except Exception:  # noqa: BLE001
            logger.exception("export failed")
            record.status, record.error_code = "failed", "PROCESSING_FAILED"
            record.error_message = "export failed"
        finally:
            record.process = None
            wav_tmp.unlink(missing_ok=True)
            out_tmp.unlink(missing_ok=True)
            if record.status == "failed" or record.cancelled:
                final.unlink(missing_ok=True)
