"""AAC end-padding regressions using an explicit test-only passthrough model."""
from types import SimpleNamespace

import numpy as np
import pytest

torch = pytest.importorskip('torch')
sf = pytest.importorskip('soundfile')

from focus_ml.adapter import LegacyDolphinAdapter
from focus_ml.config import AdapterConfig
from focus_ml.errors import MediaError


class FakeCudaEvent:
    def __init__(self, **_kwargs):
        pass

    def record(self):
        pass

    def elapsed_time(self, _other):
        return 1.0


@pytest.mark.parametrize('audio_samples', [96273, 95900, 96000])
def test_codec_rounding_keeps_six_seconds_and_never_sends_empty_roi(tmp_path, monkeypatch, audio_samples):
    monkeypatch.setattr(torch.cuda, 'Event', FakeCudaEvent)
    monkeypatch.setattr(torch.cuda, 'synchronize', lambda: None)
    source = tmp_path / 'mix.wav'
    sf.write(source, np.full(audio_samples, 0.125, dtype=np.float32), 16000)
    windows = []

    def fake_model(audio, roi):
        assert roi.shape[2] > 0, 'The AAC tail must not create an empty visual window'
        windows.append((audio.shape[-1], roi.shape[2]))
        return audio[:, None, :]

    backend = {
        'torch': torch,
        'inference': SimpleNamespace(get_preprocessing_pipelines=lambda: {'val': lambda roi: roi}),
    }
    adapter = LegacyDolphinAdapter()
    path, samples, rate, _ = adapter._separate(
        backend, str(source), np.zeros((150, 88, 88), dtype=np.uint8),
        AdapterConfig(device='cpu'), fake_model,
    )
    result, _ = sf.read(path)
    assert samples == len(result) == 96000 and rate == 16000
    assert windows == [(32000, 50)] * 3
    assert adapter.last_audio_alignment_samples == 96000 - audio_samples
    if audio_samples < 96000:
        assert not result[audio_samples:].any()


def test_substantial_timeline_mismatch_fails_without_clipping_content(tmp_path):
    source = tmp_path / 'mix.wav'
    sf.write(source, np.zeros(112000, dtype=np.float32), 16000)
    backend = {
        'torch': torch,
        'inference': SimpleNamespace(get_preprocessing_pipelines=lambda: {'val': lambda roi: roi}),
    }
    with pytest.raises(MediaError, match='timelines do not align'):
        LegacyDolphinAdapter()._separate(
            backend, str(source), np.zeros((150, 88, 88), dtype=np.uint8),
            AdapterConfig(device='cpu'), lambda *_: pytest.fail('inference must not run'),
        )
    assert not (tmp_path / 'target_extract.wav').exists()
