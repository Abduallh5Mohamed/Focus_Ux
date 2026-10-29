"""WER for the GT pair (PROVISIONAL). Reference text = ASR of the CLEAN reference (single
speaker), not human-verified -> treat as provisional, needs human review.
Compares WER(mix) and WER(est) against that reference, same ASR model/settings for all.
Saves transcripts to p1_a.txt / p1_b.txt for review.
"""
import json
import os

import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel

GT = "A:/focus/data/gt5"
WMODEL = os.environ.get("WHISPER_MODEL", "small")
WDEV = os.environ.get("WHISPER_DEVICE", "cuda")
WCOMP = os.environ.get("WHISPER_COMPUTE", "int8_float16")
model = WhisperModel(WMODEL, device=WDEV, compute_type=WCOMP)
print("whisper model:", WMODEL, "device:", WDEV, "compute:", WCOMP)


def transcribe(path):
    # load via soundfile and pass a float32 array: bypasses a PyAV/faster-whisper
    # decode incompatibility (av 19 lacks the 'metadata_errors' kwarg).
    y, sr = sf.read(path, dtype="float32")
    if y.ndim > 1:
        y = y.mean(1)
    segs, _ = model.transcribe(y, language="ar", beam_size=1, vad_filter=True)
    return "".join(s.text for s in segs).strip()


def norm(t):
    import re
    t = re.sub(r"[\u064B-\u0652\u0653-\u0655\u0670]", "", t)
    t = re.sub(r"[إأآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("\u0640", "")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def wer(ref, hyp):
    r, h = norm(ref).split(), norm(hyp).split()
    # Levenshtein
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=int)
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (0 if r[i - 1] == h[j - 1] else 1))
    return float(d[len(r)][len(h)] / max(1, len(r)))


res = {}
for who in ("a", "b"):
    ref_txt = transcribe(f"{GT}/p1_{who}_ref.wav")
    open(f"{GT}/p1_{who}.txt", "w", encoding="utf-8").write(ref_txt)
    mix_txt = transcribe(f"{GT}/p1_mix.wav")
    est_txt = transcribe(f"{GT}/p1_{who}_est.wav")
    res[who] = {
        "ref_asr": ref_txt,
        "mix_asr": mix_txt,
        "est_asr": est_txt,
        "wer_mix": round(wer(ref_txt, mix_txt), 4),
        "wer_est": round(wer(ref_txt, est_txt), 4),
        "note": "reference = ASR of clean ref (provisional, not human-verified)",
    }
    print(f"--- {who} ---")
    print("ref :", ref_txt[:200])
    print("mix :", mix_txt[:200])
    print("est :", est_txt[:200])
    print(f"WER(mix)={res[who]['wer_mix']}  WER(est)={res[who]['wer_est']}")

json.dump(res, open(f"{GT}/wer_provisional.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote wer_provisional.json")
