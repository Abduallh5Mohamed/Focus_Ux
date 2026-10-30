import pytest

from focus_ml.window_plan import separation_windows


def test_aac_16ms_tail_borrows_context_without_changing_output_timeline():
    plan = list(separation_windows(96256, 32000, 150, 16000, 25))
    assert [(p.output_start, p.output_end) for p in plan] == [
        (0, 32000), (32000, 64000), (64000, 96000), (96000, 96256)
    ]
    tail = plan[-1]
    assert tail.model_start == 64256
    assert (tail.roi_start, tail.roi_end) == (100, 150)
    assert tail.output_offset == 31744
    assert tail.output_offset + (tail.output_end - tail.output_start) == 32000


@pytest.mark.parametrize("samples,frames", [(96000, 150), (80000, 125), (32768, 50), (16001, 25), (64001, 100)])
def test_writes_cover_every_sample_once_and_model_context_stays_bounded(samples, frames):
    plan = list(separation_windows(samples, 32000, frames, 16000, 25))
    cursor = 0
    for p in plan:
        assert p.output_start == cursor
        assert 0 <= p.model_start <= p.output_start < p.output_end <= samples
        assert p.output_end - p.model_start <= 32000
        assert 0 <= p.roi_start < p.roi_end <= frames
        assert p.roi_end - p.roi_start >= 7
        cursor = p.output_end
    assert cursor == samples


def test_full_reference_windows_are_unchanged():
    plan = list(separation_windows(96000, 32000, 150, 16000, 25))
    assert [p.model_start for p in plan] == [0, 32000, 64000]
    assert [(p.roi_start, p.roi_end) for p in plan] == [(0, 50), (50, 100), (100, 150)]
    assert all(p.output_offset == 0 for p in plan)


@pytest.mark.parametrize("samples,frames", [(1280, 2), (0, 50), (32000, 0)])
def test_missing_or_very_short_context_fails_instead_of_inventing_frames(samples, frames):
    with pytest.raises(ValueError):
        list(separation_windows(samples, 32000, frames, 16000, 25))
