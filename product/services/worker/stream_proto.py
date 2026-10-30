"""Binary framing for the continuous live stream (browser -> server -> worker -> server -> browser).

Pure stdlib so the API, the Windows worker and the tests share one definition.
A *batch* is ``MAGIC | batch_seq:u32`` followed by records
``kind:u8 | position:u64 | length:u32 | data``. Positions are explicit so a
dropped, duplicated or reordered batch is detectable instead of silently shifting audio.
"""
from __future__ import annotations

import json
import struct
from typing import Iterator

MAGIC = b"FLS1"
SAMPLE_RATE = 16000
FPS = 25

K_AUDIO = 1      # in: mic PCM16 mono 16 kHz; position = first sample index
K_FRAME = 2      # in: JPEG camera frame; position = capture time in ms
K_OUT_AUDIO = 3  # out: isolated PCM16; position = first sample index
K_JSON = 4       # control / status JSON (position unused)

_HEAD = struct.Struct("<4sI")
_REC = struct.Struct("<BQI")
MAX_BATCH_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 400


class ProtoError(ValueError):
    pass


def pack_batch(batch_seq: int, records: list[tuple[int, int, bytes]]) -> bytes:
    out = bytearray(_HEAD.pack(MAGIC, batch_seq))
    for kind, position, data in records:
        out += _REC.pack(kind, position, len(data))
        out += data
    return bytes(out)


def json_record(obj: dict, position: int = 0) -> tuple[int, int, bytes]:
    return (K_JSON, position, json.dumps(obj, separators=(",", ":")).encode())


def unpack_batch(data: bytes) -> tuple[int, list[tuple[int, int, bytes]]]:
    if len(data) < _HEAD.size or len(data) > MAX_BATCH_BYTES:
        raise ProtoError("batch size invalid")
    magic, seq = _HEAD.unpack_from(data)
    if magic != MAGIC:
        raise ProtoError("bad magic")
    pos, records = _HEAD.size, []
    while pos < len(data):
        if pos + _REC.size > len(data) or len(records) >= MAX_RECORDS:
            raise ProtoError("truncated record")
        kind, position, length = _REC.unpack_from(data, pos)
        pos += _REC.size
        if kind not in (K_AUDIO, K_FRAME, K_OUT_AUDIO, K_JSON) or pos + length > len(data):
            raise ProtoError("bad record")
        records.append((kind, position, data[pos:pos + length]))
        pos += length
    return seq, records


def iter_json(records) -> Iterator[dict]:
    for kind, _p, data in records:
        if kind == K_JSON:
            try:
                value = json.loads(data)
            except ValueError as exc:
                raise ProtoError("bad json record") from exc
            if isinstance(value, dict):
                yield value
