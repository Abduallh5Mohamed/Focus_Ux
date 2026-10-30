"""Comparison report: JSON plus one local HTML page with blind-listening players.

The page never loads anything remote. Listening items carry neutral letters; the
key that maps letters to candidates sits in a collapsed section.
"""
from __future__ import annotations

import html
import random

from .metrics import CATEGORIES

TITLES = {"target_alone": "Target alone", "overlap_2": "2-person overlap",
          "overlap_3plus": "3+-person overlap", "others_overlap": "Others only (should be silent)"}


def blind_labels(names: list[str], seed: str) -> dict[str, str]:
    """Deterministic shuffle of neutral letters: label -> name."""
    order = sorted(names)
    random.Random(seed).shuffle(order)
    return {chr(ord("A") + i): n for i, n in enumerate(order)}


def _f(v, nd=2, suffix=""):
    return "—" if v is None else f"{v:.{nd}f}{suffix}"


def _pct(v):
    return "—" if v is None else f"{100 * v:.0f}%"


def _cell(cat_entry, cat):
    if not cat_entry:
        return "<td>n/a</td>" * 4
    if cat == "others_overlap":
        return f"<td colspan=4>leakage {_f(cat_entry.get('leakage_db_mean'), 1, ' dB')} (muted {_pct(cat_entry['muted_share'])}, {cat_entry['regions']} regions)</td>"
    return (f"<td>{_f(cat_entry['si_sdri_db_mean'], 1)}</td><td>{_pct(cat_entry['wrong_person_rate'])}"
            f" <small>of {cat_entry['wrong_person_judged']}</small></td>"
            f"<td>{_pct(cat_entry['retention_mean'])}</td><td>{_pct(cat_entry['muted_share'])}</td>")


def render_html(report: dict) -> str:
    e = html.escape
    d = report["decision"]
    b = report["basis"]
    parts = ["<!doctype html><meta charset=utf-8><title>Overlap extraction comparison</title>",
             "<style>body{font-family:system-ui,sans-serif;max-width:78rem;margin:2rem auto;padding:0 1rem}"
             "table{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}td,th{border:1px solid #bbb;"
             "padding:.35rem;text-align:start;vertical-align:top}.err{color:#a00}.warn{background:#fff3cd;"
             "padding:.6rem}small{color:#555}audio{max-width:16rem}</style>",
             "<h1>Overlap extraction: candidate comparison</h1>",
             f"<p class=warn><b>Data:</b> {e(str(b.get('data', 'unknown')))}; <b>device:</b> "
             f"{e(str(b.get('device', 'unknown')))}; <b>regions:</b> {e(str(b.get('regions', 'oracle')))}. "
             f"{e(b.get('caveat', ''))}</p>",
             f"<h2>Decision</h2><p><b>{e(d['text'])}</b></p>"]
    if d.get("rejected"):
        parts.append("<ul>" + "".join(f"<li>{e(k)}: {e(v)}</li>" for k, v in d["rejected"].items()) + "</ul>")
    if d.get("fine_tuning_plan"):
        parts.append(f"<p><b>Fine-tuning plan.</b> {e(d['fine_tuning_plan'])}</p>")
    names = ["gated_baseline"] + list(report["candidates"])
    for cat in CATEGORIES:
        head = ("<th colspan=4>leakage</th>" if cat == "others_overlap" else
                "<th>SI-SDRi dB</th><th>Wrong person</th><th>Target retention</th><th>Muted</th>")
        rows = []
        for n in names:
            if n == "gated_baseline":
                entry, label, note = report["baseline"]["aggregate"].get(cat), "gated_baseline (mutes overlap)", ""
            else:
                c = report["candidates"][n]
                if c.get("blocked"):
                    continue
                if cat in OVERLAP_ONLY and cat not in c["info"]["categories"]:
                    continue
                entry, label = c["aggregate"].get(cat), n
                note = ""
            rows.append(f"<tr><td>{e(label)}{note}</td>{_cell(entry, cat)}</tr>")
        parts.append(f"<h3>{e(TITLES[cat])}</h3><table><tr><th>Candidate</th>{head}</tr>{''.join(rows)}</table>")
    parts.append("<h2>Speed and memory</h2><table><tr><th>Candidate</th><th>Mechanism</th><th>Real-time factor "
                 "(overlap audio)</th><th>s / window</th><th>Peak VRAM</th><th>fp16</th><th>Whole-clip SI-SDRi</th></tr>")
    for n, c in report["candidates"].items():
        if c.get("blocked"):
            continue
        t = c["timing"]
        parts.append(f"<tr><td>{e(n)}</td><td>{e(c['info']['mechanism'])}</td><td>{_f(t.get('rtf_overlap'), 3)}</td>"
                     f"<td>{_f(t.get('seconds_per_window'), 3)}</td><td>{_f(t.get('peak_vram_mib'), 0, ' MiB')}</td>"
                     f"<td>{e(str(t.get('fp16')))}</td><td>{_f(c.get('clip_si_sdri_db_mean'), 1)}</td></tr>")
    parts.append("</table><h2>Blocked candidates</h2>")
    blocked = [(n, c) for n, c in report["candidates"].items() if c.get("blocked")]
    parts.append("<table><tr><th>Candidate</th><th>Reason</th><th>Evidence</th></tr>" + "".join(
        f"<tr><td>{e(n)}</td><td class=err>{e(c['blocked']['kind'])}: {e(c['blocked']['message'])}</td>"
        f"<td>{e(c['blocked']['evidence'])}</td></tr>" for n, c in blocked) + "</table>"
        if blocked else "<p>None.</p>")
    parts.append("<h2>Licences and labels</h2><table><tr><th>Candidate</th><th>What it is</th><th>Code licence</th>"
                 "<th>Weights licence</th><th>Version</th><th>Notes</th></tr>")
    for n, c in report["candidates"].items():
        i = c["info"]
        what = ("voice-conditioned on the enrollment" if i["mechanism"] == "target_conditioned"
                else "blind separation, then voiceprint selection (not voice-conditioned)")
        parts.append(f"<tr><td>{e(i['title'])}</td><td>{e(what)}</td><td>{e(i['code_licence'])}</td>"
                     f"<td>{e(i['weights_licence'])}</td><td>{e(i['version'])}</td><td>{e(i['notes'])}</td></tr>")
    parts.append("</table>")
    for key, title in (("listening", "Blind listening (synthetic Egyptian mixes)"),
                       ("real_clips", "Blind listening (real recordings, no reference scores)")):
        items = report.get(key) or []
        parts.append(f"<h2>{e(title)}</h2>")
        if not items:
            parts.append("<p>None provided.</p>")
        for it in items:
            players = "".join(f"<li>{e(x['label'])}: <audio controls preload=none src=\"{e(x['file'])}\"></audio></li>"
                              for x in it["items"])
            key_rows = ", ".join(f"{e(k)} = {e(v)}" for k, v in sorted(it["key"].items()))
            parts.append(f"<h4>{e(it['clip'])}</h4><p>Original mixture: <audio controls preload=none "
                         f"src=\"{e(it['mix'])}\"></audio>"
                         + (f" Enrollment: <audio controls preload=none src=\"{e(it['enroll'])}\"></audio>"
                            if it.get("enroll") else "") + f"</p><ul>{players}</ul>"
                         f"<details><summary>Reveal which is which</summary><p>{key_rows}</p></details>")
    parts.append("<h2>Limitations</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in report["limitations"]) + "</ul>")
    return "".join(parts)


OVERLAP_ONLY = ("overlap_2", "overlap_3plus")
