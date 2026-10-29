"""Stream a file to the live endpoints at its ORIGINAL speed and print server metrics.

    python product/tools/live_gate.py --api http://HOST:PORT --video clip.mp4 [--face-index 0]

The file is re-encoded to a MediaRecorder-like WebM (1 s clusters) and sliced
mid-cluster every 2 s of wall-clock time. Server-side latency printed here is a LOWER
BOUND: capture-to-play needs the browser (the /live page posts it). Playback is not
simulated, so the gate stays ``internal_only`` from this tool alone.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

CLUSTER = b"\x1f\x43\xb6\x75"


def clusters(data: bytes) -> list[int]:
    out, pos = [], 0
    while (pos := data.find(CLUSTER, pos)) >= 0:
        out.append(pos)
        pos += 4
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--face-index", type=int, default=0)
    ap.add_argument("--chunk-s", type=float, default=2.0)
    ap.add_argument("--timeout-s", type=float, default=600)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        webm = Path(tmp) / "s.webm"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", args.video, "-c:v", "libvpx", "-g", "25",
             "-c:a", "libopus", "-f", "webm", "-cluster_time_limit", "1000", str(webm)], check=True)
        data = webm.read_bytes()
    marks = clusters(data)
    step = max(1, int(args.chunk_s))
    cuts = [0] + [m + 50 for m in marks[step::step]] + [len(data)]
    chunks = [data[a:b] for a, b in zip(cuts, cuts[1:]) if b > a]

    with httpx.Client(base_url=args.api, timeout=60) as http:
        created = http.post("/live/sessions")
        created.raise_for_status()
        body = created.json()
        sid, auth = body["live_session_id"], {"Authorization": f"Bearer {body['session_token']}"}
        t0 = time.monotonic()
        target_set = False
        for seq, blob in enumerate(chunks):
            due = t0 + (seq + 1) * args.chunk_s  # a chunk exists only after its 2 s were recorded
            time.sleep(max(0.0, due - time.monotonic()))
            r = http.put(f"/live/sessions/{sid}/chunks/{seq}",
                         params={"capture_start_ms": int(seq * args.chunk_s * 1000),
                                 "duration_ms": int(args.chunk_s * 1000)},
                         content=blob, headers=auth)
            print(f"chunk {seq}: {r.status_code} {r.json().get('state', r.text[:80])}")
            if not target_set:
                view = http.get(f"/live/sessions/{sid}", headers=auth).json()
                if view["faces_status"] == "ready" and view["first_video_id"]:
                    faces = http.get(f"/videos/{view['first_video_id']}/faces", headers=auth).json()["faces"]
                    if faces:
                        http.post(f"/live/sessions/{sid}/target", headers=auth,
                                  json={"face_id": faces[min(args.face_index, len(faces) - 1)]["face_id"]}
                                  ).raise_for_status()
                        target_set = True
        http.post(f"/live/sessions/{sid}/stop", headers=auth).raise_for_status()
        deadline = time.monotonic() + args.timeout_s
        while time.monotonic() < deadline:
            view = http.get(f"/live/sessions/{sid}", headers=auth).json()
            if view["final"]["status"] in ("ready", "failed"):
                break
            time.sleep(1)
        print(json.dumps(http.get(f"/live/sessions/{sid}/metrics", headers=auth).json(), indent=2))
        print("NOTE: no browser playback report; capture-to-play is NOT measured by this tool.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
