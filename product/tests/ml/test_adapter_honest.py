"""Honesty tests: the adapter must refuse to fabricate success, never create
wav files on failure paths, keep errors user-safe, honor identity selection,
and reject unsupported configurations. The pure seam ``resolve_target_speaker``
(the adapter path that used to be ``db[:n_spk]``) is testable CPU-side."""
import json
import os
import subprocess
import sys

import pytest

import focus_ml
from focus_ml.adapter import (
    LegacyDolphinAdapter,
    resolve_target_speaker,
    select_target_speaker,
)
from focus_ml.config import AdapterConfig
from focus_ml.errors import (
    FaceNotFoundError,
    LimitError,
    MediaError,
    ModelUnavailableError,
    NoAudioError,
)
from focus_ml.identity import make_face_id
from focus_ml.types import FaceCandidate, ModelBundle, TargetSelection

_HVY = ("torch", "cv2", "face_alignment", "soundfile")


def _heavy_modules_importable() -> bool:
    """Matches adapter.available(): the full heavy stack must import, not just
    one module (a partial stack still means the real backend is unavailable)."""
    return all(_single_importable(name) for name in _HVY)


def _single_importable(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


HEAVY_PRESENT = _heavy_modules_importable()
no_backend = pytest.mark.skipif(HEAVY_PRESENT, reason="heavy backend stack fully importable")


def _job_dir(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    return str(job_dir)


# --- M8: available()/load_models honesty on this interpreter + subsystem stub


@no_backend
def test_available_is_false_without_backend():
    adapter = LegacyDolphinAdapter()
    assert adapter.available() is False


@no_backend
def test_load_models_raises_model_unavailable_without_backend():
    adapter = LegacyDolphinAdapter(config=AdapterConfig())
    with pytest.raises(ModelUnavailableError):
        adapter.load_models()


def test_modules_absent_branch_via_interpreter_subprocess():
    """Proves the modules-absent branch even on interpreters where the heavy
    stack importable: stub sys.modules with None so import raises ImportError."""
    package_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "packages", "ml")
    )
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, r'{package_root}')\n"
        "for name in ('torch', 'cv2', 'face_alignment', 'soundfile'):\n"
        "    sys.modules[name] = None\n"
        "import focus_ml\n"
        "adapter = focus_ml.LegacyDolphinAdapter()\n"
        "try:\n"
        "    ok = adapter.load_models()\n"
        "    result = {'available': adapter.available(), 'raised': False, 'code': ''}\n"
        "except Exception as exc:\n"
        "    result = {\n"
        "        'available': adapter.available(), 'raised': True,\n"
        "        'code': getattr(exc, 'code', '')\n"
        "    }\n"
        "print(json.dumps(result))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout.strip().splitlines()[-1])
    assert report["available"] is False
    assert report["raised"] is True
    assert report["code"] == "PROCESSING_FAILED"


# --- M9: deterministic fake-torch tests (cuda-present and no-cuda branches)


def _with_fake_modules(monkeypatch, cuda_available: bool):
    import types

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: cuda_available)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    for name in ("cv2", "face_alignment", "soundfile"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))


def test_load_models_hits_model_source_branch_when_cuda_present(monkeypatch):
    _with_fake_modules(monkeypatch, cuda_available=True)
    config = AdapterConfig(model_source="Z:/no/such/dir")
    with pytest.raises(ModelUnavailableError) as excinfo:
        LegacyDolphinAdapter(config=config).load_models()
    assert "model source" in excinfo.value.detail
    detail = excinfo.value.detail
    assert "no CUDA" not in detail


def test_load_models_hits_no_cuda_branch_when_source_ok(monkeypatch, tmp_path):
    _with_fake_modules(monkeypatch, cuda_available=False)
    source_dir = tmp_path / "engine"
    source_dir.mkdir()
    config = AdapterConfig(model_source=str(source_dir), device="cuda")
    with pytest.raises(ModelUnavailableError) as excinfo:
        LegacyDolphinAdapter(config=config).load_models()
    assert "no CUDA device available" in excinfo.value.detail


# --- M1: user-safe error messages, payload carries no detail


def test_media_error_message_is_user_safe_and_path_free(tmp_path):
    adapter = LegacyDolphinAdapter()
    hidden = str(tmp_path / "hidden_recording.mp4")
    with pytest.raises(MediaError) as excinfo:
        adapter.detect_candidates(hidden)
    error = excinfo.value
    assert set(json.loads(json.dumps(error.as_dict())).keys()) == {
        "code", "message", "retryable"
    }
    payload = json.dumps(error.as_dict())
    assert tmp_path.name not in payload and "hidden" not in payload
    assert error.message == "media file not found"
    assert "hidden_recording.mp4" in error.detail


def test_error_payload_never_includes_detail():
    for error in (
        MediaError("media file not found", detail="Z:/secret/x.mp4"),
        NoAudioError("no audio", detail="ffmpeg stderr leak"),
        ModelUnavailableError("backend unavailable", detail="torch missing detail"),
    ):
        payload = json.dumps(error.as_dict())
        assert set(error.as_dict().keys()) == {"code", "message", "retryable"}
        assert "Z:" not in payload and "stderr" not in payload
        assert error.detail  # diagnostics preserved for logs only


# --- M3: downscale config is rejected before anything runs


def test_downscale_configuration_rejected(tmp_path):
    config = AdapterConfig(downscale=2.0)
    adapter = LegacyDolphinAdapter(config=config)
    with pytest.raises(LimitError):
        adapter.detect_candidates("Z:/no/there.mp4", config)
    bundle = ModelBundle(dolphin=object(), config=config, loaded=True)
    with pytest.raises(LimitError):
        adapter.extract_target(
            "video.mp4", TargetSelection(face_id="f"), str(tmp_path), bundle
        )
    assert os.path.isdir(str(tmp_path)) and os.listdir(str(tmp_path)) == []


# --- M4: process state restored after engine activation failure


def test_load_backend_restores_process_state_on_failure(monkeypatch, tmp_path):
    _with_fake_modules(monkeypatch, cuda_available=True)
    source = tmp_path / "engine"
    source.mkdir()
    before_cwd = os.getcwd()
    before_path = list(sys.path)
    adapter = LegacyDolphinAdapter(
        config=AdapterConfig(model_source=str(source), device="cuda")
    )
    with pytest.raises(ModelUnavailableError) as excinfo:
        adapter._load_backend()
    assert os.getcwd() == before_cwd
    assert sys.path == before_path
    assert "engine checkout" in excinfo.value.detail


# --- zero-artifact guarantee on failure paths


def test_extract_target_with_models_none_raises_and_writes_no_wav(tmp_path):
    job_dir = _job_dir(tmp_path)
    adapter = LegacyDolphinAdapter()
    with pytest.raises(ModelUnavailableError):
        adapter.extract_target(
            "whatever.mp4", TargetSelection(face_id="x"), job_dir, None
        )
    for _root, _dirs, files in os.walk(job_dir):
        assert files == [], "no wav or other file may be created on failure"


def test_detect_candidates_nonexistent_video_raises_media_error(tmp_path):
    adapter = LegacyDolphinAdapter()
    missing = str(tmp_path / "missing.mp4")
    with pytest.raises(MediaError):
        adapter.detect_candidates(missing)


@no_backend
def test_unloaded_models_block_extraction(tmp_path):
    # even with a bundle object, loaded=False (milestone truth) must refuse
    job_dir = _job_dir(tmp_path)
    bundle = ModelBundle(config=AdapterConfig(model_source=str(job_dir)), loaded=False)
    with pytest.raises(ModelUnavailableError):
        LegacyDolphinAdapter().extract_target(
            "whatever.mp4", TargetSelection(face_id="x"), job_dir, bundle
        )
    assert os.listdir(job_dir) == []


# --- identity selection seam (the old db[:n_spk] path)


def test_adapter_identity_seam_selects_by_identity_not_order():
    config = AdapterConfig()
    frame_size = (640, 480)
    wanted_bbox_xywh = (300, 40, 110, 120)
    wanted_id = make_face_id("vid", 0, wanted_bbox_xywh, frame_size)
    # wanted face is SECOND in detection order; identity must win over position
    detections = [[10, 10, 120, 130], [300, 40, 410, 160]]
    slot, candidates = resolve_target_speaker(
        detections, "vid", frame_size, config, TargetSelection(face_id=wanted_id)
    )
    assert slot == 1
    assert candidates[slot].face_id == wanted_id
    assert candidates[slot].bbox == wanted_bbox_xywh


def test_adapter_identity_seam_unknown_identity_raises_user_safe_error():
    config = AdapterConfig()
    with pytest.raises(FaceNotFoundError) as excinfo:
        resolve_target_speaker(
            [[0, 0, 100, 100]], "vid", (640, 480), config,
            TargetSelection(face_id="missing-id"),
        )
    assert "first" in str(excinfo.value)


def test_select_target_speaker_first_frame_limitation_message():
    candidates = [
        FaceCandidate(
            face_id="other", timestamp_ms=0, bbox=(0, 0, 1, 1), frame_size=(1, 1)
        )
    ]
    with pytest.raises(FaceNotFoundError) as excinfo:
        select_target_speaker(candidates, TargetSelection(face_id="wanted"))
    message = str(excinfo.value)
    assert "first" in message
    assert "identity" in message


def test_select_target_speaker_matches_by_identity_among_first_frame_only():
    candidates = [
        FaceCandidate(face_id="a", timestamp_ms=0, bbox=(0, 0, 1, 1), frame_size=(1, 1)),
        FaceCandidate(face_id="target-id", timestamp_ms=0, bbox=(2, 2, 3, 3), frame_size=(1, 1)),
    ]
    slot, candidate = select_target_speaker(candidates, TargetSelection(face_id="target-id"))
    assert slot == 1
    assert candidate.bbox == (2, 2, 3, 3)
    assert candidate.index == 0
