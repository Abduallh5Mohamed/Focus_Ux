"""Recording manifest for the Egyptian voice set: loading and validation.

    manifest.json   (schema focus-voice-recordings/1)
    audio/...       recordings (WAV, or a video file for 'leaves_frame')
    annotations/... who-spoke-when JSON for real overlap recordings

See product/datasets/egyptian_voice/RECORDING_GUIDE.md.
"""
from __future__ import annotations

import json
import wave
from pathlib import Path

SCHEMA = "focus-voice-recordings/1"
KINDS = ("solo", "overlap", "leaves_frame")
VOLUMES = ("quiet", "normal", "loud")
NOISES = ("quiet", "street", "cafe", "fan", "traffic", "other")
ROOMS = ("small", "large", "echoey", "car", "outdoor")
MIN_SPEAKERS = 3
MIN_SOLO_S = 60.0
MEDIA_SUFFIXES = (".wav", ".mp4", ".mov", ".mkv", ".webm")


class VoiceDatasetError(ValueError):
    pass


def load_manifest(root: str | Path) -> dict:
    p = Path(root) / "manifest.json"
    if not p.is_file():
        raise VoiceDatasetError(f"{p} not found")
    try:
        raw = json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise VoiceDatasetError(f"{p}: invalid JSON ({exc})") from exc
    if raw.get("schema") != SCHEMA:
        raise VoiceDatasetError(f"unsupported schema {raw.get('schema')!r}; expected {SCHEMA}")
    return raw


def wav_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError, OSError):
        return None


def validate(root: str | Path, m: dict | None = None) -> dict:
    """Returns {"errors": [...], "warnings": [...], "coverage": {...}}.
    Errors block use of the set; warnings are missing coverage."""
    root = Path(root)
    m = m or load_manifest(root)
    errors, warnings = [], []
    consents = {}
    for c in m.get("consents", []):
        cid = str(c.get("id", ""))
        if not cid or cid in consents:
            errors.append(f"consent id missing or duplicated: {cid!r}")
        consents[cid] = c
        if not c.get("signed"):
            errors.append(f"consent {cid}: not signed")
        if not c.get("speaker_id"):
            errors.append(f"consent {cid}: no speaker_id")
    seen, solo_s, speakers = set(), {}, set()
    cond_seen = {"volume": set(), "noise": set(), "room": set(), "distance": set()}
    kinds = {k: 0 for k in KINDS}
    overlap_sizes = set()
    for r in m.get("recordings", []):
        rid = str(r.get("id", ""))
        tag = f"[{rid}]"
        if not rid or rid in seen:
            errors.append(f"{tag} recording id missing or duplicated")
        seen.add(rid)
        kind = r.get("kind")
        if kind not in KINDS:
            errors.append(f"{tag} kind must be one of {KINDS}, got {kind!r}")
            continue
        kinds[kind] += 1
        spk = [str(s) for s in r.get("speakers", [])]
        speakers.update(spk)
        f = root / str(r.get("file", ""))
        if not r.get("file") or not f.is_file():
            errors.append(f"{tag} file missing: {r.get('file')!r}")
        elif f.suffix.lower() not in MEDIA_SUFFIXES:
            errors.append(f"{tag} unsupported file type {f.suffix!r}")
        for s in spk:
            ok = any(consents.get(cid, {}).get("speaker_id") == s and cid in consents
                     for cid in r.get("consent_ids", []))
            if not ok:
                errors.append(f"{tag} speaker {s}: no signed consent listed for this speaker")
        if kind == "solo":
            if len(spk) != 1:
                errors.append(f"{tag} a solo recording has exactly one speaker")
            elif f.is_file() and f.suffix.lower() == ".wav":
                dur = wav_seconds(f)
                if dur is None:
                    errors.append(f"{tag} not a readable PCM WAV")
                else:
                    solo_s[spk[0]] = solo_s.get(spk[0], 0.0) + dur
        elif len(spk) < 2:
            errors.append(f"{tag} {kind} needs at least two speakers")
        if kind == "overlap":
            overlap_sizes.add("2" if len(spk) == 2 else "3+")
            a = root / str(r.get("annotation", ""))
            if not r.get("annotation") or not a.is_file():
                errors.append(f"{tag} overlap recording needs an annotation file (who spoke when)")
        c = r.get("conditions") or {}
        for key, allowed, store in (("volume", VOLUMES, "volume"), ("noise", NOISES, "noise"),
                                    ("room", ROOMS, "room")):
            if c.get(key) is not None and c[key] not in allowed:
                errors.append(f"{tag} conditions.{key} must be one of {allowed}")
            elif c.get(key):
                cond_seen[store].add(c[key])
        if c.get("distance_m") is not None:
            if not isinstance(c["distance_m"], (int, float)) or c["distance_m"] <= 0:
                errors.append(f"{tag} conditions.distance_m must be a positive number")
            else:
                cond_seen["distance"].add("near" if c["distance_m"] <= 0.5 else "far")
    if len(speakers) < MIN_SPEAKERS:
        warnings.append(f"only {len(speakers)} speakers; at least {MIN_SPEAKERS} are needed")
    for s, sec in sorted(solo_s.items()):
        if sec < MIN_SOLO_S:
            warnings.append(f"speaker {s}: {sec:.0f} s of solo speech; {MIN_SOLO_S:.0f} s or more is needed")
    for s in speakers - set(solo_s):
        warnings.append(f"speaker {s}: no solo recording (needed for enrollment and ground truth)")
    for need, have, label in ((set(VOLUMES), cond_seen["volume"], "volumes"),
                              ({"near", "far"}, cond_seen["distance"], "distances (near and far)"),
                              ({"quiet", "street"}, cond_seen["noise"], "noise (quiet and noisy)"),
                              ({"small", "large"}, cond_seen["room"], "rooms")):
        if not need <= have:
            warnings.append(f"missing coverage of {label}: have {sorted(have) or 'none'}")
    if not {"2", "3+"} <= overlap_sizes:
        warnings.append(f"overlap recordings needed for 2 people and 3+ people; have {sorted(overlap_sizes) or 'none'}")
    if kinds["leaves_frame"] == 0:
        warnings.append("no 'leaves_frame' clips (target leaves the camera view)")
    return {"errors": errors, "warnings": warnings,
            "coverage": {"speakers": sorted(speakers), "solo_seconds": {k: round(v, 1) for k, v in solo_s.items()},
                         "kinds": kinds, "conditions": {k: sorted(v) for k, v in cond_seen.items()}}}
