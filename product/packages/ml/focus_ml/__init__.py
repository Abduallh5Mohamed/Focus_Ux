"""focus_ml: import-safe ML adapter package for the FOCUS product.

Importing focus_ml performs no heavy-library imports (torch, cv2,
face_alignment, soundfile, numpy), no cwd change and no sys.path mutation.
Real legacy-backend activation happens lazily at execution time only.

Caller contract note: detect_candidates/extract_target accept ``video_id``;
the adapter CANNOT access the jobs DB, so the API layer MUST pass the real
contract video_id. When it is None the identity falls back to the media file
basename, which is NOT contract-conformant and is flagged with a warning in
the extraction flow.
"""
from focus_ml.adapter import (
    LegacyDolphinAdapter,
    detect_candidates,
    extract_target,
    load_models,
)
from focus_ml.config import AdapterConfig
from focus_ml.errors import (
    FaceNotFoundError,
    GpuBusyError,
    LimitError,
    MediaError,
    MlError,
    ModelUnavailableError,
    NoAudioError,
    ProcessingError,
    TargetLostError,
)
from focus_ml.identity import (
    candidate_identity,
    make_face_id,
    select_target_speaker,
    targets_match,
)
from focus_ml.timing import (
    FRAME_FPS,
    SAMPLE_RATE,
    audio_window_to_roi,
    duration_ms_from_samples,
    frames_to_ms,
    ms_to_frame_index,
    normalize_timestamps_ms,
)
from focus_ml.tracking import (
    DETECT_EVERY,
    bb_intersection_over_union,
    character_to_face,
    match_detections,
)
from focus_ml.types import ExtractionResult, FaceCandidate, ModelBundle, TargetSelection

__all__ = [
    "AdapterConfig",
    "DETECT_EVERY",
    "ExtractionResult",
    "FaceCandidate",
    "FaceNotFoundError",
    "FRAME_FPS",
    "GpuBusyError",
    "LegacyDolphinAdapter",
    "LimitError",
    "MediaError",
    "MlError",
    "ModelBundle",
    "ModelUnavailableError",
    "NoAudioError",
    "ProcessingError",
    "SAMPLE_RATE",
    "TargetLostError",
    "TargetSelection",
    "audio_window_to_roi",
    "bb_intersection_over_union",
    "candidate_identity",
    "character_to_face",
    "detect_candidates",
    "duration_ms_from_samples",
    "extract_target",
    "frames_to_ms",
    "load_models",
    "make_face_id",
    "match_detections",
    "ms_to_frame_index",
    "normalize_timestamps_ms",
    "select_target_speaker",
    "targets_match",
]
