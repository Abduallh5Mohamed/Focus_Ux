"""report.html for the real-weights experiment: completion summary first, then tables and players.

Everything numeric is read from report.json (measured); prose that interprets it lives in the
conclusion file written after the numbers were read. Relative audio links: keep report.html
next to the listen/ folder.
"""
from __future__ import annotations

import html

from . import experiment_metrics as X
from .experiment_readiness import NOT_APPROVED

CSS = """body{font:15px/1.5 system-ui,sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;color:#1b1f23}
table{border-collapse:collapse;margin:8px 0 18px;font-size:13px}td,th{border:1px solid #c8ccd0;padding:4px 8px;text-align:right}
th{background:#eef1f4}td:first-child,th:first-child{text-align:left}.warn{background:#fff4d6;padding:8px 12px;border-left:4px solid #d9a400}
.bad{background:#fde7e7;padding:8px 12px;border-left:4px solid #c62828}.ok{background:#e6f4ea;padding:8px 12px;border-left:4px solid #2e7d32}
details{margin:6px 0}audio{height:30px;vertical-align:middle}pre{background:#f6f8fa;padding:10px;overflow:auto;white-space:pre-wrap;font-size:12px}
.mono{font-family:ui-monospace,monospace;font-size:12px}h2{margin-top:32px;border-bottom:1px solid #ddd}"""

E = html.escape
COLS = (("si_sdri_db", "SI-SDRi dB"), ("target_retention", "target retention"), ("leakage_share", "leakage share"),
        ("leakage_ratio", "leakage ratio"), ("muted_share", "muted"), ("stoi", "STOI"), ("pesq", "PESQ wb"))


def f(v, pct=False):
    if v is None:
        return "–"
    return f"{v * 100:.0f} %" if pct else f"{v:g}"


def _row(label, p, extra=""):
    cells = "".join(f"<td>{f(p.get(k), k == 'muted_share')}</td>" for k, _ in COLS)
    return f"<tr><td>{E(label)}</td>{cells}{extra}</tr>"


def _head(extra=""):
    return "<tr><th>output</th>" + "".join(f"<th>{n}</th>" for _, n in COLS) + extra + "</tr>"


def _keys(report):
    ok = [n for n, c in report["candidates"].items() if c.get("inference_completed")]
    return ok


def summary_html(report, readiness, conclusion_head=""):
    cands, groups = report["candidates"], report["groups"]
    ok = _keys(report)
    loaded = [n for n, c in cands.items() if not c["blocked"]]
    failed = {n: c["blocked"] for n, c in cands.items() if c["blocked"]}
    per_mix_err = {n: c["errors"] for n, c in cands.items() if c["errors"]}
    out = ["<div class='warn'><b>Scope.</b> English LibriSpeech read speech (not Egyptian Arabic), "
           f"device: {E(str(report['basis']['device']))} (CPU, not the RTX 3050; the laptop was not reachable from here). "
           f"Peak VRAM: {E(report['peak_vram'])}. Oracle region labels, 12 mixes of about 10 s.</div>"]
    if not ok:
        out.append("<div class='bad'><b>BLOCKED: no candidate completed real inference. Nothing here shows that "
                   "extraction works.</b></div>")
    li = []
    li.append(f"<li><b>Real pretrained models loaded:</b> {E(', '.join(loaded) or 'none')}.</li>")
    li.append(f"<li><b>Completed inference:</b> {E(', '.join(ok) or 'none')} "
              f"(on {', '.join(str(sum(1 for m in c['mixes'].values() if 'hybrid' in m)) for n, c in cands.items() if n in ok)}"
              f" of {len(report['mixes'])} mixes respectively).</li>")
    if failed or per_mix_err:
        errs = "".join(f"<li class='mono'>{E(n)}: {E(b['type'])}: {E(b['message'])}</li>" for n, b in failed.items())
        errs += "".join(f"<li class='mono'>{E(n)} {E(e['mix'])} {E(e['stage'])}: {E(e['type'])}: {E(e['message'])}</li>"
                        for n, es in per_mix_err.items() for e in es)
        li.append(f"<li><b>Errors (exact text):</b><ul>{errs}</ul></li>")
    else:
        li.append("<li><b>Errors:</b> none; every candidate loaded and ran on every mix.</li>")
    rows = []
    for g, label in groups.items():
        for n in ok:
            h = report["pooled"][g].get(f"{n}:hybrid", {}).get("overlap") or {}
            r = report["pooled"][g].get(f"{n}:raw", {}).get("overlap") or {}
            rows.append(f"<tr><td>{E(label)}</td><td>{E(n)}</td><td>{f(r.get('si_sdri_db'))}</td>"
                        f"<td>{f(h.get('si_sdri_db'))}</td><td>{f(h.get('target_retention'))}</td>"
                        f"<td>{f(h.get('leakage_ratio'))}</td><td>{f(h.get('stoi'))}</td><td>{f(h.get('pesq'))}</td></tr>")
        b = report["pooled"][g]["gated_baseline"]["overlap"]
        rows.append(f"<tr><td>{E(label)}</td><td><i>gated baseline</i></td><td>–</td><td>{f(b.get('si_sdri_db'))}</td>"
                    f"<td>{f(b.get('target_retention'))}</td><td>–</td><td>–</td><td>–</td></tr>")
    li.append("<li><b>Measured separation quality in overlap regions</b> (pooled per group, mean over mixes):"
              "<table><tr><th>group</th><th>candidate</th><th>raw SI-SDRi dB</th><th>hybrid SI-SDRi dB</th>"
              "<th>retention</th><th>leakage ratio</th><th>STOI</th><th>PESQ</th></tr>" + "".join(rows) + "</table></li>")
    first = report["mixes"][0]["id"]
    links = "".join(f"<a href='#mix-{m['id']}'>{m['id']}</a> " for m in report["mixes"])
    li.append(f"<li><b>Playable examples:</b> one player folder per mix below (also in <span class='mono'>listen/&lt;mix&gt;/</span>): {links}</li>")
    t = []
    for n in ok:
        tm = cands[n]["timing"]
        rw, hy = tm.get("raw_whole_mixture", {}), tm.get("hybrid", {})
        t.append(f"<tr><td>{E(n)}</td><td>{f(cands[n]['load_seconds'])}</td><td>{f(rw.get('seconds_per_mix'))}</td>"
                 f"<td>{f(rw.get('rtf'))}</td><td>{f(hy.get('seconds_per_mix'))}</td><td>{f(hy.get('rtf'))}</td>"
                 f"<td>{f(hy.get('rtf_overlap'))}</td><td>{E(str(rw.get('peak_vram', 'not measured (CPU)')))}</td></tr>")
    li.append("<li><b>Processing times (CPU wall seconds, 10 s clips; RTF = seconds / audio seconds):</b>"
              "<table><tr><th>candidate</th><th>load s</th><th>raw s/mix</th><th>raw RTF</th><th>hybrid s/mix</th>"
              "<th>hybrid RTF</th><th>overlap RTF</th><th>peak VRAM</th></tr>" + "".join(t) + "</table></li>")
    v = []
    for n, c in readiness["candidates"].items():
        v.append(f"<tr><td>{E(n)}</td><td>{c['model_sample_rate_hz']} Hz</td><td>{E(c['licence_status'])}</td>"
                 f"<td>{E(c['weights_licence'])}</td><td>{E(c['code_licence'])}</td></tr>")
    li.append("<li><b>Versions, weights sources, licences:</b> details in the readiness table below."
              "<table><tr><th>candidate</th><th>rate</th><th>licence status</th><th>weights licence</th>"
              "<th>code licence</th></tr>" + "".join(v) + "</table></li>")
    vd = []
    best = {}
    for g, label in groups.items():
        for n, d in report["verdicts"][g].items():
            vd.append(f"<li>{E(label)} / {E(n)}: <b>{'improves' if d['improves'] else 'does not improve'}</b>"
                      + (f" ({E('; '.join(d['reasons']))})" if d["reasons"] else "") + "</li>")
            if d["improves"]:
                best.setdefault(g, []).append(n)
    li.append("<li><b>Against the gated baseline</b> (rule in <i>Comparison rule</i>; the baseline mutes overlap, "
              f"so its SI-SDRi is the -30 dB floor offset):<ul>{''.join(vd)}</ul></li>")
    if best:
        rec = []
        for g, names in best.items():
            top = max(names, key=lambda n: report["pooled"][g][f"{n}:hybrid"]["overlap"]["si_sdri_db"])
            lic = readiness["candidates"][top]["licence_status"]
            rec.append(f"{E(groups[g])}: {E(top)} ({E(lic)}"
                       + ("; <b>not approved for deployment</b>" if lic in NOT_APPROVED else "; licence review still open")
                       + ")")
        li.append("<li><b>Recommended validated model:</b> " + "; ".join(rec) + ". Validated only on English LibriSpeech, CPU.</li>")
    else:
        li.append("<li><b>Recommended validated model:</b> none. No candidate met the stated rule in any group.</li>")
    li.append("<li><b>Smallest change to integrate (proposal only, not built):</b> see the Conclusion section.</li>")
    out.append("<ol>" + "".join(li) + "</ol>")
    return "".join(out)


def pooled_tables(report):
    out = []
    for g, label in report["groups"].items():
        if g not in report["pooled"]:
            continue
        pg = report["pooled"][g]
        n = len([m for m in report["mixes"] if str(m["n_overlap"]) == g])
        out.append(f"<h3>{E(label)} - {n} mixes, overlap region (ranking basis)</h3><table>{_head()}")
        out.append(_row("gated baseline", pg["gated_baseline"]["overlap"]))
        for k, e in pg.items():
            if k != "gated_baseline":
                out.append(_row(k, e["overlap"]))
        out.append("</table>")
        out.append(f"<p>Whole clip (context only):</p><table>{_head()}")
        for k, e in pg.items():
            out.append(_row(k, e["clip"]))
        out.append("</table>")
        out.append("<p>Hybrid SI-SDRi dB in overlap by target level and by scenario:</p>"
                   "<table><tr><th>output</th>" + "".join(f"<th>{E(c)}</th>" for c in
                   list(next(iter(pg.values()))["by_level"]) + list(next(iter(pg.values()))["by_scenario"])) + "</tr>")
        for k, e in pg.items():
            if k == "gated_baseline" or k.endswith(":hybrid"):
                out.append(f"<tr><td>{E(k)}</td>" + "".join(f"<td>{f(p.get('si_sdri_db'))}</td>" for p in
                           list(e["by_level"].values()) + list(e["by_scenario"].values())) + "</tr>")
        out.append("</table>")
    return "".join(out)


def per_mix(report):
    cands = {n: c for n, c in report["candidates"].items() if c.get("inference_completed")}
    out = ["<h2 id='permix'>Per mix (overlap region)</h2><table><tr><th>mix</th><th>group</th><th>scenario</th>"
           "<th>target dB</th><th>output</th><th>SI-SDRi</th><th>retention</th><th>leak ratio</th><th>STOI</th>"
           "<th>PESQ</th><th>muted</th><th>wall s</th></tr>"]
    return "".join(out) + _per_mix_rows(report, cands) + "</table>"


def _per_mix_rows(report, cands):
    rows = []
    for m in report["mixes"]:
        i = m["id"]
        for n in cands:
          for k in ("raw", "hybrid"):
            label = f"{n} {k}"
            rec = cands[n]["mixes"].get(i, {}).get(k)
            s = (rec or {}).get("scores", {}).get("overlap") or {}
            rows.append(f"<tr><td>{i}</td><td>{m['n_overlap']}-spk</td><td>{E(str(m.get('scenario')))}</td>"
                        f"<td>{m['target_rel_db']:+.0f}</td><td>{E(label)}</td>"
                        + "".join(f"<td>{f(s.get(c), c == 'muted_share')}</td>" for c in
                                  ("si_sdri_db", "target_retention", "leakage_ratio", "stoi", "pesq", "muted_share"))
                        + f"<td>{f((rec or {}).get('wall_s'))}</td></tr>")
    return "".join(rows)


def players(report):
    out = ["<h2 id='listen'>Listening folders</h2><p>Files are FLAC, 16 kHz mono, in <span class='mono'>listen/&lt;mix&gt;/</span>. "
           "Raw = model on the whole mixture. Hybrid = extraction only in overlap, target solo turns passed through. "
           "Residual = mixture minus raw extraction. Files whose peak exceeded full scale were scaled down for playback only.</p>"]
    meta = {m["id"]: m for m in report["mixes"]}
    for i, l in report["listening"].items():
        m = meta[i]
        out.append(f"<details id='mix-{i}'><summary><b>{i}</b> - {m['n_overlap']}-speaker overlap, {E(str(m.get('scenario')))}, "
                   f"target {m['target_rel_db']:+.0f} dB, target {E(m['target'])}</summary><table>")
        for it in l["files"]:
            out.append(f"<tr><td>{E(it['label'])}</td><td><audio controls preload='none' src='{E(it['file'])}'></audio></td></tr>")
        out.append("</table></details>")
    return "".join(out)


def readiness_html(readiness):
    out = ["<h2 id='ready'>Readiness and licence record</h2>",
           "<p>Packages: " + ", ".join(f"{E(k)} {E(v)}" for k, v in readiness["packages"].items()) + "</p>"]
    for n, c in readiness["candidates"].items():
        cls = "bad" if c["licence_status"] in NOT_APPROVED else "ok"
        out.append(f"<h3>{E(c['title'])} ({E(n)})</h3><div class='{cls}'><b>{E(c['licence_status'])}</b>. "
                   f"{E(c['licence_reason'])}</div><table>"
                   f"<tr><td>weights source</td><td style='text-align:left'>{E(c['weights_source'])}</td></tr>"
                   f"<tr><td>code source</td><td style='text-align:left'>{E(c['code_source'])}</td></tr>"
                   f"<tr><td>model sample rate</td><td style='text-align:left'>{c['model_sample_rate_hz']} Hz</td></tr>"
                   f"<tr><td>enrollment (reference) audio</td><td style='text-align:left'>{E(c['enrollment_feed'])}</td></tr>"
                   f"<tr><td>code licence</td><td style='text-align:left'>{E(c['code_licence'])}</td></tr>"
                   f"<tr><td>weights licence</td><td style='text-align:left'>{E(c['weights_licence'])}</td></tr>"
                   f"<tr><td>licence checked</td><td style='text-align:left'>{E(c['licence_checked'])}</td></tr>"
                   f"<tr><td>weight files (sha256, bytes)</td><td style='text-align:left' class='mono'>"
                   + "<br>".join(f"{E(k)}  {v}  {c['weight_file_bytes'].get(k)}" for k, v in c["weight_file_sha256"].items())
                   + f"</td></tr><tr><td>code files ({len(c['code_files_sha256'])}, sha256)</td>"
                   "<td style='text-align:left' class='mono'><details><summary>show</summary>"
                   + "<br>".join(f"{E(k)}  {v}" for k, v in c["code_files_sha256"].items())
                   + "</details></td></tr></table>")
    return "".join(out)


def render_html(report, readiness, conclusion="", rule="", commands="") -> str:
    b = report["basis"]
    parts = [f"<!doctype html><meta charset='utf-8'><title>Real target-speaker extraction experiment</title><style>{CSS}</style>",
             "<h1>Real target-speaker extraction experiment</h1>",
             f"<p>Data: {E(b['data'])}; language label <b>{E(b['language'])}</b>. Seed {b['seed']}. "
             f"Device {E(str(b['device']))}, {b.get('cpu_threads')} CPU threads. Embedder for the voiceprint check: {E(b['embedder'])}.</p>",
             "<h2>Completion summary</h2>", summary_html(report, readiness),
             "<h2>Conclusion</h2>", f"<pre>{E(conclusion) if conclusion else 'not written yet'}</pre>",
             "<h2>Comparison rule (written before any result was read)</h2>", f"<pre>{E(rule)}</pre>",
             "<h2>Results pooled per group</h2>",
             "<p>2-speaker and 3-speaker groups are never pooled together. Candidates are shown raw (whole mixture) and hybrid "
             "next to the gated baseline. 8 kHz models (USEF-TSE, SpEx+) are scored after resampling back to 16 kHz; "
             "their content above 4 kHz is gone, which lowers STOI/PESQ against the 16 kHz reference. "
             "STOI: pystoi (non-extended). PESQ: pesq package (ITU-T P.862.2 wideband, reference C code, own licence). "
             "Quality scores are computed on the overlap-region samples; a fully muted output has none (–).</p>",
             pooled_tables(report), per_mix(report), players(report), readiness_html(readiness),
             "<h2>Repeat on the RTX 3050</h2>", f"<pre>{E(commands)}</pre>"]
    return "".join(parts)
