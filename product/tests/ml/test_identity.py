"""Selection identity tests: the fix for the legacy ``db[:n_spk]`` order gap."""
import pytest

from focus_ml.errors import FaceNotFoundError
from focus_ml.identity import (
    candidate_identity,
    make_face_id,
    select_target_speaker,
    targets_match,
)
from focus_ml.types import FaceCandidate, TargetSelection

BBOX_A = (10, 20, 100, 120)
BBOX_B = (300, 150, 120, 140)
FRAME = (640, 480)


def _candidate(face_id: str, bbox=BBOX_A, timestamp_ms=0) -> FaceCandidate:
    return FaceCandidate(
        face_id=face_id, timestamp_ms=timestamp_ms, bbox=bbox, frame_size=FRAME
    )


def test_make_face_id_deterministic():
    first = make_face_id("video1", 0, BBOX_A, FRAME)
    second = make_face_id("video1", 0, BBOX_A, FRAME)
    assert first == second
    assert first == make_face_id("video1", 0, tuple(BBOX_A), tuple(FRAME))


def test_make_face_id_distinguishes_inputs():
    base = make_face_id("video1", 0, BBOX_A, FRAME)
    assert make_face_id("video2", 0, BBOX_A, FRAME) != base
    assert make_face_id("video1", 40, BBOX_A, FRAME) != base
    assert make_face_id("video1", 0, BBOX_B, FRAME) != base
    assert make_face_id("video1", 0, BBOX_A, (1920, 1080)) != base


def test_targets_match_exact_identity():
    candidate = _candidate("abc")
    assert targets_match(candidate, "abc") is True
    assert targets_match(candidate, "abd") is False


def test_wanted_second_in_list_is_matched_by_identity_not_order():
    wanted_id = make_face_id("video1", 0, BBOX_B, FRAME)
    candidates = [_candidate("first-in-list"), _candidate(wanted_id, BBOX_B)]
    selection = TargetSelection(face_id=wanted_id)
    slot, found = select_target_speaker(candidates, selection)
    assert slot == 1
    assert found.face_id == wanted_id
    assert found.bbox == BBOX_B


def test_select_target_speaker_unknown_identity_raises_face_not_found():
    candidates = [_candidate("a"), _candidate("b")]
    with pytest.raises(FaceNotFoundError) as excinfo:
        select_target_speaker(candidates, TargetSelection(face_id="missing"))
    assert "identity" in str(excinfo.value)


def test_candidate_identity_matches_equal_candidates():
    a = _candidate("x")
    a2 = FaceCandidate(face_id="other-id", timestamp_ms=0, bbox=BBOX_A, frame_size=FRAME)
    assert candidate_identity(a) == candidate_identity(a2)
    assert candidate_identity(a) != candidate_identity(_candidate("x", bbox=BBOX_B, timestamp_ms=40))
