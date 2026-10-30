import numpy as np
import pytest

from services.api.focus_api import mix

R = mix.WORK_RATE


def _signals(seconds=2.0, seed=1):
    rng = np.random.default_rng(seed)
    n = int(R * seconds)
    voice = rng.standard_normal(n) * 0.2
    others = rng.standard_normal(n) * 0.1
    return voice.astype(np.float32), others.astype(np.float32)


def test_alignment_recovers_offset_and_level():
    voice, others = _signals()
    original = 0.5 * voice + others
    delay = int(0.037 * R)  # isolated is 37 ms late relative to the original
    isolated = np.concatenate([np.zeros(delay), 0.2 * voice])[: len(voice)]
    # The isolated file is 37 ms late: it must be moved 37 ms earlier. The job
    # offset says -30 ms; the bounded search refines it to -37 ms.
    result = mix.align(original, isolated, offset_ms=-30.0)
    assert result.reliable, result.reason
    assert result.lag_ms == pytest.approx(-37.0, abs=0.1)
    assert result.gain == pytest.approx(0.5 / 0.2, rel=0.05)


def test_level_matching_and_residual_close_to_others():
    voice, others = _signals()
    original = 0.5 * voice + others
    result = mix.align(original, 0.1 * voice, offset_ms=0.0)
    assert result.reliable
    assert result.gain == pytest.approx(5.0, rel=0.05)
    err = np.sqrt(np.mean((result.others - others) ** 2)) / np.sqrt(np.mean(others ** 2))
    assert err < 0.2
    np.testing.assert_allclose(result.voice + result.others, original, atol=1e-5)


def test_unrelated_audio_is_unreliable_and_others_blocked():
    voice, others = _signals()
    original = 0.5 * voice + others
    stranger, _ = _signals(seed=99)
    result = mix.align(original, stranger, offset_ms=0.0)
    assert not result.reliable and result.reason
    assert not np.any(result.others)
    with pytest.raises(mix.MixError) as caught:
        mix.render_mix(result, mix.MixSettings(voice_level=1, others_level=0.5))
    assert caught.value.code == "MIX_UNRELIABLE"
    # Voice-only rendering stays possible and explicit.
    mix.render_mix(result, mix.MixSettings(voice_level=1, others_level=0))


def test_too_short_or_silent_isolated_is_unreliable():
    voice, others = _signals()
    original = 0.5 * voice + others
    assert not mix.align(original, 0.1 * voice[: len(voice) // 4]).reliable
    assert not mix.align(original, np.zeros_like(voice)).reliable
    assert not mix.align(original, np.zeros(0, dtype=np.float32)).reliable


def test_limiter_never_exceeds_full_scale():
    rng = np.random.default_rng(3)
    loud = (rng.standard_normal(R) * 3.0).astype(np.float32)
    loud[1000] = 40.0
    out = mix.limit_peaks(loud)
    assert np.max(np.abs(out)) <= mix.LIMITER_CEILING + 1e-7
    quiet = np.full(1000, 0.1, dtype=np.float32)
    np.testing.assert_allclose(mix.limit_peaks(quiet), quiet)


def test_render_mix_peak_limited_with_boosted_voice():
    voice, others = _signals()
    original = 0.5 * voice + others
    result = mix.align(original, 0.1 * voice)
    out = mix.render_mix(result, mix.MixSettings(voice_level=2.0, others_level=1.0, noise_reduction="strong"))
    assert len(out) == len(original)
    assert np.max(np.abs(out)) <= 1.0


def test_levels_scale_tracks():
    voice, others = _signals()
    original = 0.5 * voice + others
    result = mix.align(original, 0.1 * voice)
    only_voice = mix.render_mix(result, mix.MixSettings(1.0, 0.0))
    np.testing.assert_allclose(only_voice, mix.limit_peaks(result.voice), atol=1e-6)
    muted = mix.render_mix(result, mix.MixSettings(0.0, 0.0))
    assert not np.any(muted)


def test_noise_filter_attenuates_rumble_keeps_speech_band():
    t = np.arange(R) / R
    low = np.sin(2 * np.pi * 40 * t).astype(np.float32)
    mid = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    assert np.std(mix.noise_filter(low, "strong")) < 0.1 * np.std(low)
    assert np.std(mix.noise_filter(mid, "strong")) > 0.95 * np.std(mid)
    assert mix.noise_filter(mid, "off") is mid


def test_invalid_settings_rejected():
    for bad in (mix.MixSettings(-1, 0), mix.MixSettings(1, 2), mix.MixSettings(1, 0, "ai")):
        with pytest.raises(mix.MixError):
            bad.validated()
