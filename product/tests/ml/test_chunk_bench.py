import json
import wave

import pytest

from focus_ml.chunk_bench import ChunkResult, run_chunks, summarize_bench, write_run


def _wav(path, n=3200):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x01\x00" * n)
    return str(path)


def fake_results(times, dur=2.0):
    return [ChunkResult(i, None, dur, t) for i, t in enumerate(times)]


def test_rtf_and_target_flag():
    s = summarize_bench(fake_results([1.0, 1.4, 1.6]), 2.0)
    assert s["rtf"] == pytest.approx(4.0 / 6.0, abs=1e-3) and s["meets_rtf_target"] is True
    s = summarize_bench(fake_results([2.0, 2.0]), 2.0)
    assert s["rtf"] == 1.0 and s["meets_rtf_target"] is False


def test_slower_than_realtime_builds_queue_and_latency():
    s = summarize_bench(fake_results([3.0] * 4), 2.0)   # RTF 1.5
    assert s["max_queue_depth"] >= 1
    lats = [c["latency_s"] for c in s["chunks"]]
    assert lats == sorted(lats) and lats[0] == 3.0 and lats[-1] > lats[0]


def test_fast_processing_keeps_queue_empty_and_latency_equal_to_processing():
    s = summarize_bench(fake_results([1.0] * 5), 2.0)
    assert s["max_queue_depth"] == 0 and s["latency_s"]["max"] == 1.0


def test_failed_chunk_is_reported_and_blocks_verdict():
    clock = iter([0.0, 1.0, 1.0, 2.0])

    def process(i, chunk):
        if i == 1:
            raise RuntimeError("boom")
        return {"wav_path": "x.wav", "duration_s": 2.0}

    res = run_chunks(["a", "b"], process, 2.0, clock=lambda: next(clock))
    s = summarize_bench(res, 2.0)
    assert s["n_failed"] == 1 and s["meets_rtf_target"] is None
    assert "RuntimeError: boom" in res[1].error


def test_no_successful_chunks_has_no_rtf():
    s = summarize_bench([ChunkResult(0, None, 2.0, 1.0, error="x")], 2.0)
    assert s["rtf"] is None and s["meets_rtf_target"] is None


def test_write_run_matches_eval_layout(tmp_path):
    res = [ChunkResult(i, _wav(tmp_path / f"c{i}.wav"), 0.2, 0.1) for i in range(3)]
    bench = write_run(str(tmp_path / "run"), "lbl", "clip1", "a", res, 2.0, {"tracking_mode": "adaptive"})
    meta = json.loads((tmp_path / "run" / "run.json").read_text())
    assert meta["label"] == "lbl"
    assert meta["bench_by_clip"]["clip1"]["settings"]["tracking_mode"] == "adaptive"
    with wave.open(str(tmp_path / "run" / "clip1" / "a.wav")) as w:
        assert w.getnframes() == 3 * 3200
    assert bench["n_failed"] == 0


def test_write_run_writes_no_audio_when_a_chunk_failed(tmp_path):
    res = [ChunkResult(0, _wav(tmp_path / "c0.wav"), 0.2, 0.1), ChunkResult(1, None, 2.0, 0.1, error="x")]
    write_run(str(tmp_path / "run"), "l", "clip1", "a", res, 2.0, {})
    assert not (tmp_path / "run" / "clip1" / "a.wav").exists()


def test_second_clip_does_not_overwrite_first_clips_speed(tmp_path):
    fast = [ChunkResult(0, _wav(tmp_path / "f.wav"), 2.0, 0.5)]
    slow = [ChunkResult(0, _wav(tmp_path / "s.wav"), 2.0, 3.0)]
    write_run(str(tmp_path / "run"), "l", "A", "a", fast, 2.0, {})
    write_run(str(tmp_path / "run"), "l", "B", "a", slow, 2.0, {})
    by_clip = json.loads((tmp_path / "run" / "run.json").read_text())["bench_by_clip"]
    assert set(by_clip) == {"A", "B"} and by_clip["A"]["rtf"] < 0.8 < by_clip["B"]["rtf"]
    with pytest.raises(ValueError):
        write_run(str(tmp_path / "run"), "other-label", "C", "a", fast, 2.0, {})
