"""Level matching must not amplify the background.

A real job exported 2.8 dB LOUDER than its source: the whole-file
least-squares fit was pulled up by the muted background, so the background bed
under the voice came out boosted instead of untouched. The fit now runs on the
isolated voice's active samples only.
"""
import numpy as np
import pytest

from services.api.focus_api import mix

R = mix.WORK_RATE


def _mix_signal(seconds=4.0, seed=5):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(R * seconds)) * 0.2).astype(np.float32)


def test_level_fit_is_not_pulled_up_by_the_ducked_background():
    original = _mix_signal()
    n = len(original)
    mask = np.ones(n, dtype=np.float32)
    mask[n // 2:] = 0.25                      # 50 % of the file at -12 dB
    isolated = original * mask                # what DuckedBaseline returns

    result = mix.align(original, isolated, offset_ms=0.0)

    assert result.reliable, result.reason
    # The whole-file fit would land near 1.12 (+1 dB on the bed); the active-only
    # fit recovers the true 1.0.
    assert result.gain == pytest.approx(1.0, abs=0.02)
    assert result.gain_clamped is False
    np.testing.assert_allclose(result.voice + result.others, original, atol=1e-5)


def test_level_fit_still_matches_a_quieter_model_output():
    original = _mix_signal()
    result = mix.align(original, 0.1 * original, offset_ms=0.0)
    assert result.reliable
    assert result.gain == pytest.approx(10.0, rel=0.02)
    assert result.gain_clamped is False


def test_degenerate_fit_is_bounded_and_flagged():
    original = _mix_signal()
    # 100x too quiet: the fit is clamped to the sanity bound and reported.
    result = mix.align(original, 0.01 * original, offset_ms=0.0)
    assert result.gain == pytest.approx(mix.MAX_GAIN)
    assert result.gain_clamped is True


def test_gated_isolation_does_not_change_the_source_level():
    original = _mix_signal()
    isolated = original.copy()
    isolated[: len(isolated) // 2] = 0.0      # hard gate
    result = mix.align(original, isolated, offset_ms=0.0)
    assert result.gain == pytest.approx(1.0, abs=0.02)
    rendered = mix.render_mix(result, mix.MixSettings(voice_level=1.0, others_level=0.0))
    active = slice(len(rendered) // 2, len(rendered))
    assert (np.sqrt(np.mean(rendered[active] ** 2))
            == pytest.approx(np.sqrt(np.mean(original[active] ** 2)), rel=0.02))


def test_target_only_render_adds_no_original_audio_where_the_target_is_silent():
    rng = np.random.default_rng(11)
    n = int(R * 4.0)
    half = n // 2
    voice = (rng.standard_normal(n) * 0.2).astype(np.float32)
    others = (rng.standard_normal(n) * 0.2).astype(np.float32)
    voice[:half] = 0.0                         # target speaks in the second half only
    original = (0.5 * voice + others).astype(np.float32)
    isolated = (0.3 * voice).astype(np.float32)

    result = mix.align(original, isolated, offset_ms=0.0)
    assert result.reliable, result.reason

    target_only = mix.render_mix(result, mix.MixSettings(voice_level=1.0, others_level=0.0))
    # In the target's gaps the target-only render must stay silent: no original
    # audio or residual is mixed back in.
    assert np.max(np.abs(target_only[:half])) < 1e-6
    assert np.sqrt(np.mean(target_only[half:] ** 2)) > 0.05

    # Asking for the residual explicitly does bring the other voice back.
    with_others = mix.render_mix(result, mix.MixSettings(voice_level=1.0, others_level=1.0))
    assert np.sqrt(np.mean(with_others[:half] ** 2)) > 0.05
