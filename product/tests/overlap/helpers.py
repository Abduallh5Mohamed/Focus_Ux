import numpy as np

from fakes import FREQS, SR, FakeEmbedder, scene, tone
from focus_ml.overlap.base import CandidateInfo, OverlapExtractor
from focus_ml.voice.types import Voiceprint

BANDS = (220.0, 440.0, 880.0, 1200.0)


def info(name="fake", categories=("overlap_2", "overlap_3plus"), mechanism="target_conditioned"):
    return CandidateInfo(name=name, title=name, mechanism=mechanism, code_licence="t", weights_licence="t",
                         model_rate=16000, categories=categories)


def voiceprint_for(spk):
    return Voiceprint(list(FakeEmbedder().embed(tone(FREQS[spk], 2))), "ecapa", 2.0, {})


def enrollment_for(spk):
    return tone(FREQS[spk], 6)


class ToneExtractor(OverlapExtractor):
    """Keeps only the target's tone (found from the voiceprint). 'wrong=True' keeps another speaker."""
    info = info()

    def __init__(self, wrong=False, silent=False, resize=0, max_ok_batch=None, oom_always=False):
        super().__init__("cpu", False)
        self.wrong, self.silent, self.resize = wrong, silent, resize
        self.max_ok_batch, self.oom_always = max_ok_batch, oom_always
        self.batches = []

    def check_ready(self):
        pass

    def _extract_batch(self, windows, voiceprint, enrollment):
        self.batches.append(len(windows))
        if self.oom_always or (self.max_ok_batch and len(windows) > self.max_ok_batch):
            raise RuntimeError("CUDA out of memory. Tried to allocate")
        k = int(np.argmax(voiceprint.vector))
        if self.wrong:
            k = (k + 1) % 3
        outs = []
        for w in windows:
            if self.silent:
                outs.append(np.zeros_like(w))
                continue
            spec = np.fft.rfft(w.astype(np.float64))
            f = np.fft.rfftfreq(len(w), 1 / SR)
            spec[np.abs(f - BANDS[k]) > 3] = 0
            o = np.fft.irfft(spec, len(w)).astype(np.float32)
            if self.resize:
                o = o[:len(o) + self.resize] if self.resize < 0 else np.concatenate([o, np.zeros(self.resize, np.float32)])
            outs.append(o)
        return outs
