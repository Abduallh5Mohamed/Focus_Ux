"""Real decoding of MediaRecorder (WebM/Matroska) byte streams.

MediaRecorder with a timeslice emits ONE continuous stream cut at arbitrary byte
positions: only the first blob carries the EBML header and track info, and later
blobs may start in the middle of a Cluster. They are not playable alone. We
therefore keep the stream header plus the bytes since the last Cluster start and
decode ``header + tail + new bytes`` with ffmpeg, then cut the requested window.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

CLUSTER_ID = b"\x1f\x43\xb6\x75"
EBML_MAGIC = b"\x1a\x45\xdf\xa3"
DECODE_TIMEOUT_S = 60.0


class DecodeError(Exception):
    pass


def find_clusters(data: bytes) -> list[int]:
    found, pos = [], 0
    while True:
        pos = data.find(CLUSTER_ID, pos)
        if pos < 0:
            return found
        found.append(pos)
        pos += 4


def _read_vint(data: bytes, pos: int) -> tuple[int | None, int]:
    """Return (value or None for unknown size, next position)."""
    if pos >= len(data):
        raise ValueError("truncated vint")
    first = data[pos]
    length = 1
    mask = 0x80
    while length <= 8 and not first & mask:
        length += 1
        mask >>= 1
    if length > 8 or pos + length > len(data):
        raise ValueError("bad vint")
    value = first & (mask - 1)
    for byte in data[pos + 1:pos + length]:
        value = (value << 8) | byte
    unknown = value == (1 << (7 * length)) - 1
    return (None if unknown else value), pos + length


def cluster_timecode_ms(data: bytes, offset: int) -> int | None:
    """Timecode (ms, default 1 ms scale) of the Cluster starting at ``offset``."""
    try:
        _size, pos = _read_vint(data, offset + 4)
        if data[pos] != 0xE7:
            return None
        length, pos = _read_vint(data, pos + 1)
        if length is None or not 1 <= length <= 8:
            return None
        return int.from_bytes(data[pos:pos + length], "big")
    except (ValueError, IndexError):
        return None


def decode_window(
    webm: bytes, out_path: Path, *, start_s: float, duration_s: float,
    ffmpeg: str = "ffmpeg",
) -> None:
    """Decode ``webm`` and write the [start, start+duration) window as mp4."""
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory(dir=out_path.parent) as tmp:
        source = Path(tmp) / "in.webm"
        source.write_bytes(webm)
        target = Path(tmp) / "out.mp4"
        command = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-err_detect", "ignore_err", "-i", str(source),
            "-ss", f"{max(0.0, start_s):.3f}", "-t", f"{duration_s:.3f}",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-r", "25",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ac", "1", "-movflags", "+faststart", str(target),
        ]
        try:
            done = subprocess.run(
                command, capture_output=True, timeout=DECODE_TIMEOUT_S, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DecodeError("decoder could not run") from exc
        if done.returncode != 0 or not target.is_file() or target.stat().st_size <= 0:
            raise DecodeError("chunk could not be decoded")
        target.replace(out_path)
