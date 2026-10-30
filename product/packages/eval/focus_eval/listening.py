"""Blind listening test: kit builder and answer summariser (stdlib + numpy-free).

Each item is a pair of clips, "A" and "B", where one is the unprocessed mixture
and the other the pipeline output for the same target. Which is which is
random per item and recorded only in ``key.json``, which stays with the
organiser. Raters get ``kit/`` (anonymised wavs + ``scoring_sheet.csv``).
Control items (the same clip twice) detect raters who always prefer one side.
"""
from __future__ import annotations

import csv
import json
import math
import random
import shutil
from pathlib import Path

SHEET_COLUMNS = [
    "rater_id", "item", "preferred", "target_clear_A", "target_clear_B",
    "other_voices_audible_A", "other_voices_audible_B", "artifacts_A", "artifacts_B", "notes",
]
PREFERRED_VALUES = ("A", "B", "same")
RATING_COLUMNS = SHEET_COLUMNS[3:9]
INSTRUCTIONS = (
    "For each item first play item_NN_ref.wav: it is the voice to follow (a clean recording of that person). "
    "Then play A and B and listen for that voice only. "
    "Preferred: which clip makes that voice easier to follow (A, B or same). "
    "Rate each clip 1-5: target_clear (1 = cannot follow, 5 = perfectly clear), "
    "other_voices_audible (1 = none audible, 5 = very loud), artifacts (1 = none, 5 = very distracting). "
    "Do not discuss answers with other raters.\n")


def build_kit(pairs: list[dict], out_dir: str | Path, *, seed: int, controls: int = 2) -> dict:
    """pairs: [{"clip_id","target","original","processed","reference"}] (wav paths; reference = clean
    recording of the target voice, given to raters as item_NN_ref.wav).

    Writes <out>/kit/{item_NN_A.wav,item_NN_B.wav,scoring_sheet.csv,INSTRUCTIONS.txt}
    and <out>/key.json (organiser only). Deterministic for a given seed.
    """
    if not pairs:
        raise ValueError("no clip pairs to build a listening kit from")
    for p in pairs:
        if not p.get("reference"):
            raise ValueError(f"{p.get('clip_id')}/{p.get('target')}: no target reference; raters could not tell which voice to follow")
    rng = random.Random(seed)
    items = [dict(p, kind="test") for p in pairs]
    controls = min(controls, len(pairs))
    for p in rng.sample(pairs, controls):
        items.append(dict(p, kind="control"))
    rng.shuffle(items)
    out = Path(out_dir)
    kit = out / "kit"
    if kit.exists():
        raise FileExistsError(f"{kit} already exists; refusing to overwrite a kit")
    kit.mkdir(parents=True)
    key = {"seed": seed, "items": {}}
    for i, it in enumerate(items, 1):
        name = f"item_{i:02d}"
        if it["kind"] == "control":
            a_src, b_src, a_is, b_is = it["processed"], it["processed"], "processed", "processed"
        elif rng.random() < 0.5:
            a_src, b_src, a_is, b_is = it["processed"], it["original"], "processed", "original"
        else:
            a_src, b_src, a_is, b_is = it["original"], it["processed"], "original", "processed"
        shutil.copyfile(it["reference"], kit / f"{name}_ref.wav")
        shutil.copyfile(a_src, kit / f"{name}_A.wav")
        shutil.copyfile(b_src, kit / f"{name}_B.wav")
        key["items"][name] = {"A": a_is, "B": b_is, "kind": it["kind"],
                              "clip_id": it["clip_id"], "target": it["target"]}
    with (kit / "scoring_sheet.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(SHEET_COLUMNS)
        for name in key["items"]:
            w.writerow(["", name] + [""] * (len(SHEET_COLUMNS) - 2))
    (kit / "INSTRUCTIONS.txt").write_text(INSTRUCTIONS, encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    return {"kit": str(kit), "key": str(out / "key.json"), "n_items": len(items),
            "n_controls": controls}


def _sign_test_p(wins: int, losses: int) -> float | None:
    """Two-sided exact binomial sign test against 50/50; ties excluded."""
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n * 2
    return round(min(1.0, p), 4)


def _read_sheet(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    missing = [c for c in SHEET_COLUMNS if rows and c not in rows[0]]
    if missing:
        raise ValueError(f"{path.name}: missing column(s) {', '.join(missing)}")
    return rows


def summarize_answers(key_path: str | Path, sheets: list[str | Path]) -> dict:
    """Combine filled sheets. Every problem in a sheet is reported, never skipped silently."""
    key = json.loads(Path(key_path).read_text("utf-8"))["items"]
    problems, raters = [], set()
    wins = losses = ties = 0
    by_kind = {"control": {"A": 0, "B": 0, "same": 0}}
    rating = {"processed": {"target_clear": [], "other_voices_audible": [], "artifacts": []},
              "original": {"target_clear": [], "other_voices_audible": [], "artifacts": []}}
    per_item: dict[str, dict] = {}
    answered = 0
    for sheet in sheets:
        sheet = Path(sheet)
        sheet_rows = _read_sheet(sheet)
        present = {(r["item"] or "").strip() for r in sheet_rows}
        for name in key:
            if name not in present:
                problems.append(f"{sheet.name}:{name}: item missing from the sheet")
        for row in sheet_rows:
            rater, item = (row["rater_id"] or "").strip(), (row["item"] or "").strip()
            pref = (row["preferred"] or "").strip()
            where = f"{sheet.name}:{item or '?'}"
            if item not in key:
                problems.append(f"{where}: unknown item")
                continue
            if not rater:
                problems.append(f"{where}: rater_id is empty")
                continue
            if pref == "":
                problems.append(f"{where}: no answer")
                continue
            if pref not in PREFERRED_VALUES:
                problems.append(f"{where}: preferred must be A, B or same, got {pref!r}")
                continue
            raters.add(rater)
            answered += 1
            meta = key[item]
            if meta["kind"] == "control":
                by_kind["control"][pref] += 1
                continue
            chosen = None if pref == "same" else meta[pref]
            if chosen == "processed":
                wins += 1
            elif chosen == "original":
                losses += 1
            else:
                ties += 1
            slot = per_item.setdefault(item, {"processed": 0, "original": 0, "same": 0,
                                              "clip_id": meta["clip_id"], "target": meta["target"]})
            slot[chosen or "same"] += 1
            for side in ("A", "B"):
                for col in ("target_clear", "other_voices_audible", "artifacts"):
                    raw = (row[f"{col}_{side}"] or "").strip()
                    if not raw:
                        continue
                    try:
                        val = int(raw)
                        if not 1 <= val <= 5:
                            raise ValueError
                    except ValueError:
                        problems.append(f"{where}: {col}_{side} must be 1-5, got {raw!r}")
                        continue
                    rating[meta[side]][col].append(val)
    c = by_kind["control"]
    n_control = sum(c.values())
    control_ok = None if n_control == 0 else c["same"] / n_control
    mean = lambda v: round(sum(v) / len(v), 3) if v else None
    return {
        "raters": sorted(raters), "n_answers": answered,
        "processed_preferred": wins, "original_preferred": losses, "no_preference": ties,
        "processed_preference_rate": round(wins / (wins + losses), 4) if wins + losses else None,
        "sign_test_p_two_sided": _sign_test_p(wins, losses),
        "control_same_rate": control_ok,
        "control_warning": (None if control_ok is None or control_ok >= 0.5 else
                            "raters often preferred one side of identical clips; treat results with caution"),
        "mean_ratings": {k: {c_: mean(v) for c_, v in cols.items()} for k, cols in rating.items()},
        "per_item": per_item, "problems": problems,
        "note": "Preference counts exclude control items. Small samples: read the p-value, not the rate alone.",
    }
