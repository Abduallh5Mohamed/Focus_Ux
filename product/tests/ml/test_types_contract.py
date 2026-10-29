"""Contract-shape tests for the stdlib dataclasses."""
import dataclasses

from focus_ml.types import ExtractionResult, FaceCandidate, ModelBundle, TargetSelection


def test_extraction_result_has_exactly_contract_fields():
    names = [f.name for f in dataclasses.fields(ExtractionResult)]
    assert names == [
        "wav_path",
        "duration_ms",
        "source_offset_ms",
        "timings",
        "warnings",
    ]


def test_face_candidate_bbox_and_frame_size_are_tuples():
    candidate = FaceCandidate(
        face_id="fid",
        timestamp_ms=40,
        bbox=(1, 2, 3, 4),
        frame_size=(640, 480),
    )
    assert isinstance(candidate.bbox, tuple) and len(candidate.bbox) == 4
    assert isinstance(candidate.frame_size, tuple) and len(candidate.frame_size) == 2
    assert candidate.index == 0


def test_target_selection_holds_face_id():
    assert TargetSelection(face_id="fid").face_id == "fid"


def test_model_bundle_defaults():
    bundle = ModelBundle()
    assert bundle.dolphin is None
    assert bundle.face_alignment is None
    assert bundle.device == "cuda"
    assert bundle.config is None
    assert bundle.loaded is False

def test_error_payload_contract_shape_and_no_detail_leak():
    """M1/m8: payload is exactly {code,message,retryable}; raw detail stays
    out of the payload; shared retryability vocabulary (PROCESSING_FAILED
    retryable=True everywhere)."""
    import json

    from focus_ml.errors import (
        MediaError,
        ModelUnavailableError,
        NoAudioError,
        ProcessingError,
    )

    for error in (
        MediaError("media file not found", detail="Z:/secret/x.mp4"),
        NoAudioError("no audio", detail="ffmpeg stderr text"),
        ProcessingError("processing failed", detail="internal"),
        ModelUnavailableError("backend unavailable", detail="torch ImportError"),
    ):
        payload = error.as_dict()
        assert set(payload.keys()) == {"code", "message", "retryable"}
        serialized = json.dumps(payload)
        assert "Z:" not in serialized
        assert "stderr" not in serialized

    assert ProcessingError("x").retryable is True
    assert ModelUnavailableError("y").retryable is True
    assert MediaError("z").retryable is False
