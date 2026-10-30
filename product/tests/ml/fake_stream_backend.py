import numpy as np


class FakeBackend:
    def __init__(self, lag=6, lost_from=None):
        self.n, self.lag, self.lost_from = 0, lag, lost_from
        self.windows, self.finished = [], False

    def detect(self, jpeg):
        return [{"bbox": [1, 2, 3, 4]}]

    def begin(self, index, jpeg, bbox):
        self.n = index + 1

    def push_frame(self, index, jpeg):
        self.n = index + 1
        return "lost" if self.lost_from is not None and index >= self.lost_from else "tracking"

    def hold(self, index):
        self.n = index + 1
        return "lost"

    def roi_ready(self):
        return self.n if self.finished else max(0, self.n - self.lag)

    def finish(self):
        self.finished = True

    def isolate(self, audio, first, last):
        self.windows.append((len(audio), first, last))
        return audio * 0.5

    def trim(self, before):
        pass


def pcm(samples):
    return (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
