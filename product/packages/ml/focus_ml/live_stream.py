"""Continuous live-isolation session state for the GPU worker.

Audio and frames arrive as a stream; the chosen face is tracked frame by frame by
the *backend*; every ``hop_s`` seconds the engine runs on a sliding window of the
last ``window_s`` seconds and only the new hop is emitted, after a small
``lookahead_s`` and with a short crossfade to the previous estimate.

This module is pure logic (numpy only). The model-specific work lives behind
``StreamBackend`` so the same scheduler serves whichever engine wins the
comparison (see ``live_stream_backend.DolphinStreamBackend``).

Honest-state rules: every hop produces exactly one part with an explicit state
(``ready``, ``target_lost``, ``uncertain``, ``failed``). Gaps in the input are
zero-filled and counted; duplicated input is dropped and counted.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

import numpy as np

SAMPLES_PER_FRAME_CHECK = "sample_rate must be a multiple of fps"


@dataclass(frozen=True)
class StreamConfig:
    sample_rate: int = 16000
    fps: int = 25
    window_s: float = 4.0
    hop_s: float = 0.5
    lookahead_s: float = 0.25
    crossfade_ms: float = 20.0
    max_frame_gap: int = 125  # frames; larger gaps are held, not tracked

    def __post_init__(self) -> None:
        if self.sample_rate % self.fps:
            raise ValueError(SAMPLES_PER_FRAME_CHECK)
        if self.hop_s <= 0 or self.lookahead_s < 0:
            raise ValueError("hop_s must be > 0 and lookahead_s >= 0")
        if self.window_s < self.hop_s + self.lookahead_s:
            raise ValueError("window_s must cover hop_s + lookahead_s")
        if self.crossfade_ms < 0 or self.crossfade_ms / 1000 > min(self.lookahead_s, self.hop_s):
            raise ValueError("crossfade must fit inside the lookahead and the hop")

    @property
    def hop(self) -> int:
        return int(round(self.hop_s * self.sample_rate))

    @property
    def lookahead(self) -> int:
        return int(round(self.lookahead_s * self.sample_rate))

    @property
    def window(self) -> int:
        return int(round(self.window_s * self.sample_rate))

    @property
    def crossfade(self) -> int:
        return int(round(self.crossfade_ms / 1000 * self.sample_rate))

    @property
    def per_frame(self) -> int:
        return self.sample_rate // self.fps


class StreamBackend(Protocol):
    """Model-specific half. Frame indexes are session-global (ts_ms * fps / 1000)."""

    def detect(self, jpeg: bytes) -> list[dict]: ...
    def begin(self, index: int, jpeg: bytes, bbox: Sequence[int]) -> None: ...
    def push_frame(self, index: int, jpeg: bytes) -> str: ...  # tracking|uncertain|lost
    def hold(self, index: int) -> str: ...  # frame never arrived
    def roi_ready(self) -> int: ...  # frames [0, n) have a mouth ROI
    def finish(self) -> None: ...  # make every remaining ROI available
    def isolate(self, audio: np.ndarray, first_frame: int, last_frame: int) -> np.ndarray: ...
    def trim(self, before_frame: int) -> None: ...


@dataclass
class OutPart:
    start_sample: int
    pcm: bytes  # PCM16 mono; empty for non-ready states
    samples: int
    state: str
    compute_s: float = 0.0
    error: Optional[str] = None


@dataclass
class StreamStats:
    audio_gap_samples: int = 0
    audio_duplicate_samples: int = 0
    frame_gaps: int = 0
    frame_duplicates: int = 0
    parts: int = 0
    ready_parts: int = 0
    compute_s: float = 0.0
    track_s: float = 0.0
    emitted_s: float = 0.0
    state_counts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["rtf"] = (
            round((self.compute_s + self.track_s) / self.emitted_s, 4) if self.emitted_s > 0 else None
        )
        return d


class LiveStreamSession:
    def __init__(self, backend: StreamBackend, config: StreamConfig | None = None,
                 clock=time.perf_counter):
        self.backend, self.cfg, self._clock = backend, config or StreamConfig(), clock
        self.selected = False
        self.stats = StreamStats()
        self._audio = np.zeros(0, dtype=np.float32)
        self._audio_base = 0  # absolute index of _audio[0]
        self._have = 0  # absolute end of received audio
        self._emitted = 0
        self._tail: Optional[np.ndarray] = None  # previous estimate of the next crossfade region
        self._frame_last = -1
        self._states: dict[int, str] = {}
        self._finished = False
        self._origin = 0  # first sample with a tracked face; listening starts here

    # -- input ---------------------------------------------------------------
    def detect(self, jpeg: bytes) -> list[dict]:
        return self.backend.detect(jpeg)

    def select(self, index: int, jpeg: bytes, bbox: Sequence[int]) -> None:
        if self.selected:
            raise RuntimeError("target cannot change inside a session")
        self.backend.begin(index, jpeg, bbox)
        self._frame_last = index
        self._states[index] = "tracking"
        self.selected = True
        self._origin = self._emitted = max(self._emitted, index * self.cfg.per_frame)

    def push_audio(self, start_sample: int, pcm16: bytes) -> None:
        if len(pcm16) % 2:
            pcm16 = pcm16[:-1]
        data = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        end = start_sample + len(data)
        if end <= self._have:
            self.stats.audio_duplicate_samples += len(data)
            return
        if start_sample < self._have:
            overlap = self._have - start_sample
            self.stats.audio_duplicate_samples += overlap
            data, start_sample = data[overlap:], self._have
        if start_sample > self._have:
            gap = start_sample - self._have
            self.stats.audio_gap_samples += gap
            data = np.concatenate([np.zeros(gap, dtype=np.float32), data])
        self._audio = np.concatenate([self._audio, data])
        self._have = end

    def push_frame(self, ts_ms: float, jpeg: bytes) -> None:
        if not self.selected:
            return
        index = int(round(ts_ms * self.cfg.fps / 1000))
        if index <= self._frame_last:
            self.stats.frame_duplicates += 1
            return
        missing = index - self._frame_last - 1
        if missing > 0:
            self.stats.frame_gaps += missing
            start = self._frame_last + 1
            if missing > self.cfg.max_frame_gap:
                start = index - self.cfg.max_frame_gap
                for i in range(self._frame_last + 1, start):
                    self._states[i] = "lost"
            for i in range(start, index):
                self._states[i] = self.backend.hold(i)
        began = self._clock()
        self._states[index] = self.backend.push_frame(index, jpeg)
        self.stats.track_s += self._clock() - began
        self._frame_last = index

    # -- scheduling ----------------------------------------------------------
    def step(self) -> list[OutPart]:
        """Emit every hop whose lookahead is satisfied."""
        if not self.selected:
            return []
        parts = []
        cfg = self.cfg
        while True:
            end = self._emitted + cfg.hop + cfg.lookahead
            need_frames = -(-end // cfg.per_frame)
            if self._have < end or self.backend.roi_ready() < need_frames:
                return parts
            parts.append(self._emit(self._emitted + cfg.hop, end))

    def flush(self) -> list[OutPart]:
        """Stream ended: finish tracking and emit what is left without lookahead."""
        if not self.selected or self._finished:
            return []
        self._finished = True
        self.backend.finish()
        parts = []
        while self._emitted < self._have:
            stop = min(self._emitted + self.cfg.hop, self._have)
            parts.append(self._emit(stop, min(self._have, stop + self.cfg.lookahead)))
        return parts

    def _emit(self, stop: int, window_end: int) -> OutPart:
        cfg, start = self.cfg, self._emitted
        frames = range(start // cfg.per_frame, max(start // cfg.per_frame + 1, -(-stop // cfg.per_frame)))
        votes = [self._states.get(i, "lost") for i in frames]
        n = stop - start
        state = "ready"
        if votes.count("lost") * 2 > len(votes):
            state = "target_lost"
        elif votes.count("uncertain") + votes.count("lost") > 0 and \
                (votes.count("uncertain") + votes.count("lost")) * 2 >= len(votes):
            state = "uncertain"
        part = OutPart(start, b"", n, state)
        began = self._clock()
        if state == "ready":
            try:
                part.pcm = self._isolate_hop(start, stop, window_end)
            except Exception as exc:  # engine failure is explicit, never silent audio
                part.state, part.error, self._tail = "failed", type(exc).__name__, None
        else:
            self._tail = None
        part.compute_s = self._clock() - began
        self._account(part)
        self._emitted = stop
        self._trim()
        return part

    def _isolate_hop(self, start: int, stop: int, window_end: int) -> bytes:
        cfg = self.cfg
        w_start = max(0, (window_end - cfg.window) // cfg.per_frame * cfg.per_frame)
        w_start = max(w_start, self._audio_base, self._origin)
        audio = self._audio[w_start - self._audio_base:window_end - self._audio_base]
        first = w_start // cfg.per_frame
        last = -(-window_end // cfg.per_frame)
        est = np.asarray(self.backend.isolate(audio, first, last), dtype=np.float32)
        if est.shape[0] < window_end - w_start:
            raise ValueError("engine returned a short estimate")
        hop = est[start - w_start:stop - w_start].copy()
        xf = cfg.crossfade
        if self._tail is not None and xf and len(self._tail) == xf and len(hop) >= xf:
            ramp = np.linspace(0.0, 1.0, xf, dtype=np.float32)
            hop[:xf] = self._tail * (1 - ramp) + hop[:xf] * ramp
        tail_end = stop + xf
        self._tail = (
            est[stop - w_start:tail_end - w_start].copy()
            if xf and tail_end <= window_end else None
        )
        return (np.clip(hop, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

    def _account(self, part: OutPart) -> None:
        s = self.stats
        s.parts += 1
        s.ready_parts += part.state == "ready"
        s.compute_s += part.compute_s
        s.emitted_s += part.samples / self.cfg.sample_rate
        s.state_counts[part.state] = s.state_counts.get(part.state, 0) + 1

    def _trim(self) -> None:
        cfg = self.cfg
        keep_from = max(self._audio_base, self._emitted + cfg.hop + cfg.lookahead - cfg.window)
        keep_from = keep_from // cfg.per_frame * cfg.per_frame
        if keep_from > self._audio_base:
            self._audio = self._audio[keep_from - self._audio_base:]
            self._audio_base = keep_from
            frame = keep_from // cfg.per_frame
            self.backend.trim(frame)
            for i in [k for k in self._states if k < frame]:
                del self._states[i]
