"""Continuous-path gate run: streams a reference clip at its real speed (200 ms batches of
PCM16 + 25 fps JPEG frames), collects the isolated parts like a browser would, and asks
the server for metrics. Playback latency still needs the browser (/live); SI-SDRi is
computed here from the clip's clean reference and the upload path's output."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.worker import stream_proto as sp  # noqa: E402

SR, FPS, BATCH_S = sp.SAMPLE_RATE, sp.FPS, 0.2


def si_sdr(est: np.ndarray, ref: np.ndarray) -> float:
    n = min(len(est), len(ref))
    est, ref = est[:n] - est[:n].mean(), ref[:n] - ref[:n].mean()
    target = (est @ ref) / (ref @ ref + 1e-12) * ref
    noise = est - target
    return float(10 * np.log10((target @ target + 1e-12) / (noise @ noise + 1e-12)))


def read_wav(path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if (w.getnchannels(), w.getframerate(), w.getsampwidth()) != (1, SR, 2):
            raise SystemExit(f"{path} must be mono 16 kHz PCM16")
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768


def decode(video: str):
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", video, "-vn", "-ar", str(SR), "-ac", "1",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    mjpeg = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", video, "-an", "-r", str(FPS), "-vf",
                            "scale='min(640,iw)':-2", "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                           capture_output=True, check=True).stdout
    frames, pos = [], 0
    while (a := mjpeg.find(b"\xff\xd8", pos)) >= 0:
        b = mjpeg.find(b"\xff\xd9", a)
        if b < 0:
            break
        frames.append(mjpeg[a:b + 2])
        pos = b + 2
    return pcm, frames


def parts_from(response_body: bytes):
    _s, records = sp.unpack_batch(response_body)
    meta, out = None, []
    for kind, pos, data in records:
        if kind == sp.K_JSON:
            m = json.loads(data)
            if "idx" in m:
                meta = dict(m, pcm=b"")
                out.append(meta)
        elif kind == sp.K_OUT_AUDIO and meta is not None:
            meta["pcm"] = data
    return out


def run_stream_gate(args) -> int:
    pcm, frames = decode(args.video)
    with httpx.Client(base_url=args.api, timeout=60) as http:
        created = http.post("/live/stream/sessions")
        created.raise_for_status()
        body = created.json()
        sid = body["live_session_id"]
        auth = {"Authorization": f"Bearer {body['session_token']}"}
        base = f"/live/stream/sessions/{sid}"
        step = int(BATCH_S * SR)
        parts, after, targeted, t0 = {}, -1, False, time.monotonic()
        for seq, a in enumerate(range(0, len(pcm) // 2, step)):
            time.sleep(max(0.0, t0 + (a + step) / SR - time.monotonic()))
            lo = a / SR
            records = [(sp.K_AUDIO, a, pcm[a * 2:(a + step) * 2])]
            for i in range(int(lo * FPS), min(len(frames), int((lo + BATCH_S) * FPS))):
                records.append((sp.K_FRAME, int(i * 1000 / FPS), frames[i]))
            http.post(f"{base}/in", content=sp.pack_batch(seq, records), headers=auth).raise_for_status()
            if not targeted:
                view = http.get(base, headers=auth).json()
                if view["faces"]:
                    face = view["faces"][min(args.face_index, len(view["faces"]) - 1)]
                    http.post(f"{base}/target", json={"bbox": face["bbox"]}, headers=auth).raise_for_status()
                    targeted = True
            r = http.get(f"{base}/out?after={after}&wait_ms=1", headers=auth)
            if r.status_code == 200:
                for p in parts_from(r.content):
                    parts[p["idx"]], after = p, max(after, p["idx"])
        http.post(f"{base}/stop", headers=auth).raise_for_status()
        deadline = time.monotonic() + args.timeout_s
        while time.monotonic() < deadline:
            r = http.get(f"{base}/out?after={after}&wait_ms=500", headers=auth)
            if r.status_code == 200:
                for p in parts_from(r.content):
                    parts[p["idx"]], after = p, max(after, p["idx"])
            if http.get(base, headers=auth).json()["phase"] in ("done", "failed"):
                break
        delta = None
        if args.reference_wav and args.upload_wav:
            ref, up = read_wav(args.reference_wav), read_wav(args.upload_wav)
            live = np.zeros(len(ref))
            for p in parts.values():
                if p["pcm"]:
                    x = np.frombuffer(p["pcm"], dtype="<i2").astype(np.float64) / 32768
                    live[p["start"]:p["start"] + len(x)] = x[:max(0, len(live) - p["start"])]
            mix = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768
            gain = lambda est: si_sdr(est, ref) - si_sdr(mix[:len(ref)], ref)  # noqa: E731
            delta = round(gain(up) - gain(live), 2)
            print(f"SI-SDRi upload={gain(up):.2f} dB live={gain(live):.2f} dB loss={delta} dB")
        path = f"{base}/metrics" + (f"?quality_delta_db={delta}" if delta is not None else "")
        print(json.dumps(http.get(path, headers=auth).json(), indent=2))
        print("NOTE: capture-to-play needs the /live page in a browser; this tool cannot pass the gate alone.")
    return 0
