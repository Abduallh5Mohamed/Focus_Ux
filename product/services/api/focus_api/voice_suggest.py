"""Which detected voice most likely belongs to the chosen face?

Evidence is on-screen only, gathered at enrollment time: how long each voice
speaks alone while the chosen face is visible. No lip or speaking-face score is
used (not measured as useful). The result is a suggestion; the user confirms
by listening, and nothing here reaches the extraction request.
"""
from __future__ import annotations

MIN_EVIDENCE_S = 1.5   # least visible solo speech that can support a suggestion
MIN_RATIO = 1.5        # the top voice must clearly beat the runner-up

SUGGESTION_NOTE = "اقتراح فقط: الترتيب مبني على من يتكلم أثناء ظهور الوجه، وأنت اللي تأكد بالسماع."


def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _overlap(spans, other) -> float:
    total, j = 0.0, 0
    for a, b in spans:
        for c, d in other:
            lo, hi = max(a, c), min(b, d)
            if hi > lo:
                total += hi - lo
    return total


def _subtract(spans, cuts):
    out = []
    for a, b in spans:
        cur = a
        for c, d in cuts:
            if d <= cur or c >= b:
                continue
            if c > cur:
                out.append([cur, c])
            cur = max(cur, d)
        if cur < b:
            out.append([cur, b])
    return out


def rank_voices(analysis: dict, visible: list[dict] | None) -> dict:
    """``analysis`` is the stored analysis; ``visible`` the face's on-screen spans
    in ms, or None when visibility could not be measured."""
    if isinstance(visible, dict) and visible.get('kind') == 'av_sync_v1':
        return rank_sync(analysis, visible)
    diar = analysis["diarization"]
    overlaps = _merge([[o["start"], o["end"]] for o in diar["overlaps"]])
    seen = _merge([[v["start_ms"] / 1000, v["end_ms"] / 1000] for v in visible or []])
    rows = []
    for index, speaker in enumerate(analysis["speakers"]):
        own = _merge([[t["start"], t["end"]] for t in diar["turns"] if t["speaker"] == speaker["speaker"]])
        solo = _subtract(own, overlaps)
        rows.append({
            "index": index, "talk_s": round(sum(b - a for a, b in own), 2),
            "visible_talk_s": round(_overlap(solo, seen), 2),
        })
    on_screen = visible is not None
    key = (lambda r: (-r["visible_talk_s"], -r["talk_s"], r["index"])) if on_screen \
        else (lambda r: (-r["talk_s"], r["index"]))
    rows.sort(key=key)
    suggested = None
    if on_screen and rows and rows[0]["visible_talk_s"] >= MIN_EVIDENCE_S:
        runner = rows[1]["visible_talk_s"] if len(rows) > 1 else 0.0
        if rows[0]["visible_talk_s"] >= MIN_RATIO * runner:
            suggested = rows[0]["index"]
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        row["suggested"] = row["index"] == suggested
    return {"evidence": "on_screen" if on_screen else "talk_time_only", "candidates": rows,
            "note": SUGGESTION_NOTE}


def rank_sync(analysis, evidence):
    """Compare ASD scores during distinct solo turns. Abstain on all-overlap clips.

    Raw TalkNet scores are logits, not confidence percentages. These thresholds
    are provisional and must not authorize an irreversible/automatic enrollment.
    """
    import math
    diar=analysis['diarization'];rows=[]
    cuts=_merge([[o['start'],o['end']] for o in diar['overlaps']])
    for i,speaker in enumerate(analysis['speakers']):
        own=_merge([[t['start'],t['end']] for t in diar['turns'] if t['speaker']==speaker['speaker']])
        solo=_subtract(own,cuts);weighted=0.;seconds=0.;positive=0.
        for window in evidence.get('windows',[]):
            value=window.get('score')
            if not isinstance(value,(int,float)) or not math.isfinite(value):continue
            a,b=window['start_ms']/1000,window['end_ms']/1000
            dt=_overlap(solo,[[a,b]])
            if dt<=0:continue
            seconds+=dt;weighted+=dt*value;positive+=dt*(value>0)
        score=weighted/seconds if seconds else None
        rows.append({'index':i,'talk_s':round(sum(b-a for a,b in own),2),
            'visible_talk_s':round(seconds,2),'sync_score':score,
            'positive_fraction':positive/seconds if seconds else 0.,
            'eligible':bool(speaker.get('usable')) and seconds>=1.5})
    rows.sort(key=lambda r: -(r['sync_score'] if r['sync_score'] is not None else -1e9))
    eligible=[r for r in rows if r['eligible']];chosen=None
    # A single usable voice cannot discriminate identities. Never turn absence
    # of a competing fingerprint into evidence that the selected face matches.
    if len(eligible)>=2:
        a,b=eligible[:2]
        if a['sync_score']>0 and a['sync_score']-b['sync_score']>=1 and a['positive_fraction']>=.7:
            chosen=a['index']
    for rank,row in enumerate(rows,1):
        row['rank']=rank;row['suggested']=row['index']==chosen
    note='اقتراح تجريبي من تزامن الوجه والصوت؛ أكّد الهوية بالسماع قبل العزل.'
    if chosen is None:
        note='تزامن الوجه والصوت لم يحسم الهوية. التداخل أو نقص عينات مستقلة يمنع الربط التلقائي؛ اختار بالسماع أو ارفع تسجيلًا للشخص وحده.'
    return {'evidence':'av_sync','candidates':rows,'note':note}
