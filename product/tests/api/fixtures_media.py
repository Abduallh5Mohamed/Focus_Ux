"""Minimal, metadata-only ISO BMFF fixtures for upload/probe tests.

These are not playable videos; the API only needs container metadata to enforce
duration/size limits and to report mime/width/height. Real decoding is the ML
side's job and is never done in the API process.
"""
from __future__ import annotations

import struct

_IDENTITY_MATRIX = (0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


def _full_box(box_type: bytes, version: int, flags: int, payload: bytes) -> bytes:
    return _box(box_type, bytes([version]) + flags.to_bytes(3, "big") + payload)


def _matrix_bytes() -> bytes:
    return struct.pack(">9I", *_IDENTITY_MATRIX)


def make_mvhd(duration_ms: int, timescale: int = 1000) -> bytes:
    payload = (
        struct.pack(">IIII", 0, 0, timescale, duration_ms)
        + struct.pack(">I", 0x00010000)  # rate 1.0
        + struct.pack(">H", 0x0100)  # volume 1.0
        + b"\x00\x00"
        + b"\x00" * 8
        + _matrix_bytes()
        + b"\x00" * 24
        + struct.pack(">I", 2)
    )
    return _full_box(b"mvhd", 0, 0, payload)


def make_tkhd(duration_ms: int, width: int, height: int) -> bytes:
    payload = (
        struct.pack(">IIIII", 0, 0, 1, 0, duration_ms)
        + b"\x00" * 8
        + struct.pack(">HHHH", 0, 0, 0, 0)
        + _matrix_bytes()
        + struct.pack(">II", width << 16, height << 16)
    )
    return _full_box(b"tkhd", 0, 0, payload)


def make_mp4_bytes(
    duration_ms: int = 1000,
    width: int = 640,
    height: int = 360,
    brand: bytes = b"isom",
) -> bytes:
    ftyp = _box(
        b"ftyp",
        brand + struct.pack(">I", 0x200) + b"isom" + b"mp41",
    )
    moov = _box(
        b"moov",
        make_mvhd(duration_ms) + _box(b"trak", make_tkhd(duration_ms, width, height)),
    )
    return ftyp + moov + _box(b"mdat", b"\x00" * 8)
