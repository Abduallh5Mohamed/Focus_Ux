"""FOCUS persistent runner (R8 speed/quality round).

Keeps face_alignment + retinaface + Dolphin loaded across requests. Direct frame path:
faces are kept in memory (no intermediate faces/*.mp4 encode+decode), mouth ROI is cropped
from those frames, audio-only WAV is written as soon as separation finishes (MP4 optional).
One selected speaker. Optional downscaled detection (boxes mapped back to original).

Modes:
  python focus_runner.py --bench --video ... --out ... --targets 1 --reps 3
Prints a JSON with per-stage timings for the cold request + each warm request.
"""
import argparse
import gc
import json
import os
import sys
import time
from collections import deque

import numpy as np
import torch

DOLPHIN = "A:/focus/Dolphin"
sys.path.insert(0, DOLPHIN)
os.chdir(DOLPHIN)

import subprocess  # noqa: E402

import cv2  # noqa: E402
import face_alignment  # noqa: E402
import imageio_ffmpeg  # noqa: E402
import soundfile as sf  # noqa: E402
from PIL import Image  # noqa: E402
from moviepy import VideoFileClip  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()

import Inference as I  # noqa: E402
from face_detection_utils import detect_faces  # noqa: E402

STABLE = [33, 36, 39, 42, 45]
MEAN_FACE = np.load("assets/20words_mean_face.npy")


def crop_patch_frames(frames_bgr, landmarks, window_margin, start_idx, stop_idx,
                      crop_h, crop_w, std_size=(256, 256)):
    """crop_patch but over in-memory BGR frames (no face-video decode)."""
    q_frame, q_lm = deque(), deque()
    seq = []
    trans = None
    for fi, frame in enumerate(frames_bgr):
        q_lm.append(landmarks[fi])
        q_frame.append(frame)
        if len(q_frame) == window_margin:
            smoothed = np.mean(q_lm, axis=0)
            cur_lm = q_lm.popleft()
            cur_frame = q_frame.popleft()
            tf_frame, trans = I.warp_img(smoothed[STABLE, :], MEAN_FACE[STABLE, :],
                                         cur_frame, std_size)
            tlm = trans(cur_lm)
            seq.append(I.cut_patch(tf_frame, tlm[start_idx:stop_idx], crop_h // 2, crop_w // 2))
        if fi == len(landmarks) - 1:
            if len(landmarks) < window_margin:
                smoothed = np.mean(q_lm, axis=0)
                cur_lm = q_lm.popleft()
                cur_frame = q_frame.popleft()
                tf_frame, trans = I.warp_img(smoothed[STABLE, :], MEAN_FACE[STABLE, :],
                                             cur_frame, std_size)
                tlm = trans(cur_lm)
                seq.append(I.cut_patch(tf_frame, tlm[start_idx:stop_idx], crop_h // 2, crop_w // 2))
            while q_frame:
                cur_frame = q_frame.popleft()
                tf_frame = I.apply_transform(trans, cur_frame, std_size)
                tlm = trans(q_lm.popleft())
                seq.append(I.cut_patch(tf_frame, tlm[start_idx:stop_idx], crop_h // 2, crop_w // 2))
            return np.array(seq)
    return None


class Runner:
    def __init__(self, window_s=2.0, downscale=None, device="cuda"):
        self.device = torch.device(device)
        t = time.perf_counter()
        self.fa = face_alignment.FaceAlignment(face_alignment.LandmarksType.TWO_D,
                                               flip_input=False, device=str(self.device),
                                               compile=False)
        self.dolphin = I.Dolphin.from_pretrained("JusperLee/Dolphin").to(self.device)
        self.dolphin.eval()
        self.window = int(window_s * 16000)
        self.downscale = downscale
        self.init_s = round(time.perf_counter() - t, 2)
        self._warmup()

    def _warmup(self):
        dummy = np.zeros((360, 640, 3), np.uint8)
        detect_faces(dummy, threshold=0.9, allow_upscaling=False)
        with torch.inference_mode():
            self.dolphin(torch.zeros(1, self.window, device=self.device),
                         torch.zeros(1, 1, 50, 88, 88, device=self.device))
        torch.cuda.synchronize()

    def _read_frames(self, path):
        clip = VideoFileClip(path)
        frames = [np.array(f) for f in clip.iter_frames()]  # RGB
        clip.close()
        return frames

    def _detect_track(self, frames, n_spk):
        """Replicate detectface tracking; return per-speaker BGR face crops + landmarks."""
        faces = [[] for _ in range(n_spk)]
        lms = [[] for _ in range(n_spk)]
        boxes = [[] for _ in range(n_spk)]
        det_every = 8
        detected = []
        for i, frame_rgb in enumerate(frames):
            if i % det_every == 0:
                img = frame_rgb
                scale = 1.0
                if self.downscale:
                    scale = self.downscale
                    h, w = img.shape[:2]
                    img = cv2.resize(img, (int(w * scale), int(h * scale)))
                db, _ = detect_faces(img, threshold=0.9, allow_upscaling=False)
                if db is None or len(db) == 0:
                    db, _ = detect_faces(img, threshold=0.7, allow_upscaling=True)
                if db is not None and len(db) > 0:
                    db = db[:n_spk]
                    if self.downscale:
                        db = db / scale
                    db = I.face2head(db, 1.5)
                else:
                    db = []
                detected = db
            if i == 0:
                if len(detected) < n_spk:
                    raise ValueError(f"frame0 faces {len(detected)} < {n_spk}")
                for j in range(n_spk):
                    box = detected[j]
                    face = Image.fromarray(frame_rgb).crop((box[0], box[1], box[2], box[3])).resize((224, 224))
                    preds = self.fa.get_landmarks(np.array(face))
                    if preds is None or len(preds) == 0:
                        raise ValueError(f"no landmarks in frame0 for speaker {j}")
                    faces[j].append(np.array(face)[..., ::-1])  # BGR
                    lms[j].append(preds[0])  # (68,2)
                    boxes[j].append(box)
            else:
                matched = set()
                spk_boxes = [None] * n_spk
                for box in detected:
                    ious = []
                    for s in range(n_spk):
                        if s in matched:
                            ious.append(-1)
                        else:
                            ious.append(I.bb_intersection_over_union(box, boxes[s][-1]))
                    if max(ious) > 0:
                        best = ious.index(max(ious))
                        spk_boxes[best] = box
                        matched.add(best)
                for s in range(n_spk):
                    box = spk_boxes[s] if spk_boxes[s] is not None else boxes[s][-1]
                    face = Image.fromarray(frame_rgb).crop((box[0], box[1], box[2], box[3])).resize((224, 224))
                    preds = self.fa.get_landmarks(np.array(face))
                    if preds is None or len(preds) == 0:
                        preds = lms[s][-1]
                    else:
                        preds = preds[0]
                    faces[s].append(np.array(face)[..., ::-1])
                    lms[s].append(preds)
                    boxes[s].append(box)
        return faces, lms

    def _mouth(self, faces, lms):
        roi = []
        for s in range(len(faces)):
            pre = I.landmarks_interpolate(lms[s])
            seq = crop_patch_frames(faces[s], pre, 12, 48, 68, 96, 96)
            seq = I.convert_bgr2gray(seq)  # (T,96,96) uint8, matches crop_mouth(convert_gray=True)
            roi.append(seq)
        return roi

    def _separate(self, audio_path, mouth_roi):
        data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
        mix = torch.from_numpy(data.mean(axis=1)).to(self.device)
        mr = I.get_preprocessing_pipelines()["val"](mouth_roi[0])
        out = torch.zeros(1, len(mix))
        start = 0
        fwd = 0.0
        while start < len(mix):
            end = min(start + self.window, len(mix))
            wm = mix[start:end]
            sf_ = int(start / sr * 25)
            ef = min(int(end / sr * 25), len(mr))
            wmr = mr[sf_:ef]
            e0 = torch.cuda.Event(enable_timing=True)
            e1 = torch.cuda.Event(enable_timing=True)
            e0.record()
            with torch.inference_mode():
                est = self.dolphin(wm[None], torch.from_numpy(wmr[None, None]).float().to(self.device))
            e1.record()
            torch.cuda.synchronize()
            fwd += e0.elapsed_time(e1)
            wl = end - start
            out[0, start:end] = est[0, 0, :wl].cpu()
            start += self.window
        return out[0].numpy(), sr, fwd

    def run(self, video, out_wav, mp4=False):
        T = {}
        t = time.perf_counter()
        frames = self._read_frames(video)
        T["read_frames"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        faces, lms = self._detect_track(frames, 1)
        T["detect_track"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        roi = self._mouth(faces, lms)
        T["mouth_roi"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        tmp = out_wav + ".mix.wav"
        subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", video,
                        "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", tmp], check=True)
        T["extract_audio"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        y, sr, fwd = self._separate(tmp, roi)
        T["forward_cuda_ms"] = round(fwd, 1)
        T["separate_wall"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        sf.write(out_wav, y, sr, subtype="PCM_16")
        T["write_wav"] = round(time.perf_counter() - t, 2)
        if mp4:
            pass  # optional, outside audio-ready time
        return T, y


def bench(video, out, window, downscale, reps):
    r = Runner(window_s=window, downscale=downscale)
    res = {"init_s": r.init_s, "window": window, "downscale": downscale, "requests": []}
    torch.cuda.reset_peak_memory_stats()
    t = time.perf_counter()
    T, _ = r.run(video, out + "_cold.wav")
    T["wall"] = round(time.perf_counter() - t, 2)
    T["cold"] = True
    res["requests"].append(T)
    for k in range(reps):
        t = time.perf_counter()
        T, _ = r.run(video, out + f"_warm{k}.wav")
        T["wall"] = round(time.perf_counter() - t, 2)
        T["cold"] = False
        res["requests"].append(T)
    res["peak_vram_mib"] = round(torch.cuda.max_memory_allocated() / 1024 ** 2, 1)
    res["peak_reserved_mib"] = round(torch.cuda.max_memory_reserved() / 1024 ** 2, 1)
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--downscale", type=float, default=None)
    ap.add_argument("--reps", type=int, default=3)
    a = ap.parse_args()
    r = bench(a.video, a.out, a.window, a.downscale, a.reps)
    json.dump(r, open(a.out + "_bench.json", "w"), indent=1)
