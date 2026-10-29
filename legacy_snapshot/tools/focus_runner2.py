"""FOCUS runner v2 (R9 face-prep speed round).

Same quality path as focus_runner.py (2s window, direct merge, single person, audio-only) but:
- fine-grained timing: video read, retinaface (total/calls), face_alignment (total/calls),
  tracking, mouth ROI, GPU transfer, forward, merge/write, wall.
- --detect-every N  (detect every N frames, track between; re-detect on tracking loss)
- --landmark-every N (compute landmarks every N frames, linearly interpolate between)
- --downscale X (kept for the B investigation)
Keeps the previous runner intact.
"""
import argparse
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

import Inference as I  # noqa: E402
from face_detection_utils import detect_faces  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
STABLE = [33, 36, 39, 42, 45]
MEAN_FACE = np.load("assets/20words_mean_face.npy")


def crop_patch_frames(frames_bgr, landmarks, window_margin, start_idx, stop_idx, crop_h, crop_w,
                      std_size=(256, 256)):
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
            tf_frame, trans = I.warp_img(smoothed[STABLE, :], MEAN_FACE[STABLE, :], cur_frame, std_size)
            tlm = trans(cur_lm)
            seq.append(I.cut_patch(tf_frame, tlm[start_idx:stop_idx], crop_h // 2, crop_w // 2))
        if fi == len(landmarks) - 1:
            if len(landmarks) < window_margin:
                smoothed = np.mean(q_lm, axis=0)
                cur_lm = q_lm.popleft()
                cur_frame = q_frame.popleft()
                tf_frame, trans = I.warp_img(smoothed[STABLE, :], MEAN_FACE[STABLE, :], cur_frame, std_size)
                tlm = trans(cur_lm)
                seq.append(I.cut_patch(tf_frame, tlm[start_idx:stop_idx], crop_h // 2, crop_w // 2))
            while q_frame:
                cur_frame = q_frame.popleft()
                tf_frame = I.apply_transform(trans, cur_frame, std_size)
                tlm = trans(q_lm.popleft())
                seq.append(I.cut_patch(tf_frame, tlm[start_idx:stop_idx], crop_h // 2, crop_w // 2))
            return np.array(seq)
    return None


def interp_landmarks(lms, max_gap=6):
    """Fill None landmark frames by linear interpolation between computed frames.
    Gaps longer than max_gap are filled with the nearest computed frame (no long interpolation)."""
    n = len(lms)
    idx = [i for i in range(n) if lms[i] is not None]
    if not idx:
        return lms
    out = list(lms)
    for i in range(0, idx[0]):
        out[i] = lms[idx[0]]
    for a, b in zip(idx, idx[1:]):
        gap = b - a
        for i in range(a + 1, b):
            if gap <= max_gap:
                t = (i - a) / (b - a)
                out[i] = lms[a] * (1 - t) + lms[b] * t
            else:
                out[i] = lms[a] if (i - a) <= (b - i) else lms[b]
    for i in range(idx[-1] + 1, n):
        out[i] = lms[idx[-1]]
    return out


class Runner:
    def __init__(self, window_s=2.0, downscale=None, detect_every=8, landmark_every=1, device="cuda"):
        self.device = torch.device(device)
        t = time.perf_counter()
        self.fa = face_alignment.FaceAlignment(face_alignment.LandmarksType.TWO_D, flip_input=False,
                                               device=str(self.device), compile=False)
        self.dolphin = I.Dolphin.from_pretrained("JusperLee/Dolphin").to(self.device)
        self.dolphin.eval()
        self.window = int(window_s * 16000)
        self.downscale = downscale
        self.detect_every = detect_every
        self.landmark_every = landmark_every
        self.init_s = round(time.perf_counter() - t, 2)
        self._warmup()

    def _warmup(self):
        detect_faces(np.zeros((360, 640, 3), np.uint8), threshold=0.9, allow_upscaling=False)
        with torch.inference_mode():
            self.dolphin(torch.zeros(1, self.window, device=self.device),
                         torch.zeros(1, 1, 50, 88, 88, device=self.device))
        torch.cuda.synchronize()

    def _read_frames(self, path):
        clip = VideoFileClip(path)
        frames = [np.array(f) for f in clip.iter_frames()]
        clip.close()
        return frames

    def _detect_track(self, frames, n_spk):
        faces = [[] for _ in range(n_spk)]
        lms = [[] for _ in range(n_spk)]
        boxes = [[] for _ in range(n_spk)]
        t_retina = 0.0
        n_retina = 0
        t_fa = 0.0
        n_fa = 0
        t_track = 0.0
        detected = []
        force_detect = False
        for i, frame_rgb in enumerate(frames):
            t0 = time.perf_counter()
            do_detect = (i % self.detect_every == 0) or force_detect or (i == 0)
            force_detect = False
            if do_detect:
                img = frame_rgb
                scale = 1.0
                if self.downscale:
                    scale = self.downscale
                    h, w = img.shape[:2]
                    img = cv2.resize(img, (int(w * scale), int(h * scale)))
                a = time.perf_counter()
                db, _ = detect_faces(img, threshold=0.9, allow_upscaling=False)
                if db is None or len(db) == 0:
                    db, _ = detect_faces(img, threshold=0.7, allow_upscaling=True)
                t_retina += time.perf_counter() - a
                n_retina += 1
                if db is not None and len(db) > 0:
                    db = db[:n_spk]
                    if self.downscale:
                        db = db / scale
                    db = I.face2head(db, 1.5)
                else:
                    db = []
                detected = db
            # ---- tracking (IoU match) ----
            if i == 0:
                if len(detected) < n_spk:
                    raise ValueError(f"frame0 faces {len(detected)} < {n_spk}")
                for j in range(n_spk):
                    box = detected[j]
                    face = Image.fromarray(frame_rgb).crop((box[0], box[1], box[2], box[3])).resize((224, 224))
                    if i % self.landmark_every == 0:
                        a = time.perf_counter()
                        preds = self.fa.get_landmarks(np.array(face))
                        t_fa += time.perf_counter() - a
                        n_fa += 1
                        if preds is None or len(preds) == 0:
                            raise ValueError(f"no landmarks frame0 spk{j}")
                        lms[j].append(preds[0])
                    else:
                        lms[j].append(None)
                    faces[j].append(np.array(face)[..., ::-1])
                    boxes[j].append(box)
            else:
                matched = set()
                spk_boxes = [None] * n_spk
                if do_detect:
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
                    # re-detect next frame if a speaker lost its detection
                    if any(spk_boxes[s] is None for s in range(n_spk)):
                        force_detect = True
                for s in range(n_spk):
                    box = spk_boxes[s] if spk_boxes[s] is not None else boxes[s][-1]
                    face = Image.fromarray(frame_rgb).crop((box[0], box[1], box[2], box[3])).resize((224, 224))
                    if i % self.landmark_every == 0:
                        a = time.perf_counter()
                        preds = self.fa.get_landmarks(np.array(face))
                        t_fa += time.perf_counter() - a
                        n_fa += 1
                        if preds is None or len(preds) == 0:
                            preds = lms[s][-1] if lms[s][-1] is not None else None
                        else:
                            preds = preds[0]
                        lms[s].append(preds)
                    else:
                        lms[s].append(None)
                    faces[s].append(np.array(face)[..., ::-1])
                    boxes[s].append(box)
            t_track += time.perf_counter() - t0
        return faces, lms, boxes, {"retina_total_ms": round(t_retina * 1000, 1),
                                   "retina_calls": n_retina,
                                   "retina_per_call_ms": round(t_retina * 1000 / max(1, n_retina), 1),
                                   "fa_total_ms": round(t_fa * 1000, 1),
                                   "fa_calls": n_fa,
                                   "fa_per_call_ms": round(t_fa * 1000 / max(1, n_fa), 1),
                                   "track_ms": round(t_track * 1000, 1)}

    def _mouth(self, faces, lms):
        roi = []
        for s in range(len(faces)):
            pre = interp_landmarks(lms[s])
            seq = crop_patch_frames(faces[s], pre, 12, 48, 68, 96, 96)
            seq = I.convert_bgr2gray(seq)
            roi.append(seq)
        return roi

    def _separate(self, audio_path, mouth_roi):
        data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
        t = time.perf_counter()
        mix = torch.from_numpy(data.mean(axis=1)).to(self.device)
        mr = I.get_preprocessing_pipelines()["val"](mouth_roi[0])
        mr_t = torch.from_numpy(mr[None, None]).float()
        transfer = time.perf_counter() - t
        out = torch.zeros(1, len(mix))
        start = 0
        fwd = 0.0
        while start < len(mix):
            end = min(start + self.window, len(mix))
            wm = mix[start:end]
            sf_ = int(start / sr * 25)
            ef = min(int(end / sr * 25), len(mr))
            wmr = mr_t[:, :, sf_:ef].to(self.device)
            e0 = torch.cuda.Event(enable_timing=True)
            e1 = torch.cuda.Event(enable_timing=True)
            e0.record()
            with torch.inference_mode():
                est = self.dolphin(wm[None], wmr)
            e1.record()
            torch.cuda.synchronize()
            fwd += e0.elapsed_time(e1)
            wl = end - start
            out[0, start:end] = est[0, 0, :wl].cpu()
            start += self.window
        return out[0].numpy(), sr, fwd, transfer

    def run(self, video, out_wav):
        T = {}
        t = time.perf_counter()
        frames = self._read_frames(video)
        T["video_read"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        faces, lms, boxes, dt = self._detect_track(frames, 1)
        T["detect_track"] = round(time.perf_counter() - t, 2)
        T.update(dt)
        t = time.perf_counter()
        roi = self._mouth(faces, lms)
        T["mouth_roi"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        tmp = out_wav + ".mix.wav"
        subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", video, "-vn",
                        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", tmp], check=True)
        T["extract_audio"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        y, sr, fwd, transfer = self._separate(tmp, roi)
        T["gpu_transfer"] = round(transfer, 3)
        T["forward_cuda_ms"] = round(fwd, 1)
        T["separate_wall"] = round(time.perf_counter() - t, 2)
        t = time.perf_counter()
        sf.write(out_wav, y, sr, subtype="PCM_16")
        T["write_wav"] = round(time.perf_counter() - t, 2)
        return T, y


def bench(video, out, window, downscale, detect_every, landmark_every, reps):
    r = Runner(window_s=window, downscale=downscale, detect_every=detect_every,
               landmark_every=landmark_every)
    res = {"init_s": r.init_s, "window": window, "downscale": downscale,
           "detect_every": detect_every, "landmark_every": landmark_every, "requests": []}
    torch.cuda.reset_peak_memory_stats()
    for k in range(reps):
        t = time.perf_counter()
        T, _ = r.run(video, out + f"_w{k}.wav")
        T["wall"] = round(time.perf_counter() - t, 2)
        T["rep"] = k
        res["requests"].append(T)
    res["peak_vram_mib"] = round(torch.cuda.max_memory_allocated() / 1024 ** 2, 1)
    res["peak_reserved_mib"] = round(torch.cuda.max_memory_reserved() / 1024 ** 2, 1)
    walls = [x["wall"] for x in res["requests"]]
    res["wall_median"] = round(float(np.median(walls)), 2)
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--downscale", type=float, default=None)
    ap.add_argument("--detect-every", type=int, default=8)
    ap.add_argument("--landmark-every", type=int, default=1)
    ap.add_argument("--reps", type=int, default=3)
    a = ap.parse_args()
    r = bench(a.video, a.out, a.window, a.downscale, a.detect_every, a.landmark_every, a.reps)
    json.dump(r, open(a.out + "_bench.json", "w"), indent=1)
