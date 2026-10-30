"""Metrics, gate verdict and local HTML pages for comparing isolation engines.

Pure CPU code (numpy only) so it can be unit-tested with fake data.
"""
from __future__ import annotations

import html
import statistics
from dataclasses import dataclass, field

import numpy as np

GATE_MEDIAN_SI_SDRI_DB = 10.0
GATE_MAX_WARM_SECONDS = 5.0
GATE_CLIP_SECONDS = 15.0
MIN_TIMING_CLIP_SECONDS = 14.0  # shorter clips don't represent the 15 s requirement


def si_sdr(est, ref) -> float:
    est = np.asarray(est, dtype=np.float64); ref = np.asarray(ref, dtype=np.float64)
    n = min(len(est), len(ref))
    est, ref = est[:n] - est[:n].mean(), ref[:n] - ref[:n].mean()
    t = (np.dot(est, ref) / (np.dot(ref, ref) + 1e-12)) * ref
    e = est - t
    return float(10 * np.log10((np.dot(t, t) + 1e-12) / (np.dot(e, e) + 1e-12)))


def si_sdri(est, mix, ref) -> float:
    """Improvement over leaving the mixture untouched."""
    return si_sdr(est, ref) - si_sdr(mix, ref)


@dataclass
class EngineRun:
    engine: str
    wav_name: str | None = None
    timings: dict = field(default_factory=dict)
    wall_s: float = 0.0
    warm_wall_s: float | None = None
    si_sdri_db: float | None = None
    warnings: list = field(default_factory=list)
    details: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class EngineSetResult:
    engine: str
    si_sdri_db: list[float]
    warm_wall_s: list[float]
    clip_seconds: float
    errors: int = 0


def gate_verdict(results: list[EngineSetResult], listening: dict[str, bool]) -> dict:
    """Winner must reach median SI-SDRi >= 10 dB on the 3-speaker set, pass the
    listening test on the real hard clip, and finish a 15 s clip in <= 5 s warm."""
    rows = []
    for r in results:
        median = statistics.median(r.si_sdri_db) if r.si_sdri_db else None
        warm = statistics.median(r.warm_wall_s) if r.warm_wall_s else None
        checks = {
            "median_si_sdri": median is not None and r.errors == 0 and median >= GATE_MEDIAN_SI_SDRI_DB,
            "listening": listening.get(r.engine) is True,
            "speed": warm is not None and warm <= GATE_MAX_WARM_SECONDS
                     and r.clip_seconds >= MIN_TIMING_CLIP_SECONDS,
        }
        rows.append({
            "engine": r.engine, "median_si_sdri_db": median, "warm_wall_s": warm,
            "clips": len(r.si_sdri_db), "errors": r.errors,
            "listening": listening.get(r.engine), "checks": checks,
            "passed": all(checks.values()),
            "failed_checks": [k for k, v in checks.items() if not v],
        })
    winners = [r for r in rows if r["passed"]]
    if winners:
        best = max(winners, key=lambda r: r["median_si_sdri_db"])
        return {"status": "pass", "winner": best["engine"], "rows": rows,
                "message": f"{best['engine']} passed every gate condition."}
    closest = None
    if rows:
        closest = min(rows, key=lambda r: (len(r["failed_checks"]),
                                           -(r["median_si_sdri_db"] or -999)))
    msg = "No engine passed the gate."
    if closest:
        msg += (f" Closest: {closest['engine']} (failed: {', '.join(closest['failed_checks'])}; "
                f"median SI-SDRi {closest['median_si_sdri_db']}).")
    return {"status": "fail", "winner": None, "closest": closest["engine"] if closest else None,
            "rows": rows, "message": msg}


def _fmt(v, suffix=""):
    return "—" if v is None else f"{v:.2f}{suffix}"


_STYLE = ("body{font-family:system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem}"
          "table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:.4rem;"
          "text-align:start;vertical-align:top}.err{color:#a00}.ok{color:#070}")


def render_compare_html(clip_name: str, mix_wav: str, runs: list[EngineRun],
                        has_reference: bool) -> str:
    e = html.escape
    cards = []
    for r in runs:
        stages = ", ".join(f"{e(k)}: {v}s" for k, v in r.timings.items()) or "—"
        player = (f'<audio controls preload="none" src="{e(r.wav_name)}"></audio>'
                  if r.wav_name else f'<span class="err">{e(r.error or "no output")}</span>')
        warns = "".join(f"<li>{e(w)}</li>" for w in r.warnings) or "<li>none</li>"
        sdr = _fmt(r.si_sdri_db, " dB") if has_reference else "no clean reference"
        cards.append(
            f"<tr><td><b>{e(r.engine)}</b></td><td>{player}</td>"
            f"<td>total {_fmt(r.wall_s, 's')}<br>warm {_fmt(r.warm_wall_s, 's')}<br>{stages}</td>"
            f"<td>{sdr}</td><td><ul>{warns}</ul></td></tr>")
    return (f"<!doctype html><meta charset=utf-8><title>Engine comparison</title>"
            f"<style>{_STYLE}</style><h1>Engine comparison: {e(clip_name)}</h1>"
            f'<p>Original mixture: <audio controls preload="none" src="{e(mix_wav)}"></audio></p>'
            "<table><tr><th>Engine</th><th>Isolated audio</th><th>Time per stage</th>"
            "<th>SI-SDRi</th><th>Warnings</th></tr>" + "".join(cards) + "</table>"
            "<p>Listening decides: play each result next to the original, then choose.</p>")


def render_gate_html(verdict: dict) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(r['engine'])}</td><td>{_fmt(r['median_si_sdri_db'], ' dB')}</td>"
        f"<td>{r['clips']} (errors {r['errors']})</td><td>{_fmt(r['warm_wall_s'], 's')}</td>"
        f"<td>{'pass' if r['listening'] else 'not passed' if r['listening'] is False else 'not recorded'}</td>"
        f"<td class={'ok' if r['passed'] else 'err'}>{'PASS' if r['passed'] else e(', '.join(r['failed_checks']))}</td></tr>"
        for r in verdict["rows"])
    return (f"<!doctype html><meta charset=utf-8><title>Engine gate</title><style>{_STYLE}</style>"
            f"<h1>Engine selection gate</h1><p><b>{e(verdict['message'])}</b></p>"
            "<p>Needs: median SI-SDRi &ge; 10 dB on the 3-speaker set, listening pass on the "
            "real hard clip, 15 s clip in &le; 5 s after warm-up.</p>"
            "<table><tr><th>Engine</th><th>Median SI-SDRi</th><th>Clips</th><th>Warm time</th>"
            "<th>Listening</th><th>Result</th></tr>" + rows + "</table>")
