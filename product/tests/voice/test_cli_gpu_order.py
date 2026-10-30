import argparse

import numpy as np

from focus_ml.voice import cli
from focus_ml.voice.types import SAMPLE_RATE, Diarization, Segment


def test_enroll_file_unloads_diarizer_before_embedding(monkeypatch):
    events = []
    x = np.random.default_rng(0).normal(0, 0.1, SAMPLE_RATE * 8).astype("float32")
    monkeypatch.setattr(cli, "load_canonical", lambda p: x)

    class Diar:
        def diarize(self, s):
            events.append("diarize")
            return Diarization(turns=[Segment(0, 8, "A")], overlaps=[], speech=[Segment(0, 8)])

        def unload(self):
            events.append("unload_diarizer")

    class Emb:
        name = "fake"

        def embed(self, s):
            events.append("embed")
            return np.ones(4) / 2

    a = argparse.Namespace(min_clean_s=4.0, enroll_speaker=None, enroll_range=None,
                           enroll_file="v.wav", voiceprint=None)
    cli.make_voiceprint(a, x, None, Emb(), Diar())
    assert events.index("unload_diarizer") < events.index("embed")
