"""Test-set manifest: loading and validation.

Layout (all paths relative to the dataset directory)::

    manifest.json
    clips/<clip_id>/video.mp4        optional, for humans and the pipeline
    clips/<clip_id>/mix.wav          mixture fed to the model
    clips/<clip_id>/<speaker>_ref.wav
    clips/<clip_id>/<speaker>.txt    hand-written reference transcript
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import SCHEMA_VERSION

KNOWN_TAGS = ("head_motion", "face_disappears", "similar_voices", "overlap", "baseline",
              # limitation scenarios (real recordings), reported in their own section
              "whisper", "shout", "noise", "reverb", "no_solo_enrollment")
VERIFIED = "human_verified"
PROVISIONAL = "provisional_asr"
TRANSCRIPT_STATUSES = (VERIFIED, PROVISIONAL)
STATUS_READY = "ready"
STATUS_TEMPLATE = "template"


class DatasetError(ValueError):
    pass


@dataclass
class Speaker:
    id: str
    ref_audio: str
    transcript: str | None
    transcript_status: str


@dataclass
class Clip:
    id: str
    status: str
    mix_audio: str
    video: str | None
    source: dict
    tags: list[str]
    speakers: list[Speaker]
    targets: list[str]

    def speaker(self, speaker_id: str) -> Speaker:
        for s in self.speakers:
            if s.id == speaker_id:
                return s
        raise KeyError(speaker_id)


@dataclass
class Dataset:
    root: Path
    dataset_id: str
    clips: list[Clip] = field(default_factory=list)

    def path(self, rel: str) -> Path:
        return self.root / rel

    def fingerprint(self) -> str:
        """Content hash of the manifest plus every file a READY clip references
        (mix, references, transcripts). Two reports are comparable only when
        this matches, so replacing clips or fixing a transcript changes it."""
        h = hashlib.sha256()
        h.update((self.root / "manifest.json").read_bytes())
        for clip in self.clips:
            if clip.status != STATUS_READY:
                continue
            rels = [clip.mix_audio] + [s.ref_audio for s in clip.speakers]
            rels += [s.transcript for s in clip.speakers if s.transcript]
            for rel in sorted(rels):
                f = self.path(rel)
                h.update(rel.encode("utf-8"))
                h.update(f.read_bytes() if f.is_file() else b"<missing>")
        return h.hexdigest()


def load_dataset(root: str | Path) -> Dataset:
    root = Path(root)
    manifest = root / "manifest.json"
    if not manifest.is_file():
        raise DatasetError(f"{manifest} not found")
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetError(f"{manifest}: invalid JSON ({exc})") from exc
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise DatasetError(f"unsupported manifest schema_version {raw.get('schema_version')!r}")
    ds = Dataset(root=root, dataset_id=str(raw.get("dataset_id") or root.name))
    seen: set[str] = set()
    for c in raw.get("clips", []):
        cid = str(c.get("id", ""))
        if not cid or cid in seen:
            raise DatasetError(f"clip id missing or duplicated: {cid!r}")
        seen.add(cid)
        speakers = [
            Speaker(
                id=str(s["id"]),
                ref_audio=str(s.get("ref_audio", "")),
                transcript=s.get("transcript"),
                transcript_status=str(s.get("transcript_status", PROVISIONAL)),
            )
            for s in c.get("speakers", [])
        ]
        ds.clips.append(
            Clip(
                id=cid,
                status=str(c.get("status", STATUS_TEMPLATE)),
                mix_audio=str(c.get("mix_audio", "")),
                video=c.get("video"),
                source=dict(c.get("source") or {}),
                tags=list(c.get("tags") or []),
                speakers=speakers,
                targets=[str(t) for t in c.get("targets", [])],
            )
        )
    return ds


def validate_dataset(ds: Dataset) -> list[str]:
    """Return human-readable problems. Template clips only report as incomplete."""
    problems: list[str] = []
    for clip in ds.clips:
        tag = f"[{clip.id}]"
        if clip.status == STATUS_TEMPLATE:
            problems.append(f"{tag} still a template (not scored)")
            continue
        if clip.status != STATUS_READY:
            problems.append(f"{tag} unknown status {clip.status!r}")
            continue
        if not clip.speakers:
            problems.append(f"{tag} has no speakers")
        ids = [s.id for s in clip.speakers]
        if len(set(ids)) != len(ids):
            problems.append(f"{tag} duplicate speaker ids")
        if not clip.targets:
            problems.append(f"{tag} has no targets")
        for t in clip.targets:
            if t not in ids:
                problems.append(f"{tag} target {t!r} is not a speaker")
        if len(clip.speakers) < 2:
            problems.append(f"{tag} single speaker: wrong-person check not possible")
        for key in ("url", "license", "description"):
            if not str(clip.source.get(key, "")).strip():
                problems.append(f"{tag} source.{key} is empty")
        for t in clip.tags:
            if t not in KNOWN_TAGS:
                problems.append(f"{tag} unknown tag {t!r}")
        if not clip.mix_audio or not ds.path(clip.mix_audio).is_file():
            problems.append(f"{tag} mix_audio missing: {clip.mix_audio!r}")
        for s in clip.speakers:
            if not s.ref_audio or not ds.path(s.ref_audio).is_file():
                problems.append(f"{tag} speaker {s.id}: ref_audio missing: {s.ref_audio!r}")
            if s.transcript_status not in TRANSCRIPT_STATUSES:
                problems.append(f"{tag} speaker {s.id}: bad transcript_status {s.transcript_status!r}")
            if s.id in clip.targets:
                if not s.transcript or not ds.path(s.transcript).is_file():
                    problems.append(f"{tag} speaker {s.id}: target has no transcript file")
    return problems
