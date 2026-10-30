"""Dolphin-backed ``StreamBackend``: per-frame tracking, landmarks and mouth ROI.

Reuses the adapter's handles and legacy helpers (face2head, warp_img, cut_patch,
preprocessing pipeline) so quality tracks the upload path. Differences from the
upload path, both to be judged by the SI-SDRi gate and recorded in the report:
  * the 12-frame landmark smoothing is centred (6 frames of lookahead) instead of
    forward-looking, and landmarks are not interpolated (a missed landmark holds
    the previous one);
  * the window is ``StreamConfig.window_s`` (default 4 s) instead of 2 s.
NOT validated on a GPU in this repository.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from focus_ml.adaptive_tracking import STATE_LOST, AdaptiveConfig, AdaptiveFaceTracker
from focus_ml.errors import FaceNotFoundError, ProcessingError
from focus_ml.timing import audio_window_to_roi
from focus_ml.tracking import FACE_BOX_SCALE

SMOOTH_BEFORE, SMOOTH_AFTER = 5, 6  # 12-frame window, centred
STABLE = [33, 36, 39, 42, 45]


@dataclass(frozen=True)
class AccelOptions:
    fp16: bool = True
    compile: bool = False


class DolphinStreamBackend:
    def __init__(self, engine, accel: AccelOptions | None = None):
        engine.initialize()
        self.engine, self.accel = engine, accel or AccelOptions()
        self.cfg = engine.models.config or engine.config
        self.backend = engine.adapter._backend_from_bundle(engine.models, self.cfg)
        self.dolphin = engine.models.dolphin
        self.accel_report = {"fp16": self.accel.fp16, "compile": "off",
                             "onnx_tensorrt": "not attempted"}
        if self.accel.compile:
            try:
                self.backend["torch"].compile  # noqa: B018 - presence check
                self.dolphin = self.backend["torch"].compile(self.dolphin)
                self.accel_report["compile"] = "on"
            except Exception as exc:  # explicit, never silent
                self.accel_report["compile"] = f"failed: {type(exc).__name__}"
        self._reset()

    def _reset(self):
        self.tracker = None
        self.first = 0
        self._lm, self._crops, self._roi = {}, {}, {}
        self._last_lm = None
        self._count_to = 0  # frames [first, _count_to) have landmarks
        self._roi_to = 0
        self._finishing = False
        self._mean_face = None
        self._pipeline = None

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _decode(jpeg: bytes):
        import cv2

        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ProcessingError("a camera frame could not be decoded", retryable=False)
        return frame

    def _detect_boxes(self, frame):
        from focus_ml.adapter import _bgr_to_rgb

        a = self.engine.adapter
        return a._detect_frame(self.backend["detect_faces"], _bgr_to_rgb(frame))

    # -- StreamBackend -------------------------------------------------------
    def detect(self, jpeg: bytes) -> list[dict]:
        import cv2
        from focus_ml.adapter import _build_first_frame_candidates

        frame = self._decode(jpeg)
        boxes = self._detect_boxes(frame)
        h, w = frame.shape[:2]
        cands, _ = _build_first_frame_candidates(boxes, "live", (w, h), self.cfg)
        out = []
        for c in cands:
            x, y, bw, bh = c.bbox
            crop = frame[y:y + bh, x:x + bw]
            if crop.size == 0:
                continue
            scale = min(1.0, 192 / max(bw, bh))
            crop = cv2.resize(crop, (max(1, round(bw * scale)), max(1, round(bh * scale))))
            ok, enc = cv2.imencode(".jpg", crop)
            if ok:
                out.append({"bbox": list(c.bbox), "frame_size": [w, h],
                            "thumbnail": base64.b64encode(enc.tobytes()).decode("ascii")})
        return out

    def begin(self, index: int, jpeg: bytes, bbox: Sequence[int]) -> None:
        self._reset()
        frame = self._decode(jpeg)
        x, y, w, h = bbox
        inference = self.backend["inference"]
        head = inference.face2head([[x, y, x + w, y + h]], FACE_BOX_SCALE)[0]
        c = self.cfg
        self.tracker = AdaptiveFaceTracker(
            AdaptiveConfig(
                min_confidence=c.adaptive_min_confidence, max_interval=c.adaptive_max_interval,
                edge_interval=min(c.adaptive_edge_interval, c.adaptive_max_interval),
                identity_iou_min=c.adaptive_identity_iou, max_hold_frames=c.adaptive_max_hold_frames,
                fps=c.fps),
            (frame.shape[1], frame.shape[0]),
            lambda f: [inference.face2head([b], FACE_BOX_SCALE)[0] for b in self._detect_boxes(f)],
            self._template_tracker(),
        )
        self.first = self._count_to = self._roi_to = index
        self._mean_face = np.load(os.path.join(self.cfg.model_source or os.getcwd(),
                                               "assets", "20words_mean_face.npy"))
        self._pipeline = inference.get_preprocessing_pipelines()["val"]
        step = self.tracker.start(frame, head)
        if not self._landmarks(index, frame, step.box):
            raise FaceNotFoundError("no face landmarks on the selected face")
        self._advance_roi()

    @staticmethod
    def _template_tracker():
        from focus_ml.light_tracker import template_box_tracker
        return template_box_tracker

    def _landmarks(self, index, frame, box) -> bool:
        import cv2

        crop = cv2.resize(frame[max(0, int(box[1])):int(box[3]), max(0, int(box[0])):int(box[2])],
                          (224, 224))
        if crop.size == 0:
            return False
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        preds = self.backend["face_alignment"].get_landmarks(rgb)
        found = preds is not None and len(preds) > 0
        if found:
            self._last_lm = preds[0]
        if self._last_lm is None:
            return False
        self._lm[index], self._crops[index] = self._last_lm, crop
        self._count_to = index + 1
        return True

    def push_frame(self, index: int, jpeg: bytes) -> str:
        frame = self._decode(jpeg)
        step = self.tracker.step(index, frame)
        self._landmarks(index, frame, step.box)
        self._advance_roi()
        return step.state

    def hold(self, index: int) -> str:
        if self._last_lm is not None and self._crops:
            last = max(self._crops)
            self._lm[index], self._crops[index] = self._last_lm, self._crops[last]
            self._count_to = index + 1
            self._advance_roi()
        return STATE_LOST

    def _advance_roi(self):
        inference = self.backend["inference"]
        while self._roi_to < self._count_to and (
            self._finishing or self._roi_to + SMOOTH_AFTER < self._count_to
        ):
            i = self._roi_to
            lo, hi = max(self.first, i - SMOOTH_BEFORE), min(self._count_to, i + SMOOTH_AFTER + 1)
            smoothed = np.mean([self._lm[k] for k in range(lo, hi)], axis=0)
            tf_frame, trans = inference.warp_img(
                smoothed[STABLE, :], self._mean_face[STABLE, :], self._crops[i], (256, 256))
            patch = inference.cut_patch(tf_frame, trans(self._lm[i])[48:68], 48, 48)
            self._roi[i] = inference.convert_bgr2gray(np.array([patch]))[0]
            self._roi_to += 1

    def roi_ready(self) -> int:
        return self._roi_to

    def finish(self) -> None:
        self._finishing = True
        self._advance_roi()

    def trim(self, before_frame: int) -> None:
        keep = before_frame - SMOOTH_BEFORE
        for store in (self._roi, self._lm, self._crops):
            for k in [k for k in store if k < keep]:
                del store[k]

    def isolate(self, audio: np.ndarray, first_frame: int, last_frame: int) -> np.ndarray:
        torch = self.backend["torch"]
        frames = [self._roi[i] for i in range(first_frame, min(last_frame, self._roi_to))]
        if not frames:
            raise ProcessingError("no mouth region available for this window", retryable=False)
        prepared = self._pipeline(np.array(frames))
        device = next(self.dolphin.parameters()).device if hasattr(self.dolphin, "parameters") \
            else torch.device(self.cfg.device)
        mix = torch.from_numpy(np.ascontiguousarray(audio)).to(device)
        a, b = audio_window_to_roi(0, len(audio), self.cfg.sample_rate, self.cfg.fps,
                                   roi_len=len(prepared))
        roi = torch.from_numpy(np.ascontiguousarray(prepared[a:b]))[None, None].float().to(device)
        with torch.inference_mode():
            if self.accel.fp16 and device.type == "cuda":
                with torch.autocast("cuda", dtype=torch.float16):
                    est = self.dolphin(mix[None], roi)
            else:
                est = self.dolphin(mix[None], roi)
        return est[0, 0, :len(audio)].float().detach().cpu().numpy()
