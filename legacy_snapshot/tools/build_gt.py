"""Build the first real FOCUS GT pair from two internet sources.
A = talkinarabic "Mariam introduces herself" (clean, full-frame), segment 26-40s.
B = YouTube Linguamid "Introduce yourself in Egyptian Arabic" (full-frame), segment 24-38s.
Produces: p1_a_ref.wav, p1_b_ref.wav, p1_mix.wav, p1_a_in.mov, p1_b_in.mov (+ raw segs).
Mux uses PCM (no AAC delay); same mix is placed in both videos; verifies extraction==mix.
"""
import json
import os
import subprocess

import numpy as np
import soundfile as sf
import imageio_ffmpeg

ff = imageio_ffmpeg.get_ffmpeg_exe()
SRC = "A:/focus/data/src"
GT = "A:/focus/data/gt5"
os.makedirs(GT, exist_ok=True)
SR = 16000

SEGS = {
    "a": ("mariam.mp4", 26.0, 14.0),      # person A (clean)
    "b": ("linguamid.mp4", 24.0, 14.0),   # person B (full-frame)
}


def run(args):
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error"] + args, check=True)


# 1) cut segments (keep original audio)
for who, (src, t0, dur) in SEGS.items():
    run(["-ss", str(t0), "-i", f"{SRC}/{src}", "-t", str(dur),
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", f"{GT}/{who}_seg.mp4"])

# 2) extract 16k mono references
for who in SEGS:
    run(["-i", f"{GT}/{who}_seg.mp4", "-vn", "-ar", str(SR), "-ac", "1",
         "-c:a", "pcm_s16le", f"{GT}/{who}_raw.wav"])

# 3) loudness-normalise each to -23 LUFS, peak -2 dB
for who in SEGS:
    run(["-i", f"{GT}/{who}_raw.wav", "-af", "loudnorm=I=-23:TP=-2:LRA=11",
         "-ar", str(SR), "-ac", "1", f"{GT}/p1_{who}_ref.wav"])

# 4) known mix, no clipping
run(["-i", f"{GT}/p1_a_ref.wav", "-i", f"{GT}/p1_b_ref.wav",
     "-filter_complex", "amix=inputs=2:duration=shortest:normalize=0",
     "-ar", str(SR), "-ac", "1", f"{GT}/_mix_raw.wav"])
y, sr = sf.read(f"{GT}/_mix_raw.wav")
pk = float(np.max(np.abs(y)))
gain = 1.0
if pk > 0.98:
    gain = 0.98 / pk
sf.write(f"{GT}/p1_mix.wav", (y * gain).astype(np.float32), sr, subtype="PCM_16")

# 5) 25fps CFR video + mux the SAME mix as PCM (no AAC delay)
for who in SEGS:
    v25 = f"{GT}/{who}_v25.mp4"
    run(["-i", f"{GT}/{who}_seg.mp4", "-an", "-vf", "fps=25",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", v25])
    run(["-i", v25, "-i", f"{GT}/p1_mix.wav", "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "pcm_s16le", "-shortest", f"{GT}/p1_{who}_in.mov"])

# 6) verify the model receives the MIX (extract audio from each input)
res = {"gain": round(gain, 4), "mix_peak_before_gain": round(pk, 4), "sr": sr}
for who in SEGS:
    run(["-i", f"{GT}/p1_{who}_in.mov", "-vn", "-ar", str(SR), "-ac", "1",
         f"{GT}/{who}_in_audio.wav"])
    a, _ = sf.read(f"{GT}/p1_mix.wav")
    b, _ = sf.read(f"{GT}/{who}_in_audio.wav")
    n = min(len(a), len(b))
    a2, b2 = a[:n], b[:n]
    corr = float(np.dot(a2, b2) / (np.linalg.norm(a2) * np.linalg.norm(b2) + 1e-12))
    res[who] = {"extract_vs_mix_corr": round(corr, 5), "len_mix": len(a), "len_extract": len(b),
                "peak": round(float(np.max(np.abs(b))), 4)}

for who in SEGS:
    info = sf.info(f"{GT}/p1_{who}_ref.wav")
    res[f"{who}_ref"] = {"dur": round(info.duration, 3), "sr": info.samplerate,
                         "peak": round(float(np.max(np.abs(sf.read(f"{GT}/p1_{who}_ref.wav")[0]))), 4)}
print(json.dumps(res, indent=1))
json.dump(res, open(f"{GT}/gt_build.json", "w"), indent=1)
