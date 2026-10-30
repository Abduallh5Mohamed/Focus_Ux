"""LegacyDolphinAdapter: the explicit integration boundary to the legacy
A:/focus engine (legacy_snapshot/tools/focus_runner.py + Dolphin/Inference.py).

Contract function names (docs/02_CONTRACTS.md "Python adapter الداخلي"):
``load_models(config)``, ``detect_candidates(video_path, config)``,
``extract_target(video_path, target, job_dir, models, on_progress)``.

Module import is side-effect free: no torch/cv2/face_alignment import, no cwd
change, no sys.path mutation. Heavy imports happen only inside ``_load_backend``
at execution time.

STATUS (read before trusting any result; update ONLY with executed evidence):
- Round 2: real offline weight loading is implemented in ``load_models``
  (Dolphin.from_pretrained with local_files_only=True against the caller-supplied
  FOCUS_MODEL_CACHE; no network traffic is ever possible here). The extraction
  pipeline is a line-by-line port of legacy focus_runner.py with the channel
  order and device placement verified against the engine on GPU on the gt5
  fixtures (see product/tools/verify_gpu.py report under runtime/round2/ml/).
- The selection identity gap (legacy ``db[:n_spk]`` truncation, docs/01 #1) is
  addressed CPU-side via ``resolve_target_speaker`` (identity match, not order).
- Day-1 selection contract: candidates only from the FIRST valid detected
  frame (index 0); later-frame targets need validated engine support that does
  not exist yet (the FaceNotFoundError path says so, for API display).
- Non-25fps sources: ``focus_ml.normalize.normalize_input`` canonicalizes any
  upload to 25fps video + 16k mono audio, timeline-preserving, into a
  caller-supplied job directory. ``extract_target`` warns (does not refuse)
  when the source fps deviates from the configured fps.
- User-facing error messages carry NO system paths or tool stderr; raw
  diagnostics are kept in ``MlError.detail`` (logs only) and never enter
  ``as_dict()`` payloads.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Callable, Optional, Sequence

from focus_ml.adaptive_tracking import AdaptiveConfig, AdaptiveFaceTracker
from focus_ml.config import AdapterConfig
from focus_ml.errors import (
    FaceNotFoundError,
    LimitError,
    MediaError,
    ModelUnavailableError,
    NoAudioError,
    ProcessingError,
    TargetLostError,
)
from focus_ml.identity import make_face_id, select_target_speaker
from focus_ml.timing import audio_window_to_roi, duration_ms_from_samples, frames_to_ms
from focus_ml.tracking import DETECT_EVERY, FACE_BOX_SCALE, match_detections
from focus_ml.windows import merge_windows, normalize_input, normalize_output, plan_windows
from focus_ml.types import ExtractionResult, FaceCandidate, ModelBundle, TargetSelection

_HEAVY_MODULES = ("torch", "cv2", "face_alignment", "soundfile")
_BACKEND_MESSAGE = "the ML engine backend is unavailable on this machine"
_FPS_WARNING = (
    "the engine timeline assumes 25 fps sources and this media's frame rate "
    "differs; canonicalize with focus_ml.normalize.normalize_input for "
    "exact candidate timestamps and ROI alignment"
)
_FPS_UNREADABLE_WARNING = (
    "the source frame rate could not be read; the 25 fps engine timeline was "
    "assumed without verification"
)
_EXPANSION_WARNING = (
    "face box expansion follows legacy Inference.face2head center math; "
    "parity with the engine was exercised end-to-end on the gt5 GPU fixtures "
    "(see the verify_gpu report) but is not bit-identical on all inputs"
)
_GPU_WARNING = (
    "separation executed on the real legacy engine (offline cached weights, "
    "local GPU) via the adapter pipeline validated by "
    "product/tools/verify_gpu.py; results are reported per run and are not "
    "claimed to be ground truth"
)
_VIDEO_ID_FALLBACK_WARNING = (
    "face identity fell back to the media file basename instead of the "
    "contract video_id; the API layer must pass the real video_id (the "
    "adapter cannot access the jobs DB)"
)
_WEIGHTS_OFFLINE_HINT = (
    "Dolphin weights were not found offline; weight downloads are forbidden, "
    "so the caller must point FOCUS_MODEL_CACHE at the populated local "
    "huggingface cache root"
)


def _backend_unavailable(detail: str) -> ModelUnavailableError:
    return ModelUnavailableError(_BACKEND_MESSAGE, detail=detail)


def _probe_heavy_imports() -> list[tuple[str, str]]:
    failures = []
    for name in _HEAVY_MODULES:
        try:
            __import__(name)
        except Exception as exc:
            failures.append((name, f"{type(exc).__name__}: {exc}"))
    return failures


def _cuda_available(torch) -> bool:
    return bool(getattr(getattr(torch, "cuda", None), "is_available", lambda: False)())


def _resolve_device(torch, requested: str) -> str:
    """Honor the configured device or fail loudly; tensors must never silently
    mismatch the model's device (raise instead of silently defaulting)."""
    if requested.startswith("cuda") and not _cuda_available(torch):
        raise _backend_unavailable(f"configured device is unavailable: {requested}")
    return requested


def _reject_downscale(cfg: AdapterConfig) -> None:
    """Downscale detection lives in legacy experiments only; silently dividing
    boxes without resizing the frame would produce wrong geometry, which
    docs/01 #5 forbids. Deferred until a validated full pipeline exists."""
    if cfg.downscale is not None:
        raise LimitError("downscale detection is not supported in this milestone")


def _hub_cache_dir(cfg: AdapterConfig) -> Optional[str]:
    """huggingface_hub treats ``cache_dir`` as the hub cache root (the
    ``models--…`` directories live directly underneath). A caller-supplied
    HF_HOME-style root therefore gets the conventional ``hub`` component
    appended; an already-``hub``-suffixed path is used unchanged."""
    if not cfg.model_cache:
        return None
    root = os.path.normpath(cfg.model_cache)
    if os.path.basename(root).lower() == "hub":
        return root
    return os.path.join(root, "hub")


def _corners_to_xywh(
    corners: Sequence[float], frame_size: tuple[int, int]
) -> tuple[tuple[int, int, int, int], bool]:
    """Legacy detections arrive as corner boxes; candidates store the contract
    convention (x, y, w, h) in ORIGINAL frame pixel coordinates. Clipping at
    frame edges and int rounding are reported via ``changed`` (docs/01 #5)."""
    width, height = frame_size
    x1, y1, x2, y2 = (
        float(corners[0]), float(corners[1]), float(corners[2]), float(corners[3])
    )
    x_raw, y_raw = min(x1, x2), min(y1, y2)
    w_raw, h_raw = abs(x2 - x1), abs(y2 - y1)
    x = max(0, int(round(x_raw)))
    y = max(0, int(round(y_raw)))
    box_w = min(width - x, int(round(w_raw)))
    box_h = min(height - y, int(round(h_raw)))
    bbox = (x, y, max(0, box_w), max(0, box_h))
    unclipped = (int(round(x_raw)), int(round(y_raw)), int(round(w_raw)), int(round(h_raw)))
    return bbox, bbox != unclipped


def _bgr_to_rgb(frame):
    import cv2  # lazy execution-time import
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def _build_first_frame_candidates(
    detections: list[list[float]],
    video_id: str,
    frame_size: tuple[int, int],
    cfg: AdapterConfig,
) -> tuple[list[FaceCandidate], int]:
    """Day-1 only: every first-frame detection becomes a candidate at index 0
    with timestamp from frames_to_ms(0). Returns (candidates, clipped_count).
    bbox convention: (x, y, w, h) in ORIGINAL frame coordinates; ``video_id``
    is the caller-supplied contract id (never a silently derived fallback)."""
    timestamp_ms = frames_to_ms(0, cfg.fps)
    candidates: list[FaceCandidate] = []
    clipped = 0
    for corners in detections:
        bbox, changed = _corners_to_xywh(corners, frame_size)
        clipped += 1 if changed else 0
        candidates.append(
            FaceCandidate(
                face_id=make_face_id(video_id, timestamp_ms, bbox, frame_size),
                timestamp_ms=timestamp_ms,
                bbox=bbox,
                frame_size=frame_size,
                index=0,
            )
        )
    return candidates, clipped


def resolve_target_speaker(
    detections: list[list[float]],
    video_id: str,
    frame_size: tuple[int, int],
    cfg: AdapterConfig,
    target: TargetSelection,
) -> tuple[int, list[FaceCandidate]]:
    """Pure seam replacing legacy ``db[:n_spk]`` order truncation: ALL first-
    frame detections become speaker slots and the target speaker is chosen BY
    IDENTITY (face_id), never by list position or first-N count. Raises
    FaceNotFoundError when no candidate identity matches."""
    candidates, _clipped = _build_first_frame_candidates(
        detections, video_id, frame_size, cfg
    )
    slot, _candidate = select_target_speaker(candidates, target)
    return slot, candidates


class LegacyDolphinAdapter:
    """Legacy engine adapter; one instance per process, single concurrency."""

    def __init__(self, config: AdapterConfig | None = None):
        self.config = config if config is not None else AdapterConfig.from_env()
        self._backend_memo: dict | None = None
        # Per-run tracking report (counts, stage times, loss events) of the most
        # recent extract_target call; also written to <job_dir>/tracking_report.json.
        self.last_tracking_report: dict | None = None

    def available(self) -> bool:
        try:
            return not _probe_heavy_imports()
        except Exception:
            return False

    def _load_backend(self, config: AdapterConfig | None = None) -> dict:
        """Activate the legacy engine for the duration of one execution: heavy
        imports plus the legacy sys.path insertion and cwd change (docs/01 #2
        style) happen here, and BOTH are restored on every exit path. During
        the call body the cwd change remains active — that is what legacy did,
        and per-request restoration is this milestone's honest compromise;
        across thread boundaries the gap remains a documented limitation.

        Fast path: if the engine modules were already imported FROM THIS SAME
        source directory (sys.modules memo), the activation is skipped — the
        imported modules hold no cwd dependency (assets are resolved from
        cfg.model_source), so no state ded is left behind."""
        cfg = config if config is not None else self.config
        failures = _probe_heavy_imports()
        if failures:
            named = ", ".join(f"{name} ({diag})" for name, diag in failures)
            raise _backend_unavailable(f"required modules failed to import: {named}")
        import torch  # lazy execution-time import

        if cfg.device.startswith("cuda") and not _cuda_available(torch):
            raise _backend_unavailable(
                "no CUDA device available; the legacy engine executes only on GPU"
            )
        source = cfg.model_source
        if not source or not os.path.isdir(source):
            raise _backend_unavailable(
                f"model source directory missing or unset (set FOCUS_MODEL_SOURCE "
                f"to the legacy Dolphin checkout): {source!r}"
            )
        if self._backend_memo is not None:
            return self._backend_memo
        inference_module = sys.modules.get("Inference")
        if inference_module is not None:
            module_file = str(getattr(inference_module, "__file__", ""))
            if not module_file or not module_file.startswith(os.path.normpath(source)):
                inference_module = None
        already_active = (
            inference_module is not None
            and "face_detection_utils" in sys.modules
            and "face_alignment" in sys.modules
            and "look2hear" in sys.modules
        )
        if already_active:
            import face_alignment as _fa_module  # lazy execution-time import

            fa = _fa_module.FaceAlignment(
                _fa_module.LandmarksType.TWO_D,
                flip_input=False,
                device=cfg.device,
                compile=False,
            )
            backend = {
                "inference": inference_module,
                "detect_faces": sys.modules["face_detection_utils"].detect_faces,
                "face_alignment": fa,
                "torch": torch,
            }
            self._backend_memo = backend
            return backend
        previous_cwd = os.getcwd()
        already_in_path = source in sys.path
        if not already_in_path:
            sys.path.insert(0, source)
        try:
            os.chdir(source)
            try:
                if "Inference" in sys.modules and inference_module is None:
                    del sys.modules["Inference"]  # imported from a different source
                import Inference as dolphin_inference  # legacy engine module
                from face_detection_utils import detect_faces  # legacy detector

                import face_alignment  # lazy execution-time import

                fa = face_alignment.FaceAlignment(
                    face_alignment.LandmarksType.TWO_D,
                    flip_input=False,
                    device=cfg.device,
                    compile=False,
                )
            except Exception as exc:
                raise _backend_unavailable(
                    f"legacy engine modules could not be imported or initialized "
                    f"from the engine checkout: {type(exc).__name__}: {exc}"
                )
            backend = {
                "inference": dolphin_inference,
                "detect_faces": detect_faces,
                "face_alignment": fa,
                "torch": torch,
            }
            self._backend_memo = backend
            return backend
        finally:
            os.chdir(previous_cwd)
            if not already_in_path:
                try:
                    sys.path.remove(source)
                except ValueError:
                    pass

    def _load_dolphin_weights(self, backend: dict, cfg: AdapterConfig) -> object:
        """Offline weight load (no network is ever possible here):
        Dolphin.from_pretrained with local_files_only=True against the
        configured cache root; mirrors legacy ``I.Dolphin.from_pretrained``.
        Any failure becomes an honest ModelUnavailableError."""
        inference = backend["inference"]
        dolphin_cls = getattr(inference, "Dolphin", None)
        if dolphin_cls is None:
            raise _backend_unavailable(
                "engine module lacks the Dolphin model class; cannot load weights"
            )
        cache_dir = _hub_cache_dir(cfg)
        kwargs: dict = {"local_files_only": True}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        try:
            return dolphin_cls.from_pretrained("JusperLee/Dolphin", **kwargs)
        except Exception as exc:
            raise _backend_unavailable(
                f"offline Dolphin weight load failed ({_WEIGHTS_OFFLINE_HINT}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def _warmup(self, backend: dict, dolphin, cfg: AdapterConfig) -> None:
        """Same warmup shape as legacy Runner._warmup: a null detector pass and
        a null forward pass so the first real request is representative."""
        import numpy as np  # lazy execution-time import

        torch = backend["torch"]
        detect_faces = backend["detect_faces"]
        dummy = np.zeros((360, 640, 3), np.uint8)
        try:
            detect_faces(dummy, threshold=0.9, allow_upscaling=False)
            with torch.inference_mode():
                dolphin(
                    torch.zeros(1, int(cfg.window_s * cfg.sample_rate), device=cfg.device),
                    torch.zeros(1, 1, 50, 88, 88, device=cfg.device),
                )
            torch.cuda.synchronize()
        except Exception as exc:
            raise _backend_unavailable(
                f"engine warmup failed on {cfg.device}: {type(exc).__name__}: {exc}"
            ) from exc

    def load_models(self, config: AdapterConfig | None = None) -> ModelBundle:
        """Load the REAL legacy engine offline: cached weights only (no
        download is possible; the call fails honestly when the local cache or
        the CUDA device is missing), warm them once, and return a fully
        loaded bundle that extraction reuses without re-importing or
        re-instantiating FaceAlignment."""
        cfg = config if config is not None else self.config
        _reject_downscale(cfg)
        failures = _probe_heavy_imports()
        if failures:
            named = ", ".join(f"{name} ({diag})" for name, diag in failures)
            raise _backend_unavailable(f"required modules failed to import: {named}")
        import torch  # lazy execution-time import

        if cfg.device.startswith("cuda") and not _cuda_available(torch):
            raise _backend_unavailable(
                "no CUDA device available; load_models cannot warm the legacy engine"
            )
        source = cfg.model_source
        if not source or not os.path.isdir(source):
            raise _backend_unavailable(
                f"model source directory missing or unset: {source!r}"
            )
        backend = self._load_backend(cfg)
        dolphin = self._load_dolphin_weights(backend, cfg)
        dolphin = dolphin.to(cfg.device)
        dolphin.eval()
        self._warmup(backend, dolphin, cfg)
        return ModelBundle(
            dolphin=dolphin,
            face_alignment=backend["face_alignment"],
            device=cfg.device,
            config=cfg,
            loaded=True,
            inference=backend["inference"],
            detect_faces=backend["detect_faces"],
        )

    def detect_candidates(
        self,
        video_path: str,
        config: AdapterConfig | None = None,
        video_id: str | None = None,
    ) -> list[FaceCandidate]:
        """Day-1 contract: candidates only from the FIRST valid detected frame
        (index 0); a target later than that requires validated engine support
        that does not exist yet.

        ``video_id`` must carry the real contract video_id from the API layer;
        when it is None this method falls back to the media file basename,
        which is NOT contract-conformant (there is no warnings channel here;
        the extraction flow flags that fallback with a warning)."""
        cfg = config if config is not None else self.config
        _reject_downscale(cfg)
        if not os.path.isfile(video_path):
            raise MediaError("media file not found", detail=f"missing: {video_path!r}")
        backend = self._load_backend(cfg)
        first = self._read_first_frame(video_path)
        if first is None:
            raise MediaError(
                "video could not be decoded", detail=f"undecodable: {video_path!r}"
            )
        bgr_frame, frame_size = first
        detections = self._detect_frame(backend["detect_faces"], _bgr_to_rgb(bgr_frame))
        if not detections:
            raise FaceNotFoundError(
                "no face detected on the first frame of the requested media",
                detail=f"media: {video_path!r}",
            )
        candidates, _clipped = _build_first_frame_candidates(
            detections,
            video_id or os.path.splitext(os.path.basename(video_path))[0],
            frame_size,
            cfg,
        )
        return candidates

    def _read_first_frame(self, video_path: str) -> Optional[tuple]:
        import cv2  # lazy execution-time import

        capture = cv2.VideoCapture(video_path)
        try:
            ok, frame = capture.read()
            if not ok or frame is None:
                return None
            return frame, (int(frame.shape[1]), int(frame.shape[0]))
        finally:
            capture.release()

    def _probe_fps(self, video_path: str) -> Optional[float]:
        import cv2  # lazy execution-time import

        capture = cv2.VideoCapture(video_path)
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
        finally:
            capture.release()
        if not fps or fps <= 0 or fps != fps:  # zero/NaN guard
            return None
        return float(fps)

    def _detect_frame(self, detect_faces, frame_rgb) -> list[list[float]]:
        """Detection parity with the legacy detect/track cycle: threshold 0.9
        without upscaling, fallback 0.7 with upscaling. Downscale back-mapping
        (legacy runner lines 128-129) is DEFERRED: cfg.downscale is rejected
        upstream because silent box-only scaling is geometrically wrong."""
        det = None
        try:
            det, _ = detect_faces(frame_rgb, threshold=0.9, allow_upscaling=False)
            if det is None or len(det) == 0:
                det, _ = detect_faces(frame_rgb, threshold=0.7, allow_upscaling=True)
        except Exception as exc:
            raise ProcessingError(
                "face detection failed on the requested media",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
        if det is None or len(det) == 0:
            return []
        return [[float(v) for v in box] for box in det]

    def extract_target(
        self,
        video_path: str,
        target: TargetSelection,
        job_dir: str,
        models: ModelBundle | None,
        on_progress: Callable[[str, float], None] | None = None,
        video_id: str | None = None,
    ) -> ExtractionResult:
        """Full extraction on the REAL legacy engine (weights already loaded
        by ``load_models``; the bundle must carry them). Pipeline ported from
        legacy focus_runner.py lines 80-233 and exercised against the gt5 GPU
        fixtures by product/tools/verify_gpu.py. Target chosen by identity.
        Precondition failures happen BEFORE any output file is created: no wav
        is ever written on failure.

        ``video_id`` must be the real contract video_id (API layer duty); None
        appends a basename-fallback warning to the result warnings."""
        timings: dict[str, float] = {}
        _reject_downscale(self.config)
        if models is None or not getattr(models, "loaded", False):
            raise _backend_unavailable(
                "models bundle is None or not loaded; load_models must succeed "
                "first (cached offline weights)"
            )
        if models.dolphin is None or getattr(models, "inference", None) is None:
            raise _backend_unavailable(
                "bundle is incomplete (no loaded Dolphin model or engine "
                "module); use the bundle returned by load_models"
            )
        if not os.path.isfile(video_path):
            raise MediaError("media file not found", detail=f"missing: {video_path!r}")
        if on_progress is not None:
            on_progress("tracking", 0.0)
        read_start = time.perf_counter()
        frames, _frame_size = self._read_frames_bgr(video_path)
        timings["read_frames"] = round(time.perf_counter() - read_start, 2)
        cfg = models.config if models.config is not None else self.config
        _reject_downscale(cfg)
        if len(frames) / cfg.fps > cfg.max_video_seconds + 1e-6:
            raise LimitError(
                f"video exceeds the {cfg.max_video_seconds}s limit "
                f"({len(frames) / cfg.fps:.2f}s at {cfg.fps}fps)"
            )
        source_fps = self._probe_fps(video_path)
        if source_fps is None:
            fps_warnings = [_FPS_UNREADABLE_WARNING]
        elif abs(source_fps - cfg.fps) > 0.05:
            fps_warnings = [
                f"source video runs at {source_fps:.2f} fps; " + _FPS_WARNING
            ]
        else:
            fps_warnings = []
        backend = self._backend_from_bundle(models, cfg)
        track_start = time.perf_counter()
        track_result = self._track_stage(backend, frames, video_path, target, cfg, video_id)
        timings["detect_track"] = round(time.perf_counter() - track_start, 2)
        tracking_report = track_result["report"]
        for key in ("full_detects", "light_tracks", "landmark_calls"):
            timings[key] = float(tracking_report.get(key, 0))
        timings["detect_s"] = float(tracking_report.get("detect_s", 0.0))
        timings["landmark_s"] = float(tracking_report.get("landmark_s", 0.0))
        tracking_report["tracking_mode"] = cfg.tracking_mode
        self.last_tracking_report = tracking_report
        mouth_start = time.perf_counter()
        mouth_roi, roi_warnings = self._mouth_roi(
            backend["inference"],
            track_result["faces_bgr"],
            track_result["landmarks"],
            cfg,
        )
        timings["mouth_roi"] = round(time.perf_counter() - mouth_start, 2)
        if on_progress is not None:
            on_progress("tracking", 1.0)

        if on_progress is not None:
            on_progress("separating", 0.0)
        audio_start = time.perf_counter()
        mix_wav = self._extract_audio(video_path, str(job_dir))
        timings["extract_audio"] = round(time.perf_counter() - audio_start, 2)
        separate_start = time.perf_counter()
        wav_path, n_samples, sr, forward_ms = self._separate(
            backend, mix_wav, mouth_roi, cfg, models.dolphin
        )
        timings["forward_cuda_ms"] = round(forward_ms, 1)
        timings["separate_wall"] = round(time.perf_counter() - separate_start, 2)
        if on_progress is not None:
            on_progress("separating", 1.0)
        self._write_tracking_report(str(job_dir), tracking_report)
        result_warnings = list(track_result["warnings"])
        result_warnings.extend(roi_warnings)
        result_warnings.extend(fps_warnings)
        result_warnings.extend([_EXPANSION_WARNING, _GPU_WARNING])
        if video_id is None:
            result_warnings.append(_VIDEO_ID_FALLBACK_WARNING)
        return ExtractionResult(
            wav_path=wav_path,
            duration_ms=duration_ms_from_samples(n_samples, sr),
            source_offset_ms=0,
            timings=timings,
            warnings=result_warnings,
        )

    @staticmethod
    def _write_tracking_report(job_dir: str, report: dict) -> None:
        import json

        os.makedirs(job_dir, exist_ok=True)
        with open(os.path.join(job_dir, "tracking_report.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=1)

    def _backend_from_bundle(self, models: ModelBundle, cfg: AdapterConfig) -> dict:
        """Reuse the already-activated engine handles instead of re-importing
        or re-instantiating FaceAlignment per request. The bundle is produced
        by ``load_models``; tensor work imports torch lazily here."""
        if self._backend_memo is not None:
            memo = self._backend_memo
            if (
                memo.get("inference") is models.inference
                and memo.get("face_alignment") is models.face_alignment
            ):
                return memo
        import torch  # lazy execution-time import

        return {
            "inference": models.inference,
            "detect_faces": models.detect_faces,
            "face_alignment": models.face_alignment,
            "torch": torch,
        }

    def _read_frames_bgr(self, video_path: str) -> tuple[list, tuple[int, int]]:
        import cv2  # lazy execution-time import

        capture = cv2.VideoCapture(video_path)
        frames = []
        try:
            while True:
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                frames.append(frame)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            capture.release()
        if not frames:
            raise MediaError(
                "video could not be decoded", detail=f"undecodable: {video_path!r}"
            )
        if width <= 0 or height <= 0:
            height, width = frames[0].shape[:2]
        return frames, (width, height)

    def _track_stage(
        self,
        backend: dict,
        frames: list,
        video_path: str,
        target: TargetSelection,
        cfg: AdapterConfig,
        video_id: str | None,
    ) -> dict:
        """Port of the legacy detect/track cycle with the legacy cadence,
        hold-last behavior and face2head expansion (legacy runner lines
        108-171); exercised on GPU against the gt5 fixtures by verify_gpu.

        Identity selection (replaces legacy ``db[:n_spk]``): all first-frame
        detections become speaker slots, chosen by face_id identity via
        ``select_target_speaker``. Detection cadence: every cfg.detect_every
        frames; on NON-detection frames the CACHED detections of the last
        detection cycle are fed to match_detections (legacy else-branch
        behavior where ``detected`` persists between cycles)."""
        inference = backend["inference"]
        detect_faces = backend["detect_faces"]
        detections0 = self._detect_frame(detect_faces, _bgr_to_rgb(frames[0]))
        if not detections0:
            raise FaceNotFoundError(
                "no face detected on the first frame of the requested media",
                detail=f"media: {video_path!r}",
            )
        effective_video_id = (
            video_id if video_id else os.path.splitext(os.path.basename(video_path))[0]
        )
        stage_warnings: list[str] = []
        candidates, clipped = _build_first_frame_candidates(
            detections0, effective_video_id,
            (frames[0].shape[1], frames[0].shape[0]), cfg,
        )
        if clipped:
            stage_warnings.append(
                f"{clipped} detection box(es) were clipped or rounded to the "
                f"frame bounds when converting to original-coordinate xywh"
            )
        speaker_slot, _target_candidate = select_target_speaker(candidates, target)
        n_spk = len(candidates)
        detect_every = cfg.detect_every if cfg.detect_every else DETECT_EVERY
        speaker_boxes = [
            inference.face2head([box], FACE_BOX_SCALE)[0] for box in detections0
        ]
        boxes_history = [[box] for box in speaker_boxes]
        target_reacquired = False
        any_detection_after_first = False
        cached_detected: list = []
        if cfg.tracking_mode == "adaptive":
            adaptive_boxes, report, adaptive_warnings = self._adaptive_boxes(
                backend, frames, speaker_boxes[speaker_slot], cfg
            )
            boxes_history = [[] for _ in range(n_spk)]
            boxes_history[speaker_slot] = adaptive_boxes
            stage_warnings.extend(adaptive_warnings)
            faces_bgr, landmarks, lm_stats = self._finalize_track(
                backend, frames, boxes_history, speaker_slot, cfg
            )
            report.update(lm_stats)
            return {
                "faces_bgr": faces_bgr, "landmarks": landmarks,
                "warnings": stage_warnings, "report": report,
                "boxes": list(boxes_history[speaker_slot]),
            }
        ref_stats = {"mode": "reference", "frames": len(frames), "full_detects": 1,
                     "light_tracks": 0, "hold_frames": 0, "detect_s": 0.0,
                     "events": [], "loss_intervals": []}
        for i in range(1, len(frames)):
            if i % detect_every == 0:
                detect_started = time.perf_counter()
                current = self._detect_frame(detect_faces, _bgr_to_rgb(frames[i]))
                ref_stats["detect_s"] = round(
                    ref_stats["detect_s"] + time.perf_counter() - detect_started, 4
                )
                ref_stats["full_detects"] += 1
                cached_detected = [
                    inference.face2head([box], FACE_BOX_SCALE)[0] for box in current
                ]
                if cached_detected:
                    any_detection_after_first = True
            previous = [history[-1] for history in boxes_history]
            matched = match_detections(previous, cached_detected, 0.0)
            new_box = matched[speaker_slot]
            if new_box is not None and new_box is not previous[speaker_slot]:
                target_reacquired = True
            for speaker in range(n_spk):
                boxes_history[speaker].append(matched[speaker])
        if not any_detection_after_first:
            stage_warnings.append(
                "tracker never re-detected any face after the first frame; the "
                "target box was held from the first frame for the whole clip"
            )
        elif not target_reacquired:
            raise TargetLostError(
                "the selected face was never re-matched by the tracker after "
                "the first frame"
            )
        faces_bgr, landmarks, lm_stats = self._finalize_track(
            backend, frames, boxes_history, speaker_slot, cfg
        )
        ref_stats.update(lm_stats)
        return {
            "faces_bgr": faces_bgr, "landmarks": landmarks,
            "warnings": stage_warnings, "report": ref_stats,
            "boxes": list(boxes_history[speaker_slot]),
        }

    def _adaptive_boxes(self, backend, frames, first_box, cfg) -> tuple[list, dict, list]:
        """Opt-in adaptive tracking of the TARGET only (see adaptive_tracking).
        Returns (per-frame boxes, report, warnings). Unvalidated on a GPU."""
        from focus_ml.light_tracker import template_box_tracker  # lazy (needs cv2)

        inference = backend["inference"]
        detect_faces = backend["detect_faces"]

        def detect(frame):
            found = self._detect_frame(detect_faces, _bgr_to_rgb(frame))
            return [inference.face2head([box], FACE_BOX_SCALE)[0] for box in found]

        tracker = AdaptiveFaceTracker(
            AdaptiveConfig(
                min_confidence=cfg.adaptive_min_confidence,
                max_interval=cfg.adaptive_max_interval,
                edge_interval=min(cfg.adaptive_edge_interval, cfg.adaptive_max_interval),
                identity_iou_min=cfg.adaptive_identity_iou,
                max_hold_frames=cfg.adaptive_max_hold_frames,
                fps=cfg.fps,
            ),
            (int(frames[0].shape[1]), int(frames[0].shape[0])),
            detect,
            template_box_tracker,
        )
        boxes = [tracker.start(frames[0], first_box).box]
        for i in range(1, len(frames)):
            boxes.append(tracker.step(i, frames[i]).box)
        tracker.finalize()
        report = tracker.report()
        warnings = [
            f"target {'lost' if loss['declared_lost'] else 'uncertain'} from "
            f"{loss['start_ms']} ms to {loss['end_ms']} ms ({loss['reason']}); "
            f"the last known face box was held"
            for loss in report["loss_intervals"]
        ]
        return boxes, report, warnings

    def _finalize_track(
        self, backend: dict, frames: list, boxes_history, speaker_slot: int, cfg
    ) -> tuple[list, list, dict]:
        """Port of legacy runner lines 139-170 order (GPU-exercised): the
        detector frame is converted to RGB ONCE per use, the landmarker
        receives RGB, and the stored face crop is pixels[..., ::-1] (BGR)
        because the downstream mouth-ROI converter consumes BGR. Landmark
        cycles run every cfg.landmark_every frames; between cycles the last
        landmark is held (legacy default landmark_every=1 landmarks every
        frame)."""
        import numpy as np  # lazy execution-time import

        fa = self._landmarker(backend, cfg)
        from PIL import Image  # lazy execution-time import

        target_history = boxes_history[speaker_slot]
        faces, landmarks = [], []
        lm_calls, lm_seconds = 0, 0.0
        for frame_index, frame in enumerate(frames):
            frame_rgb = _bgr_to_rgb(frame)
            box = target_history[frame_index]
            crop = (
                Image.fromarray(frame_rgb)
                .crop((box[0], box[1], box[2], box[3]))
                .resize((224, 224))
            )
            pixels_rgb = np.asarray(crop)
            landmark_cycle = frame_index % cfg.landmark_every == 0 or not landmarks
            if landmark_cycle:
                lm_started = time.perf_counter()
                preds = fa.get_landmarks(pixels_rgb)
                lm_seconds += time.perf_counter() - lm_started
                lm_calls += 1
                if preds is None or len(preds) == 0:
                    if frame_index == 0:
                        raise FaceNotFoundError(
                            "no face landmarks on the first frame for the "
                            "selected face"
                        )
                    current = landmarks[-1]
                else:
                    current = preds[0]
            else:
                current = landmarks[-1]
            faces.append(pixels_rgb[..., ::-1])
            landmarks.append(current)
        return faces, landmarks, {
            "landmark_calls": lm_calls, "landmark_s": round(lm_seconds, 4),
        }

    def _landmarker(self, backend: dict, cfg):
        """face_alignment (reference) or the fast MediaPipe landmarker, which
        is created once and cached on the adapter."""
        if cfg.landmark_backend != "mediapipe":
            return backend["face_alignment"]
        cached = getattr(self, "_fast_landmarker", None)
        if cached is None or cached[0] != cfg.landmarker_model:
            from focus_ml.fast_landmarks import MediaPipeLandmarker  # lazy

            cached = (cfg.landmarker_model, MediaPipeLandmarker(cfg.landmarker_model))
            self._fast_landmarker = cached
        return cached[1]

    def _mouth_roi(self, inference, faces_bgr, lms, cfg) -> tuple[object, list[str]]:
        """Port of legacy ``crop_patch_frames`` + gray conversion for the
        TARGET speaker slot (legacy ``_separate`` read mouth_roi[0]; identity
        selection now supplies the correct slot). GPU-exercised on the gt5
        fixtures. Engine asset is loaded via cfg.model_source absolute path —
        never os.getcwd() — because cwd restoration makes the process cwd
        unreliable here."""
        import numpy as np  # lazy execution-time import

        root = cfg.model_source or os.getcwd()
        mean_face = np.load(os.path.join(root, "assets", "20words_mean_face.npy"))
        roi_warnings: list[str] = []
        stable = [33, 36, 39, 42, 45]
        window_margin, start_idx, stop_idx, crop_h, crop_w, std_size = (
            12, 48, 68, 96, 96, (256, 256)
        )
        if hasattr(inference, "landmarks_interpolate"):
            pre = inference.landmarks_interpolate(list(lms))
        else:
            pre = list(lms)
            roi_warnings.append(
                "engine lacks landmarks_interpolate; non-interpolated landmarks "
                "feed the mouth ROI, which may degrade quality"
            )
        if pre is None:
            raise ProcessingError(
                "mouth ROI tracking failed for the selected face identity "
                "(landmark interpolation found no usable segments)"
            )
        q_frame, q_lm, seq = [], [], []
        trans = None
        for fi, frame in enumerate(faces_bgr):
            q_lm.append(pre[fi])
            q_frame.append(frame)
            if len(q_frame) == window_margin:
                smoothed = np.mean(q_lm, axis=0)
                cur_lm = q_lm.pop(0)
                cur_frame = q_frame.pop(0)
                tf_frame, trans = inference.warp_img(
                    smoothed[stable, :], mean_face[stable, :], cur_frame, std_size
                )
                seq.append(
                    inference.cut_patch(
                        tf_frame, trans(cur_lm)[start_idx:stop_idx],
                        crop_h // 2, crop_w // 2,
                    )
                )
            if fi == len(pre) - 1:
                if len(pre) < window_margin:
                    smoothed = np.mean(q_lm, axis=0)
                    cur_lm = q_lm.pop(0)
                    cur_frame = q_frame.pop(0)
                    tf_frame, trans = inference.warp_img(
                        smoothed[stable, :], mean_face[stable, :], cur_frame, std_size
                    )
                    seq.append(
                        inference.cut_patch(
                            tf_frame, trans(cur_lm)[start_idx:stop_idx],
                            crop_h // 2, crop_w // 2,
                        )
                    )
                while q_frame:
                    cur_frame = q_frame.pop(0)
                    tf_frame = inference.apply_transform(trans, cur_frame, std_size)
                    tlm = trans(q_lm.pop(0))
                    seq.append(
                        inference.cut_patch(
                            tf_frame, tlm[start_idx:stop_idx],
                            crop_h // 2, crop_w // 2,
                        )
                    )
                break
        if not seq:
            raise FaceNotFoundError(
                "mouth ROI could not be built for the selected face identity"
            )
        return inference.convert_bgr2gray(np.array(seq)), roi_warnings

    def _extract_audio(self, video_path: str, job_dir: str) -> str:
        """ffmpeg 16k mono WAV into job_dir (legacy runner command shape).
        NoAudioError when the media carries no audio stream (empty/missing
        output or ffmpeg stderr naming a stream problem); MediaError when the
        media is corrupt; ProcessingError for other ffmpeg/tool failures.
        No placeholder wav is ever written on failure; stderr text stays in
        ``detail`` and never in the user-facing message."""
        os.makedirs(job_dir, exist_ok=True)
        out = os.path.join(job_dir, "mix.wav")
        try:
            import imageio_ffmpeg  # lazy execution-time import

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = "ffmpeg"
        stderr = ""
        try:
            completed = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", video_path,
                 "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", out],
                capture_output=True, text=True,
            )
        except (OSError, FileNotFoundError) as exc:
            raise ProcessingError(
                "audio extraction tool unavailable",
                retryable=False,
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
        stderr = (completed.stderr or "").lower()
        if completed.returncode != 0:
            if "invalid data found" in stderr:
                raise MediaError(
                    "the uploaded media is invalid or corrupt",
                    detail=f"ffmpeg: {stderr.strip()}",
                )
            if "audio" in stderr or "stream" in stderr:
                raise NoAudioError(
                    "no extractable audio stream in the uploaded media",
                    detail=f"ffmpeg: {stderr.strip()}",
                )
            raise ProcessingError(
                "audio extraction failed", detail=f"ffmpeg: {stderr.strip()}"
            )
        if not os.path.isfile(out) or os.path.getsize(out) == 0:
            raise NoAudioError("no audio stream produced from the uploaded media")
        return out

    def _separate(self, backend: dict, mix_wav: str, mouth_roi, cfg: AdapterConfig, dolphin):
        """Windowed separation, matching the legacy _separate stage exactly
        (legacy focus_runner.py lines 182-206): the TARGET speaker's ROI goes
        through ``I.get_preprocessing_pipelines()["val"]`` ONCE, each audio
        window maps to ROI frames via ``sf_ = int(start/sr*25)`` /
        ``ef = min(int(end/sr*25), len(mr))``, the window ROI is cast to float,
        mix and ROI live on the SAME device as the model, and forward timing
        uses CUDA events with a synchronize per window. Returns
        (wav_path, n_samples, sr, forward_cuda_ms)."""
        import numpy as np  # lazy execution-time import
        import soundfile as sf  # lazy execution-time import

        inference = backend["inference"]
        torch = backend["torch"]
        pipelines = getattr(inference, "get_preprocessing_pipelines", None)
        if pipelines is None:
            raise _backend_unavailable(
                "engine lacks get_preprocessing_pipelines; the legacy "
                "preprocessing step cannot be reproduced"
            )
        prepared_roi = pipelines()["val"](mouth_roi)
        data, sr = sf.read(mix_wav, dtype="float32", always_2d=True)
        device = torch.device(_resolve_device(torch, cfg.device))
        mix_np = np.ascontiguousarray(data.mean(axis=1))
        if cfg.normalize_audio:
            mix_np, _gain_db = normalize_input(mix_np)
        mix = torch.from_numpy(mix_np).to(device)
        overlap = 0.0 if cfg.merge == "direct" else cfg.window_overlap
        spans = plan_windows(len(mix), cfg.sample_rate, cfg.window_s, overlap)
        estimates = []
        forward_ms = 0.0
        for start, end in spans:
            roi_start, roi_end = audio_window_to_roi(
                start, end, cfg.sample_rate, cfg.fps, roi_len=len(prepared_roi)
            )
            window_roi = (
                torch.from_numpy(
                    np.ascontiguousarray(prepared_roi[roi_start:roi_end])
                )[None, None]
                .float()
                .to(device)
            )
            e0 = torch.cuda.Event(enable_timing=True)
            e1 = torch.cuda.Event(enable_timing=True)
            e0.record()
            with torch.inference_mode():
                est = dolphin(mix[start:end][None], window_roi)
            e1.record()
            torch.cuda.synchronize()
            forward_ms += e0.elapsed_time(e1)
            estimates.append(est[0, 0, : end - start].detach().cpu().numpy())
        merged = merge_windows(estimates, spans, len(mix))
        if cfg.normalize_audio:
            merged, _ = normalize_output(merged)
        result = merged
        out_wav = os.path.join(os.path.dirname(mix_wav), "target_extract.wav")
        sf.write(out_wav, result, sr, subtype="PCM_16")
        return out_wav, len(mix), sr, forward_ms


def load_models(config: AdapterConfig | None = None) -> ModelBundle:
    return LegacyDolphinAdapter(config=config).load_models(config=config)


def detect_candidates(
    video_path: str,
    config: AdapterConfig | None = None,
    video_id: str | None = None,
) -> list[FaceCandidate]:
    return LegacyDolphinAdapter(config=config).detect_candidates(
        video_path, config, video_id
    )


def extract_target(
    video_path: str,
    target: TargetSelection,
    job_dir: str,
    models: ModelBundle | None,
    on_progress: Callable[[str, float], None] | None = None,
    video_id: str | None = None,
) -> ExtractionResult:
    config = models.config if models is not None and models.config is not None else None
    return LegacyDolphinAdapter(config=config).extract_target(
        video_path, target, job_dir, models, on_progress, video_id
    )
