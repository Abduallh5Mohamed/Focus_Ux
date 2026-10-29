"""Stdlib-only container probe for bounded uploads.

The API must enforce "max 15 s / 50 MB" before a job is created. No ffprobe or
decoder is required: we parse just enough metadata from ISO BMFF (mp4/mov) and
Matroska (webm/mkv) containers. Unknown containers are rejected as
INVALID_MEDIA, which is the safe (non-fabricated) outcome.

Limitations documented in the README:
  * WebM recorded by ``MediaRecorder`` often omits the Segment/Info/Duration
    element; such uploads are rejected until a duration can be verified.
  * AVI and arbitrary formats are not accepted (the web app only advertises
    mp4/quicktime/webm/matroska).
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass

MP4_BRANDS_QUICKTIME = (b"qt  ", b"qt\x20\x20")
WEBM_MAGIC = b"\x1a\x45\xdf\xa3"


class ProbeError(Exception):
    """User-safe probing failure (mapped to INVALID_MEDIA / LIMIT_EXCEEDED)."""

    def __init__(self, message: str, code: str = "INVALID_MEDIA"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class VideoProbe:
    mime_type: str
    duration_ms: int
    width: int = 0
    height: int = 0
    fps: float | None = None


def probe_video(path: str | os.PathLike[str]) -> VideoProbe:
    size = os.path.getsize(path)
    if size <= 0:
        raise ProbeError("the uploaded file is empty")
    with open(path, "rb") as handle:
        head = handle.read(16)
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return _probe_iso_bmff(path)
    if head.startswith(WEBM_MAGIC):
        return _probe_matroska(path)
    raise ProbeError("unsupported or corrupt video container")


# --------------------------------------------------------------------------
# ISO BMFF (mp4 / mov)
# --------------------------------------------------------------------------

def _probe_iso_bmff(path: str | os.PathLike[str]) -> VideoProbe:
    file_size = os.path.getsize(path)
    with open(path, "rb") as handle:
        brands = _ftyp_brands(handle)
        moov = _find_box(handle, 0, file_size, b"moov", depth=0)
        if moov is None:
            raise ProbeError("mp4 container has no moov box")
        start, end = moov
        mvhd = _find_box(handle, start, end, b"mvhd", depth=0)
        if mvhd is None:
            raise ProbeError("mp4 container has no duration metadata")
        duration_ms = _read_mvhd_duration(handle, *mvhd)
        widths: list[int] = []
        heights: list[int] = []
        for tkhd in _find_all_boxes(handle, start, end, b"tkhd", depth=0):
            width, height = _read_tkhd_size(handle, *tkhd)
            if width and height:
                widths.append(width)
                heights.append(height)
        mime = "video/quicktime" if _is_quicktime(brands) else "video/mp4"
    if duration_ms <= 0:
        raise ProbeError("could not determine video duration")
    return VideoProbe(
        mime_type=mime,
        duration_ms=duration_ms,
        width=max(widths) if widths else 0,
        height=max(heights) if heights else 0,
    )


def _ftyp_brands(handle) -> list[bytes]:
    handle.seek(0)
    header = handle.read(16)
    if len(header) < 16 or header[4:8] != b"ftyp":
        return []
    box_size = struct.unpack(">I", header[:4])[0]
    payload_size = max(0, min(box_size, 4096) - 8)
    payload = header[8:] + handle.read(max(0, payload_size - 8))
    brands = [payload[0:4]]
    for offset in range(8, len(payload) - 3, 4):
        brands.append(payload[offset:offset + 4])
    return brands


def _is_quicktime(brands: list[bytes]) -> bool:
    return any(brand in MP4_BRANDS_QUICKTIME for brand in brands)


def _read_box_header(handle, offset: int, end: int):
    if offset + 8 > end:
        return None
    handle.seek(offset)
    raw = handle.read(8)
    if len(raw) < 8:
        return None
    size, box_type = struct.unpack(">I4s", raw)
    header_size = 8
    if size == 1:
        extended = handle.read(8)
        if len(extended) < 8:
            return None
        size = struct.unpack(">Q", extended)[0]
        header_size = 16
    elif size == 0:
        size = end - offset
    if size < header_size:
        return None
    box_end = min(offset + size, end)
    return box_type, offset + header_size, box_end


def _iter_boxes(handle, start: int, end: int):
    offset = start
    guard = 0
    while offset + 8 <= end and guard < 100_000:
        guard += 1
        header = _read_box_header(handle, offset, end)
        if header is None:
            break
        box_type, payload_start, box_end = header
        yield box_type, payload_start, box_end
        if box_end <= offset:
            break
        offset = box_end


def _find_box(handle, start: int, end: int, wanted: bytes, depth: int):
    for box_type, payload_start, box_end in _iter_boxes(handle, start, end):
        if box_type == wanted:
            return payload_start, box_end
        if depth < 4 and box_type in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
            found = _find_box(handle, payload_start, box_end, wanted, depth + 1)
            if found is not None:
                return found
    return None


def _find_all_boxes(handle, start: int, end: int, wanted: bytes, depth: int):
    found = []
    for box_type, payload_start, box_end in _iter_boxes(handle, start, end):
        if box_type == wanted:
            found.append((payload_start, box_end))
        elif depth < 4 and box_type in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
            found.extend(
                _find_all_boxes(handle, payload_start, box_end, wanted, depth + 1)
            )
    return found


def _read_mvhd_duration(handle, start: int, end: int) -> int:
    handle.seek(start)
    payload = handle.read(min(end - start, 120))
    if len(payload) < 20:
        raise ProbeError("mp4 duration metadata is truncated")
    version = payload[0]
    if version == 1:
        if len(payload) < 32:
            raise ProbeError("mp4 duration metadata is truncated")
        timescale = struct.unpack(">I", payload[20:24])[0]
        duration = struct.unpack(">Q", payload[24:32])[0]
    else:
        timescale = struct.unpack(">I", payload[12:16])[0]
        duration = struct.unpack(">I", payload[16:20])[0]
    if timescale <= 0:
        raise ProbeError("mp4 duration metadata is invalid")
    return int(round(duration * 1000.0 / timescale))


def _read_tkhd_size(handle, start: int, end: int) -> tuple[int, int]:
    handle.seek(start)
    payload = handle.read(min(end - start, 120))
    if not payload:
        return 0, 0
    version = payload[0]
    offset = 88 if version == 1 else 76
    if len(payload) < offset + 8:
        return 0, 0
    width_fixed, height_fixed = struct.unpack(">II", payload[offset:offset + 8])
    return int(round(width_fixed / 65536.0)), int(round(height_fixed / 65536.0))


# --------------------------------------------------------------------------
# Matroska / WebM (minimal EBML walker)
# --------------------------------------------------------------------------

_EBML = 0x1A45DFA3
_DOCTYPE = 0x4282
_SEGMENT = 0x18538067
_INFO = 0x1549A966
_TIMECODE_SCALE = 0x2AD7B1
_DURATION = 0x4489
_TRACKS = 0x1654AE6B
_TRACK_ENTRY = 0xAE
_VIDEO = 0xE0
_PIXEL_WIDTH = 0xB0
_PIXEL_HEIGHT = 0xBA

_CONTAINERS = {_EBML, _SEGMENT, _INFO, _TRACKS, _TRACK_ENTRY, _VIDEO}


def _probe_matroska(path: str | os.PathLike[str]) -> VideoProbe:
    file_size = os.path.getsize(path)
    values: dict[int, object] = {}
    with open(path, "rb") as handle:
        _walk_ebml(handle, 0, file_size, 0, values)
    doctype = values.get(_DOCTYPE)
    if isinstance(doctype, bytes):
        doctype_text = doctype.decode("ascii", "ignore").lower()
    else:
        doctype_text = "webm"
    if doctype_text == "matroska":
        mime = "video/x-matroska"
    else:
        mime = "video/webm"
    timecode_scale = values.get(_TIMECODE_SCALE)
    duration = values.get(_DURATION)
    if not isinstance(duration, float):
        raise ProbeError(
            "webm/matroska duration could not be verified; re-encode with duration metadata"
        )
    scale = int(timecode_scale) if isinstance(timecode_scale, int) else 1_000_000
    duration_ms = int(round(duration * scale / 1_000_000.0))
    if duration_ms <= 0:
        raise ProbeError("could not determine video duration")
    width = values.get(_PIXEL_WIDTH)
    height = values.get(_PIXEL_HEIGHT)
    return VideoProbe(
        mime_type=mime,
        duration_ms=duration_ms,
        width=int(width) if isinstance(width, int) else 0,
        height=int(height) if isinstance(height, int) else 0,
    )


def _read_vint(handle, *, keep_marker: bool):
    first = handle.read(1)
    if not first:
        return None, 0, False
    byte = first[0]
    if byte == 0:
        return None, 0, False
    length = 8 - byte.bit_length() + 1
    if length > 8:
        return None, 0, False
    raw = byte.to_bytes(1, "big") + handle.read(length - 1)
    if len(raw) < length:
        return None, 0, False
    if keep_marker:
        value = int.from_bytes(raw, "big")
    else:
        mask = (1 << (7 * length)) - 1
        value = int.from_bytes(raw, "big") & mask
    all_ones = (1 << (7 * length)) - 1
    unknown = not keep_marker and value == all_ones
    return value, length, unknown


def _walk_ebml(handle, start: int, end: int, depth: int, values: dict) -> None:
    if depth > 6:
        return
    offset = start
    guard = 0
    while offset < end and guard < 200_000:
        guard += 1
        handle.seek(offset)
        element_id, id_len, _ = _read_vint(handle, keep_marker=True)
        if element_id is None:
            return
        size, size_len, unknown = _read_vint(handle, keep_marker=False)
        if size is None:
            return
        payload_start = offset + id_len + size_len
        if unknown:
            payload_end = end
        else:
            payload_end = min(payload_start + size, end)
        if element_id in _CONTAINERS:
            _walk_ebml(handle, payload_start, payload_end, depth + 1, values)
        elif element_id == _DOCTYPE:
            handle.seek(payload_start)
            values[_DOCTYPE] = handle.read(payload_end - payload_start)
        elif element_id == _DURATION and _DURATION not in values:
            length = payload_end - payload_start
            handle.seek(payload_start)
            raw = handle.read(length)
            if length == 4:
                values[_DURATION] = struct.unpack(">f", raw)[0]
            elif length == 8:
                values[_DURATION] = struct.unpack(">d", raw)[0]
        elif element_id in (_TIMECODE_SCALE, _PIXEL_WIDTH, _PIXEL_HEIGHT):
            length = payload_end - payload_start
            if 0 < length <= 8:
                handle.seek(payload_start)
                raw = handle.read(length)
                values[element_id] = int.from_bytes(raw, "big")
        if payload_end <= offset:
            return
        offset = payload_end
