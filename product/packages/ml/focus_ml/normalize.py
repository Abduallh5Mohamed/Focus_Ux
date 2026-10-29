"""Input normalization (Round 2): canonicalize arbitrary uploads to

- 25 fps CF video (H.264 + AAC 16 kHz mono in the container), and
- a separate 16 kHz mono PCM WAV timeline-equivalent audio file,

written ONLY into a caller-supplied job-specific directory. The upload and
any reference material are never modified or overwritten, and nothing is
written near the legacy tree (callers must not pass one in).

Design notes
- Timeline-preserving: the ``fps`` filter duplicates/drops frames without
  re-timing the audio, so duration is preserved (and verified after encode;
  a mismatch beyond a tolerance is reported in ``warnings``).
- Audio samples are produced with the EXACT ffmpeg invocation shape the
  legacy engine uses for its mix (16k, mono, pcm_s16le), so the normalized
  job stays engine-compatible.
- No media parsing libraries at import time: probing parses the ``ffmpeg -i``
  stderr text with pure functions so command construction and parsing are
  CPU-testable without running any binary.
"""
from __future__ import annotations

import dataclasses
import os
import re
import subprocess
from typing import Callable, Optional

_LIMIT_MESSAGE = "the media exceeds the upload limits (max {seconds:g} s / {megabytes:d} MB)"

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_FPS_PLAIN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
_FPS_RATIONAL_RE = re.compile(r"(\d+)/(\d+)\s*tps")
_AUDIO_RATE_RE = re.compile(r"(\d+)\s*Hz")

DURATION_MATCH_TOLERANCE_S = 0.75


@dataclasses.dataclass
class NormalizedMedia:
    """Canonical inputs for the engine; paths are worker-owned job artifacts."""

    video_path: str
    audio_path: Optional[str]
    duration_ms: int
    source_duration_ms: int
    source_fps: Optional[float]
    has_audio: bool
    warnings: list[str] = dataclasses.field(default_factory=list)


def parse_duration_seconds(text: str) -> Optional[float]:
    match = _DURATION_RE.search(text or "")
    if not match:
        return None
    hours, minutes, seconds = float(match.group(1)), int(match.group(2)), float(match.group(3))
    return hours * 3600.0 + minutes * 60.0 + seconds


def parse_fps(text: str) -> Optional[float]:
    """Prefer Stream-side ``fps`` values ("25 fps,"; "29.97 fps,"), then the
    rational "30000/1001 tps" form used for 29.97."""
    text = text or ""
    match = _FPS_PLAIN_RE.search(text)
    if match:
        return float(match.group(1))
    match = _FPS_RATIONAL_RE.search(text)
    if match:
        numerator, denominator = float(match.group(1)), float(match.group(2))
        if denominator > 0:
            return numerator / denominator
    return None


def parse_audio_sample_rate(text: str) -> Optional[int]:
    match = _AUDIO_RATE_RE.search(text or "")
    return int(match.group(1)) if match else None


def default_ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg  # lazy execution-time import

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def probe_stream(video_path: str, ffmpeg_exe: Optional[str] = None) -> dict:
    """Probe source duration (s), fps and sample rate by parsing ``ffmpeg -i``
    stderr (ffmpeg exits nonzero without an output file, which is expected).
    Raises MediaError when the media is undecodable."""
    ff = ffmpeg_exe or default_ffmpeg_exe()
    completed = subprocess.run(
        [ff, "-hide_banner", "-i", video_path], capture_output=True, text=True
    )
    stderr = completed.stderr or ""
    duration_s = parse_duration_seconds(stderr)
    if duration_s is None:
        raise ValueError(
            "media could not be probed (undecodable or not media)",
            # value never surfaces to users; callers wrap decisions on it
        )
    probe = {
        "duration_s": duration_s,
        "fps": parse_fps(stderr),
        "sample_rate": parse_audio_sample_rate(stderr),
        "size_bytes": os.path.getsize(video_path) if os.path.isfile(video_path) else 0,
    }
    return probe


def build_normalize_command(
    ffmpeg_exe: str,
    src: str,
    out_video: str,
    out_audio: str,
    fps: int = 25,
) -> tuple[list[str], list[str]]:
    """Two invocations: (1) 25 fps H.264 video with AAC 16 k mono audio kept
    in the container (the engine timeline single source of truth), (2) the
    legacy-shaped 16k mono PCM wav for the engine mix. Returns
    (video_command, audio_command) as argument lists (no shell)."""
    video_cmd = [
        ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
        "-map", "0:v:0",
        "-filter:v", f"fps={fps}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-map", "0:a:0?", "-c:a", "aac", "-ar", "16000", "-ac", "1", "-b:a", "128k",
        out_video,
    ]
    audio_cmd = [
        ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
        "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", out_audio,
    ]
    return video_cmd, audio_cmd


def _run_runner_default(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _is_same_file(path_a: str, path_b: str) -> bool:
    try:
        return os.path.abspath(path_a) == os.path.abspath(path_b)
    except Exception:
        return False


def normalize_input(
    video_path: str,
    job_dir: str,
    config=None,
    on_progress: Callable[[str, float], None] | None = None,
    *,
    ffmpeg_exe: Optional[str] = None,
    prober=None,
    runner=None,
) -> NormalizedMedia:
    """Normalize ANY upload into 25 fps video + 16k mono audio inside
    ``job_dir`` (created on demand). Refuses (LimitError) before any encode
    when the source exceeds the clip limits (refuse_limit) or when an output
    path would collide with the source file itself.

    ``prober`` and ``runner`` are injectable seams for tests; production
    callers omit them and real ffmpeg probes/encodes run."""
    cfg = config if config is not None else _default_config()
    from focus_ml.errors import LimitError, MediaError, ProcessingError  # local

    if not os.path.isfile(video_path):
        raise MediaError("media file not found", detail=f"missing: {video_path!r}")
    ff = ffmpeg_exe or default_ffmpeg_exe()
    prober = prober or probe_stream
    runner = runner or _run_runner_default

    warnings: list[str] = []
    try:
        info = prober(video_path, ff)
    except ValueError as exc:
        raise MediaError(
            "the uploaded media could not be read",
            detail=f"probe failed: {type(exc).__name__}: {exc}",
        ) from exc
    duration_s = float(info.get("duration_s") or 0.0)
    source_fps = info.get("fps")
    size_mb = info.get("size_bytes", 0) / (1024 * 1024)
    if duration_s > cfg.max_video_seconds + 1e-6:
        raise LimitError(_LIMIT_MESSAGE.format(
            seconds=cfg.max_video_seconds, megabytes=cfg.max_upload_mb
        ) + f" (duration {duration_s:.2f} s)")
    if size_mb > cfg.max_upload_mb:
        raise LimitError(_LIMIT_MESSAGE.format(
            seconds=cfg.max_video_seconds, megabytes=cfg.max_upload_mb
        ) + f" (size {size_mb:.1f} MB)")

    os.makedirs(str(job_dir), exist_ok=True)
    out_video = os.path.join(str(job_dir), "normalized_video.mp4")
    out_audio = os.path.join(str(job_dir), "normalized_audio.wav")
    for out in (out_video, out_audio):
        if _is_same_file(out, video_path):
            raise MediaError(
                "the job output directory collides with the upload itself",
                detail=f"output would overwrite source: {out!r}",
            )

    if on_progress is not None:
        on_progress("normalizing", 0.0)
    video_cmd, audio_cmd = build_normalize_command(ff, video_path, out_video, out_audio)
    video_run = runner(video_cmd)
    if video_run.returncode != 0:
        raise ProcessingError(
            "video normalization failed; nothing was produced for this job",
            detail=f"ffmpeg: {(video_run.stderr or '').strip()}",
        )
    audio_run = runner(audio_cmd)
    has_audio = audio_run.returncode == 0 and os.path.isfile(out_audio) and os.path.getsize(out_audio) > 0
    if not has_audio:
        audio_stderr = (audio_run.stderr or "").lower()
        warnings.append(
            "the source media carries no extractable audio; the separation "
            "stage cannot run on this job"
        )
        out_audio_final: Optional[str] = None
        if "invalid data" in audio_stderr:
            raise MediaError(
                "the uploaded media is invalid or corrupt",
                detail=f"ffmpeg: {audio_stderr.strip()}",
            )

    if on_progress is not None:
        on_progress("normalizing", 1.0)

    # Timeline verification on the actual output, not just the source claim.
    try:
        out_info = prober(out_video, ff)
    except ValueError:
        out_info = {}
    out_duration = float(out_info.get("duration_s") or 0.0)
    if out_duration and abs(out_duration - duration_s) > DURATION_MATCH_TOLERANCE_S:
        warnings.append(
            f"normalized video duration {out_duration:.2f} s differs from the "
            f"source {duration_s:.2f} s beyond tolerance"
        )

    if source_fps is not None and abs(source_fps - cfg.fps) > 0.02:
        warnings.append(
            f"source ran at {source_fps:.2f} fps and was resampled to "
            f"{cfg.fps} fps (frames dropped/duplicated on the original "
            f"timeline to preserve duration)"
        )
    source_rate = info.get("sample_rate")
    if source_rate is not None and source_rate != cfg.sample_rate:
        warnings.append(
            f"source audio ran at {source_rate} Hz and was resampled to "
            f"{cfg.sample_rate} Hz mono"
        )

    return NormalizedMedia(
        video_path=out_video,
        audio_path=out_audio_final if not has_audio else out_audio,
        duration_ms=int(round(duration_s * 1000.0)),
        source_duration_ms=int(round(duration_s * 1000.0)),
        source_fps=source_fps,
        has_audio=has_audio,
        warnings=warnings,
    )


def _default_config():
    from focus_ml.config import AdapterConfig  # lazy

    return AdapterConfig.from_env()
