"""Pure IoU tracking port tests: legacy matching + veto dedup semantics."""
import pytest

from focus_ml.tracking import (
    DETECT_EVERY,
    bb_intersection_over_union,
    character_to_face,
    match_detections,
)


def test_detect_every_constant():
    assert DETECT_EVERY == 8


def test_iou_identical_boxes_is_one():
    box = (0, 0, 100, 100)
    assert bb_intersection_over_union(box, box) == 1.0


def test_iou_disjoint_boxes_is_zero():
    assert bb_intersection_over_union((0, 0, 10, 10), (50, 50, 60, 60)) == 0.0


def test_iou_partial_overlap():
    value = bb_intersection_over_union((0, 0, 10, 10), (5, 0, 15, 10))
    assert 0.0 < value < 1.0


def test_iou_degenerate_boxes_are_zero_without_raising():
    assert bb_intersection_over_union((0, 0, 0, 0), (0, 0, 0, 0)) == 0.0
    assert bb_intersection_over_union((0, 0, 10, 10), (50, 50, 50, 50)) == 0.0


def test_character_to_face_keeps_center_and_expands():
    x1, y1, x2, y2 = character_to_face((10, 10, 110, 130), scale=1.5)
    square = int(max(110, 130) * 1.5)
    assert (x1 + x2) / 2 == (10 + (10 + 110)) / 2
    assert (y1 + y2) / 2 == (10 + (10 + 130)) / 2
    # center-preserving square: full side equals the square, half a side equals square/2
    assert x2 - x1 == square
    assert y2 - y1 == square
    assert x1 + square / 2 == 10 + 110 / 2


def test_match_detections_best_iou_assignment():
    speaker_prev = [(0, 0, 100, 100), (200, 200, 300, 300)]
    detected = [(195, 195, 300, 300), (5, 5, 100, 100)]
    result = match_detections(speaker_prev, detected)
    # box near speaker1 must land on speaker1 despite list order
    assert tuple(result[0]) == (5, 5, 100, 100)
    assert tuple(result[1]) == (195, 195, 300, 300)


def test_match_detections_holds_last_box_when_unmatched():
    speaker_prev = [(0, 0, 100, 100), (200, 200, 300, 300)]
    detected = [(195, 195, 300, 300)]
    result = match_detections(speaker_prev, detected)
    assert tuple(result[0]) == (0, 0, 100, 100)
    assert tuple(result[1]) == (195, 195, 300, 300)


def test_match_detections_veto_uses_each_detection_once():
    speaker_prev = [(0, 0, 100, 100), (0, 0, 100, 100)]
    detected = [(2, 2, 100, 100)]
    result = match_detections(speaker_prev, detected)
    assert len([box for box in result if tuple(box) == (2, 2, 100, 100)]) == 1
    # one detection can never map to both speakers (legacy matched-set veto)
    assert tuple(result[0]) == (2, 2, 100, 100) or tuple(result[1]) == (2, 2, 100, 100)
