"""Small deterministic fakes: each 'speaker' is a sine tone; the fake embedder
reads the spectrum, so same tone => same voice. No models involved."""
import numpy as np

from focus_ml.voice.types import Diarization, Segment
from focus_ml.voice.diarizer import from_turns

SR = 16000
FREQS = {"A": 220.0, "B": 440.0, "C": 880.0}


def tone(freq, seconds, amp=0.3):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def scene(plan, total_s, amp=0.3):
    """plan: [(speaker, start, end)] -> mixed audio (tones summed)."""
    x = np.zeros(int(total_s * SR), dtype=np.float32)
    for spk, a, b in plan:
        ia, ib = int(a * SR), int(b * SR)
        x[ia:ib] += tone(FREQS[spk], b - a, amp)[: ib - ia]
    return x


class FakeEmbedder:
    name = "ecapa"

    def __init__(self):
        self.unloaded = 0
        self.calls = 0

    def load(self):
        pass

    def embed(self, samples):
        self.calls += 1
        spec = np.abs(np.fft.rfft(np.asarray(samples, dtype=np.float64), n=SR))
        bands = np.array([spec[int(f) - 3:int(f) + 4].sum() for f in (220, 440, 880, 1200)])
        bands = bands + 1e-3
        return bands / np.linalg.norm(bands)

    def unload(self):
        self.unloaded += 1


class FakeDiarizer:
    model_id = "fake"

    def __init__(self, turns):
        self.turns, self.calls, self.unloaded = turns, 0, 0

    def diarize(self, samples):
        self.calls += 1
        return from_turns([Segment(a, b, s) for s, a, b in self.turns])

    def unload(self):
        self.unloaded += 1
