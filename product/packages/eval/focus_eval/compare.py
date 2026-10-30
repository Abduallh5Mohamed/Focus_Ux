"""Compare two evaluation reports (baseline vs candidate) and flag regressions."""
from __future__ import annotations

from dataclasses import dataclass

from . import EVALUATION_POLICY
from .dataset import VERIFIED

DEFAULT_SI_SDRI_DROP_DB = 0.5
DEFAULT_CER_INCREASE = 0.02


@dataclass
class Thresholds:
    si_sdri_drop_db: float = DEFAULT_SI_SDRI_DROP_DB
    cer_increase: float = DEFAULT_CER_INCREASE  # absolute (0.02 = 2 points)
    include_provisional: bool = False


def _key(row: dict) -> tuple[str, str]:
    return row["clip_id"], row["speaker_id"]


def _usable(row: dict) -> bool:
    return row["audio_status"] == "ok"


def compare_reports(base: dict, cand: dict, th: Thresholds | None = None) -> dict:
    th = th or Thresholds()
    warnings: list[str] = []
    inconclusive: list[str] = []
    if any(report.get("evaluation_policy") != EVALUATION_POLICY
           or report.get("expected_targets") is None for report in (base, cand)):
        inconclusive.append("evaluation policy is missing or outdated; regenerate both reports")
    if base["dataset_id"] != cand["dataset_id"]:
        inconclusive.append(f"dataset differs: {base['dataset_id']!r} vs {cand['dataset_id']!r}")
    fb, fc = base.get("dataset_fingerprint"), cand.get("dataset_fingerprint")
    if not fb or not fc or fb != fc:
        inconclusive.append("dataset content differs (fingerprint mismatch or missing); reports score different data")
    b_rows = {_key(r): r for r in base["rows"]}
    c_rows = {_key(r): r for r in cand["rows"]}
    common = sorted(set(b_rows) & set(c_rows))
    only_base = sorted(set(b_rows) - set(c_rows))
    only_cand = sorted(set(c_rows) - set(b_rows))
    regressions: list[dict] = []

    def add(kind: str, key, **detail):
        regressions.append({"kind": kind, "clip_id": key[0], "speaker_id": key[1], **detail})

    # New reports retain the manifest's READY targets even if rows are removed.
    # For older reports, at least require coverage of the union of observed rows.
    expected = set(b_rows) | set(c_rows)
    for report in (base, cand):
        expected.update(tuple(k) for k in report.get("expected_targets", []))
    for key in sorted(expected):
        b, c = b_rows.get(key), c_rows.get(key)
        if b is None or not _usable(b):
            inconclusive.append(f"baseline target is not scorable: {key[0]}/{key[1]}")
        if c is None:
            add("missing_in_candidate", key)
        elif not _usable(c):
            add("audio_lost", key, candidate_status=c["audio_status"])
    cer_b = {"errors": 0, "total": 0}
    cer_c = {"errors": 0, "total": 0}
    for key in common:
        b, c = b_rows[key], c_rows[key]
        if not (_usable(b) and _usable(c)):
            continue
        drop = b["si_sdri"] - c["si_sdri"]
        if drop > th.si_sdri_drop_db:
            add("si_sdri_drop", key, baseline=b["si_sdri"], candidate=c["si_sdri"], drop_db=round(drop, 3))
        if c.get("wrong_person") and not b.get("wrong_person"):
            add("wrong_person", key, baseline_margin_db=b.get("margin_db"), candidate_margin_db=c.get("margin_db"))
        use_text = b["reference_status"] == VERIFIED or th.include_provisional
        if use_text and "cer" in b:
            if "cer" not in c:
                add("transcript_lost", key, candidate_text_status=c["text_status"])
            else:
                cer_b["errors"] += b["char_errors"]; cer_b["total"] += b["char_total"]
                cer_c["errors"] += c["char_errors"]; cer_c["total"] += c["char_total"]
                if c["cer"] - b["cer"] > th.cer_increase:
                    add("cer_increase", key, baseline=b["cer"], candidate=c["cer"])

    agg = None
    if cer_b["total"]:
        cb = cer_b["errors"] / cer_b["total"]
        cc = cer_c["errors"] / cer_c["total"]
        agg = {"baseline_cer": round(cb, 4), "candidate_cer": round(cc, 4), "delta": round(cc - cb, 4)}
        if cc - cb > th.cer_increase:
            regressions.append({"kind": "cer_increase_overall", **agg})
    n_scored = sum(1 for k in common if _usable(b_rows[k]) and _usable(c_rows[k]))
    if n_scored == 0:
        inconclusive.append("no targets were scored in both reports; nothing was compared")
    if inconclusive:
        status = "inconclusive"
    elif regressions:
        status = "regression"
    else:
        status = "pass"
    return {
        "status": status,
        "inconclusive_reasons": inconclusive,
        "n_scored_in_both": n_scored,
        "baseline": base["run_label"],
        "candidate": cand["run_label"],
        "thresholds": {
            "si_sdri_drop_db": th.si_sdri_drop_db,
            "cer_increase": th.cer_increase,
            "include_provisional": th.include_provisional,
        },
        "n_compared": len(common),
        "only_in_baseline": [list(k) for k in only_base],
        "only_in_candidate": [list(k) for k in only_cand],
        "overall_cer": agg,
        "warnings": warnings,
        "regressions": regressions,
        "ok": status == "pass",
    }
