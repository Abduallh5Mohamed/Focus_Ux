import json
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from services.api.focus_api import mix
from services.worker.interfaces import TargetRunResult

from .fakes import FakeExtractionRunner
from .test_uploads import assert_error

FPS = 25
SECONDS = 2.0


def _write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def _signals(rate: int):
    rng = np.random.default_rng(5)
    n = int(rate * SECONDS)
    def speech_band(x):  # content below 6 kHz, like a 16 kHz isolated file can hold
        spec = np.fft.rfft(x)
        spec[np.fft.rfftfreq(n, 1 / rate) > 6000] = 0
        return np.fft.irfft(spec, n)
    voice = speech_band(rng.standard_normal(n)) * 0.3
    others = speech_band(rng.standard_normal(n)) * 0.16
    return voice, others


@pytest.fixture(scope="module")
def real_video(tmp_path_factory):
    base = tmp_path_factory.mktemp("clip")
    voice, others = _signals(48_000)
    _write_wav(base / "orig.wav", 0.5 * voice + others, 48_000)
    _write_wav(base / "iso16.wav", np.interp(
        np.arange(0, len(voice), 3), np.arange(len(voice)), 0.2 * voice), 16_000)
    video = base / "clip.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
        "-i", f"testsrc=size=160x120:rate={FPS}:duration={SECONDS}", "-i", str(base / "orig.wav"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video),
    ], check=True)
    _write_wav(base / "unrelated.wav", np.random.default_rng(77).standard_normal(32_000) * 0.2, 16_000)
    return base, video


class WavRunner(FakeExtractionRunner):
    def __init__(self, wav: Path, duration_ms: int = 2000):
        super().__init__(duration_ms=duration_ms)
        self.wav = wav

    def extract(self, job, job_dir, on_progress):
        import os
        os.makedirs(job_dir, exist_ok=True)
        target = os.path.join(job_dir, "target_extract.wav")
        Path(target).write_bytes(self.wav.read_bytes())
        return TargetRunResult(wav_path=target, duration_ms=self.duration_ms,
                               source_offset_ms=0, timings={}, warnings=[])


def _job(make_api, real_video, wav_name="iso16.wav"):
    base, video = real_video
    api = make_api(runner=WavRunner(base / wav_name))
    video_id, token, _ = api.upload_ok(data=video.read_bytes())
    api.drain()
    face = api.get_faces(video_id, token).json()["faces"][0]["face_id"]
    job = api.create_job(video_id, face, "r1", token).json()["job_id"]
    api.drain()
    assert api.get_job(job, token).json()["status"] == "completed"
    _, stranger, _ = api.upload_ok()
    return api, video_id, token, job, stranger


def _probe(path: Path, stream: str, entries: str):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", entries,
         "-of", "json", str(path)], capture_output=True, check=True, text=True).stdout
    return json.loads(out)


def _decode_audio(path: Path, rate: int = mix.WORK_RATE) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-nostdin", "-i", str(path), "-vn",
         "-map", "0:a:0", "-f", "f32le", "-ac", "1", "-ar", str(rate), "pipe:1"],
        capture_output=True, check=True,
    ).stdout
    usable = len(raw) - len(raw) % 4
    return np.frombuffer(raw[:usable], dtype="<f4").astype(np.float32)


def _expected_alignment(base: Path, source: Path, duration_ms: int = 2000):
    """Reproduce the server's analysis on the same decoded inputs."""
    original = mix.decode_mono(source)
    original = mix.fit_length(original, int(round(duration_ms * mix.WORK_RATE / 1000)))
    isolated = mix.decode_mono(base / "iso16.wav")
    result = mix.align(original, isolated, offset_ms=0.0)
    assert result.reliable, result.reason
    return result


def _nrmse(actual: np.ndarray, expected: np.ndarray, skip_ms: float = 50.0) -> float:
    """Normalised RMS error of the decoded AAC against the exact server render.

    The leading/trailing AAC frames are skipped because codec priming adds
    samples at both ends; over the steady-state middle this is fair.
    """
    length = min(len(actual), len(expected))
    skip = int(mix.WORK_RATE * skip_ms / 1000.0)
    a = np.asarray(actual[skip:length - skip], dtype=np.float64)
    e = np.asarray(expected[skip:length - skip], dtype=np.float64)
    return float(np.sqrt(np.mean((a - e) ** 2)) / np.sqrt(np.mean(e ** 2)))


def _wait_ready(api, job, export, token):
    for _ in range(200):
        state = api.client.get(f"/jobs/{job}/exports/{export}", headers=api.auth(token)).json()
        if state["status"] != "rendering":
            return state
        time.sleep(0.05)
    raise AssertionError("export did not finish")


def _export(api, job, token, **body):
    return api.client.post(f"/jobs/{job}/exports", json=body, headers=api.auth(token))


def test_mix_info_and_tracks_reliable(make_api, real_video):
    api, _vid, token, job, _s = _job(make_api, real_video)
    info = api.client.get(f"/jobs/{job}/mix", headers=api.auth(token)).json()
    assert info["others_available"] is True
    assert abs(info["alignment_ms"]) < 2
    for track in ("voice", "others"):
        r = api.client.get(f"/jobs/{job}/mix/{track}", headers=api.auth(token))
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
        assert r.content[:4] == b"RIFF"
    assert_error(api.client.get(f"/jobs/{job}/mix/other", headers=api.auth(token)), 404, "NOT_FOUND")


def test_unreliable_residual_is_refused(make_api, real_video):
    api, _vid, token, job, _s = _job(make_api, real_video, "unrelated.wav")
    info = api.client.get(f"/jobs/{job}/mix", headers=api.auth(token)).json()
    assert info["others_available"] is False and info["others_unavailable_reason"]
    assert_error(api.client.get(f"/jobs/{job}/mix/others", headers=api.auth(token)), 409, "MIX_UNRELIABLE")
    assert_error(_export(api, job, token, others_level=0.5), 409, "MIX_UNRELIABLE")
    assert _export(api, job, token, others_level=0).status_code == 202


def test_invalid_export_settings(make_api, real_video):
    api, _vid, token, job, _s = _job(make_api, real_video)
    assert_error(_export(api, job, token, voice_level=5), 400, "INVALID_REQUEST")
    assert_error(_export(api, job, token, noise_reduction="ai"), 400, "INVALID_REQUEST")


def test_export_is_in_sync_and_video_unchanged(make_api, real_video):
    base, source = real_video
    api, vid, token, job, _s = _job(make_api, real_video)
    started = _export(api, job, token, voice_level=1.5, others_level=0.2, noise_reduction="light")
    assert started.status_code == 202
    export = started.json()["export_id"]
    assert _wait_ready(api, job, export, token)["status"] == "ready"
    response = api.client.get(f"/jobs/{job}/exports/{export}/file", headers=api.auth(token))
    assert response.status_code == 200 and response.headers["content-type"] == "video/mp4"
    out = base / "exported.mp4"
    out.write_bytes(response.content)

    frame = 1.0 / FPS
    src_v = float(_probe(source, "v:0", "stream=duration")["streams"][0]["duration"])
    out_v = float(_probe(out, "v:0", "stream=duration")["streams"][0]["duration"])
    out_a = float(_probe(out, "a:0", "stream=duration")["streams"][0]["duration"])
    assert abs(out_v - src_v) <= frame
    assert abs(out_a - src_v) <= frame
    start_a = float(_probe(out, "a:0", "stream=start_time")["streams"][0]["start_time"])
    assert abs(start_a) <= frame

    def video_md5(path):
        return subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy",
             "-f", "md5", "-"], capture_output=True, check=True, text=True).stdout
    assert video_md5(out) == video_md5(source)

    # Peak never clips.
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(out), "-map", "0:a:0", "-f", "f32le",
         "-ac", "1", "pipe:1"], capture_output=True, check=True).stdout
    peak = float(np.max(np.abs(np.frombuffer(raw, dtype="<f4"))))
    assert peak <= 1.0

    # The final AAC track is the exact server-side mix (voice 1.5, residual 0.2,
    # light high-pass), not the source or a re-gained variant.
    alignment = _expected_alignment(base, source)
    expected = mix.render_mix(alignment, mix.MixSettings(1.5, 0.2, "light"))
    assert _nrmse(_decode_audio(out), expected) < 0.06


@pytest.mark.parametrize('explicit_settings', [False, True], ids=['empty-body-default', 'explicit-target-only'])
def test_target_only_export_excludes_the_original_residual(make_api, real_video, explicit_settings):
    base, source = real_video
    api, _vid, token, job, _s = _job(make_api, real_video)
    settings = dict(voice_level=1, others_level=0, noise_reduction="off") if explicit_settings else {}
    started = _export(api, job, token, **settings)
    assert started.status_code == 202
    export = started.json()["export_id"]
    assert _wait_ready(api, job, export, token)["status"] == "ready"
    response = api.client.get(f"/jobs/{job}/exports/{export}/file", headers=api.auth(token))
    assert response.status_code == 200
    out = base / "target_only.mp4"
    out.write_bytes(response.content)

    alignment = _expected_alignment(base, source)
    expected_target = mix.render_mix(alignment, mix.MixSettings(1.0, 0.0, "off"))
    expected_full = mix.render_mix(alignment, mix.MixSettings(1.0, 1.0, "off"))
    decoded = _decode_audio(out)

    # Close to the target-only render...
    assert _nrmse(decoded, expected_target) < 0.06
    # ...and clearly not the source or a residual-containing mix.
    assert _nrmse(decoded, expected_full) > 0.3


def test_export_access_control_and_deletion(make_api, real_video):
    api, vid, token, job, stranger = _job(make_api, real_video)
    export = _export(api, job, token, others_level=0).json()["export_id"]
    assert _wait_ready(api, job, export, token)["status"] == "ready"
    paths = [f"/jobs/{job}/mix", f"/jobs/{job}/mix/voice", f"/jobs/{job}/exports/{export}",
             f"/jobs/{job}/exports/{export}/file"]
    for path in paths:
        assert_error(api.client.get(path), 401, "UNAUTHORIZED")
        assert_error(api.client.get(path, headers=api.auth(stranger)), 404, "NOT_FOUND")
        assert_error(api.client.get(path, params={"token": token}), 401, "UNAUTHORIZED")
    assert_error(api.client.post(f"/jobs/{job}/exports", json={}), 401, "UNAUTHORIZED")
    assert_error(_export(api, job, stranger), 404, "NOT_FOUND")
    exports_dir = api.settings.jobs_dir / job / "exports"
    assert list(exports_dir.glob("*.mp4"))

    assert api.delete_video(vid, token).status_code == 202
    for path in paths:
        assert_error(api.client.get(path, headers=api.auth(token)), 404, "NOT_FOUND")
    assert_error(_export(api, job, token), 404, "NOT_FOUND")
    api.drain()
    assert not (api.settings.jobs_dir / job).exists()
    for path in paths:
        assert_error(api.client.get(path, headers=api.auth(token)), 404, "NOT_FOUND")


def test_unknown_export_is_404(make_api, real_video):
    api, _vid, token, job, _s = _job(make_api, real_video)
    assert_error(api.client.get(f"/jobs/{job}/exports/{'0' * 32}", headers=api.auth(token)), 404, "NOT_FOUND")
