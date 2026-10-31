"""Opt-in speech separation as the extraction stage (ClearerVoice MossFormer2_SS).

Why this exists
---------------
On a real job the background turned out to be **another human voice**, not
instrumental music: Demucs put 99.4 % of the mix into its ``vocals`` stem, and
on a gap-only clip the ``vocals`` stem was -13.0 dBFS while drums/bass/other sat
at -57..-69 dBFS (``runtime/analysis/demucs_findings.json``). A music separator
is the wrong class of model for that.

MossFormer2_SS_16K separates the mix into two speech sources. Measured on the
same file: the two stems are complementary (``corr(s1+s2, mix) = 0.9716``) and
almost uncorrelated with each other (``0.0493``); the source chosen as the
target is **18.7 dB** below the mix in the non-target regions. This measures
attenuation there, not proof of absent leakage during overlapping speech.

Which stem is the target?
-------------------------
Two selection modes exist.

``enrollment_embedding`` (default when context is supplied by the engine via
``set_context``): every separated stem is embedded on bounded TARGET windows,
or separated overlap windows if the original mixture has no solo target, and compared
to the enrollment voiceprint with the SAME thresholds as
``focus_ml.voice.match`` (no invented calibration). A stem is selected only
when it clears the target threshold AND is separated from the second best
similarity by a margin (default: the gap between the two match thresholds).
Otherwise the extraction refuses - it never falls back to the raw mixture or to
a masked version of it. Windows that are silent, non-finite or shorter than the
embedder minimum are skipped and reported; if nothing usable remains the job
fails explicitly.

When the identity evidence supports the selected stem, its overlap regions are
kept from the separated stem (chunk by chunk, only where the stem itself still
matches the enrollment there); overlap chunks that are too short, silent or
uncertain are muted. This overlap handling is provisional: it is judged per
chunk with the same voiceprint evidence, and its stats are reported in the
identity metadata.

``timing_contrast`` (fallback without context): the stem that is loudest inside
the TARGET regions and quietest outside is the enrolled speaker - the same
criterion, just applied to the separator's output. In the demo on the real
file the winning stem scored +3.43 dB against -2.25 dB for the other one. This
is a timing heuristic, NOT calibrated identity confidence, and full-overlap
regions cannot be recovered with it.

Rules kept
----------
* no torch/clearvoice import in the product environment: a subprocess runs
  ``product/tools/clearervoice_separate.py`` in the ClearerVoice environment;
* nothing is downloaded at run time - a missing checkpoint raises
  ``ModelUnavailableError`` pointing at ``product/tools/clearervoice_setup.py``;
* a separator failure fails the job. It never silently degrades to the mask.
* the model inverts stems in arbitrary order; selection never assumes order,
  and the sources stay unpermuted for the whole file (no streaming is claimed).
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from ..errors import ModelUnavailableError, ProcessingError
from ..isolation_engines import fit_samples, read_wav
from .embedder import embed_segments
from .extractor import DuckedBaseline, target_mask
from .match import MatchConfig, cosine
from .preprocess import slice_samples
from .segments import merge
from .types import SAMPLE_RATE, TARGET, LabelledRegion, Segment, Voiceprint

SETUP_HINT = ("install the ClearerVoice environment and fetch MossFormer2_SS_16K once with "
              "product/tools/clearervoice_setup.py --download")
DEFAULT_MODEL = "MossFormer2_SS_16K"


def project_root() -> Path:
    return Path(__file__).resolve().parents[5]


def cv_home(env=None) -> Path:
    source = os.environ if env is None else env
    return Path(source.get("FOCUS_CLEARERVOICE_HOME") or (project_root() / "model-assets" / "clearervoice"))


def _write_pcm16(path: str, samples, rate: int) -> None:
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


class ClearerVoiceSeparator:
    """Two speech stems for a mono 16 kHz signal, via a subprocess."""

    name = "clearervoice_ss"

    def __init__(self, python: str | None = None, model: str = DEFAULT_MODEL,
                 home: str | None = None, timeout_s: float = 5400.0, env=None):
        source = os.environ if env is None else env
        self.python = python or source.get("FOCUS_CLEARERVOICE_PYTHON") or None
        self.model = model or source.get("FOCUS_CLEARERVOICE_MODEL") or DEFAULT_MODEL
        self.home = Path(home) if home else cv_home(source)
        self.timeout_s = timeout_s
        self.root = project_root()
        self.resident = None
        if source.get('FOCUS_CLEARERVOICE_RESIDENT') == '1':
            from .resident_separation import ResidentSeparation
            self.resident = ResidentSeparation(self.python,
                self.root / 'product/tools/clearervoice_resident.py', self.home,
                self.model, min(timeout_s, 300.0))

    def check_ready(self) -> None:
        if not self.python or not Path(self.python).is_file():
            raise ModelUnavailableError(
                "the speech separator is not installed on this computer; " + SETUP_HINT,
                retryable=False, detail=f"FOCUS_CLEARERVOICE_PYTHON={self.python!r}")
        checkpoint = self.home / "checkpoints" / self.model
        if not checkpoint.is_dir() or not any(checkpoint.rglob("*")):
            raise ModelUnavailableError(
                f"the speech separator weights {self.model} are missing; " + SETUP_HINT,
                retryable=False, detail=f"empty or missing: {checkpoint}")

    def separate(self, samples, rate: int = SAMPLE_RATE):
        """Returns a list of stems (each the input's length)."""
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        self.check_ready()
        script = self.root / "product" / "tools" / "clearervoice_separate.py"
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "mix.wav")
            out_dir = os.path.join(tmp, "stems")
            _write_pcm16(src, x, rate)
            if self.resident is not None:
                stems = self.resident.request(src, out_dir)
                return [fit_samples(*read_wav(path), rate, len(x)) for path in stems]
            command = [self.python, str(script), src, out_dir,
                       "--model", self.model, "--home", str(self.home)]
            try:
                done = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout_s)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ProcessingError("the speech separator could not run",
                                      retryable=True, detail=str(exc)) from exc
            if done.returncode != 0:
                tail = (done.stderr or "").strip()[-600:]
                if done.returncode == 3:
                    raise ModelUnavailableError(
                        "the ClearerVoice environment is not usable; " + SETUP_HINT,
                        retryable=False, detail=tail)
                raise ProcessingError("the speech separator failed", retryable=True, detail=tail)
            try:
                stems = json.loads((done.stdout or "").strip().splitlines()[-1])["stems"]
            except Exception as exc:  # noqa: BLE001
                raise ProcessingError("the speech separator returned no stems",
                                      retryable=True, detail=str(exc)) from exc
            out = []
            for path in stems:
                data, sr = read_wav(path)
                out.append(fit_samples(data, sr, rate, len(x)))
        if len(out) < 2:
            raise ProcessingError("the speech separator returned fewer than two sources",
                                  retryable=True, detail=f"{len(out)} stems")
        return out


class SpeechSeparationBaseline:
    """Extracts the enrolled voice from a two-source separation.

    Without context from the engine (``set_context`` never called) this runs the
    legacy timing-contrast selection, which masks solo TARGET spans only and
    cannot recover overlap. With context, the selected stem's identity is
    checked against the enrollment voiceprint before anything is written, and
    overlap chunks of the confirmed stem are kept only where that stem still
    matches the enrollment there. Both modes are target-only: the other stem is
    never added, and a refusal never degrades to the masked mixture.
    """

    name = "speech_separation"

    def __init__(self, floor_db: float = -12.0, fade_ms: float = 30.0,
                 bridge_ms: float = 250.0, identity_margin: float | None = None,
                 separator=None, output_mode='verified'):
        self.ducked = DuckedBaseline(floor_db=floor_db, fade_ms=fade_ms, bridge_ms=bridge_ms)
        self.separator = separator or ClearerVoiceSeparator()
        if identity_margin is not None and (not math.isfinite(identity_margin) or not 0 <= identity_margin <= 2):
            raise ValueError("identity_margin must be finite and between zero and two")
        self.identity_margin = identity_margin
        if output_mode not in ('verified', 'stem'):
            raise ValueError('output_mode must be verified or stem')
        self.output_mode = output_mode
        self._context = None
        self.last_identity: dict | None = None

    def params(self) -> dict:
        return {"fade_ms": self.ducked.fade_ms, "bridge_ms": self.ducked.bridge_ms,
                "selection": "enrollment_embedding" if self._context else "timing_contrast",
                "other_source_added": False,
                "output_mode": self.output_mode,
                "overlap_policy": "evidence_gated" if self._context else "muted",
                "separator": getattr(self.separator, "name", "custom"),
                "model": getattr(self.separator, "model", None)}

    def check_ready(self) -> None:
        if hasattr(self.separator, "check_ready"):
            self.separator.check_ready()

    def set_context(self, voiceprint: Voiceprint, embedder, match: MatchConfig | None = None) -> None:
        """Extraction hook called by ``AudioOnlyEngine.isolate`` right after the
        match stage: the enrolled voiceprint and the embedder in use. The
        embedder must stay loaded until ``extract`` finishes its final identity
        use, then the engine releases it. ``match`` (threshold policy) defaults
        to the thresholds of ``embedder.name``."""
        self.last_identity = None
        cfg = match or MatchConfig.for_embedder(embedder.name)
        self._context = (voiceprint if isinstance(voiceprint, Voiceprint)
                         else Voiceprint.from_dict(voiceprint), embedder, cfg)

    # -- selection ---------------------------------------------------------
    def clear_context(self):
        self._context = None

    @staticmethod
    def _embedding_score(embedder, samples, windows, voiceprint, cfg):
        try:
            with np.errstate(invalid='raise', divide='raise', over='raise'):
                vec, _ = embed_segments(embedder, samples, windows,
                                       min_s=cfg.min_region_s, max_chunk_s=cfg.max_chunk_s)
            if vec is None:
                return None
            a = np.asarray(vec, dtype=float)
            b = np.asarray(voiceprint.vector, dtype=float)
            if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all() \
                    or np.linalg.norm(a) <= 0 or np.linalg.norm(b) <= 0:
                raise ValueError("non-finite, zero or incompatible voice embedding")
            score = cosine(a, b)
            if not math.isfinite(score):
                raise ValueError("non-finite voice similarity")
            return score
        except (ValueError, RuntimeError, FloatingPointError) as exc:
            raise ProcessingError("speaker identity could not be measured reliably",
                                  retryable=False, detail=type(exc).__name__) from exc

    @staticmethod
    def target_contrast(stem: np.ndarray, regions, rate: int = SAMPLE_RATE) -> float:
        """dB(stem inside the TARGET regions) - dB(stem everywhere else)."""
        inside = np.zeros(len(stem), dtype=bool)
        for r in regions:
            if r.label == TARGET:
                inside[int(round(r.start * rate)):int(round(r.end * rate))] = True
        if not inside.any() or inside.all():
            return 0.0

        def db(v):
            return float(20 * np.log10(np.sqrt(np.mean(np.square(v, dtype=np.float64))) + 1e-12))

        return db(stem[inside]) - db(stem[~inside])

    # -- enrollment-embedding selection ------------------------------------
    def _reliable_windows(self, samples, windows, cfg: MatchConfig, rate: int = SAMPLE_RATE):
        """Windows of the given audio that are long enough, finite and not
        silent - the only ones an embedding can be trusted on."""
        out = []
        for w in windows:
            piece = slice_samples(samples, w, rate)
            if piece.size == 0:
                continue
            if piece.size < int(math.ceil(cfg.min_region_s * rate)):
                continue
            if not np.all(np.isfinite(piece)):
                continue
            rms = float(np.sqrt(np.mean(np.square(piece, dtype=np.float64))))
            if rms <= 0.0:
                continue
            out.append(Segment(w.start, w.end))
        return out

    @staticmethod
    def _chunks(regions, cfg: MatchConfig) -> list[Segment]:
        chunks = []
        for r in regions:
            duration = r.end - r.start
            if duration <= 0:
                continue
            n = max(1, int(np.ceil(duration / cfg.max_chunk_s)))
            step = duration / n
            chunks += [Segment(r.start + i * step, r.start + (i + 1) * step)
                       for i in range(n)]
        return [c for c in chunks if c.duration >= cfg.min_region_s]

    def _identity_choice(self, stems, regions):
        """Returns (best stem index, similarities, the identity metadata dict).
        Raises ProcessingError when the identity evidence does not support any
        single separated source."""
        voiceprint, embedder, cfg = self._context
        target_regions = [r for r in regions if r.label == TARGET]
        evidence_regions = target_regions or regions
        details = {"selection": "enrollment_embedding", "embedder": embedder.name,
                   "similarities": [None] * len(stems), "required_margin": None,
                   "target_index": None, "refusal": None, "warnings": [], "overlap": {}}
        self.last_identity = details
        if voiceprint.embedder != embedder.name:
            details["refusal"] = "embedder_mismatch"
            self.last_identity = details
            raise ProcessingError("the voiceprint was made with a different embedder; "
                                  "enroll again with this embedder",
                                  retryable=False,
                                  detail=f"voiceprint={voiceprint.embedder!r} worker={embedder.name!r}")
        if not evidence_regions:
            self.last_identity = details
            raise ProcessingError(
                "no confirmed target speech was found to compare with the enrolled voice; "
                "provide clean target speech", retryable=False, detail="no TARGET regions")
        windows = self._chunks(evidence_regions, cfg)
        if not windows:
            windows = self._chunks(regions, cfg)
        if len(windows) > 8:
            windows = [windows[int(i)] for i in np.linspace(0, len(windows) - 1, 8)]
        working = [self._reliable_windows(s, windows, cfg) for s in stems]
        details["stem_windows"] = [len(v) for v in working]
        if not any(working):
            details["refusal"] = "no_usable_windows"
            self.last_identity = details
            raise ProcessingError(
                "the separated target speech is too short or too quiet to compare with "
                "the enrolled voice", retryable=False,
                detail=f"windows per stem: {details['stem_windows']}")
        sims = []
        for idx, stem_args in enumerate(working):
            if not stem_args:
                sims.append(None)
                continue
            sims.append(self._embedding_score(embedder, stems[idx], stem_args, voiceprint, cfg))
        details["similarities"] = [None if s is None else round(float(s), 4) for s in sims]
        details["required_margin"] = round((self.identity_margin if self.identity_margin is not None
                                            else cfg.target_threshold - cfg.other_threshold), 4)
        margin = details["required_margin"]
        candidates = sorted((s for s in sims if s is not None), reverse=True)
        if not candidates:
            details["refusal"] = "no_usable_embeddings"
            self.last_identity = details
            raise ProcessingError("no separated source has usable identity evidence", retryable=False)
        best, second = (candidates[0], candidates[1]) if len(candidates) > 1 else (candidates[0], None)
        best_idx = (sims.index(best) if best in sims else -1)
        if best < cfg.other_threshold:
            details["refusal"] = "no_match"
            self.last_identity = details
            raise ProcessingError(
                "none of the separated sources matches the enrolled voice; the separation "
                "could not find this speaker", retryable=False,
                detail=f"similarities: {details['similarities']}")
        if best < cfg.target_threshold:
            details["refusal"] = "uncertain_identity"
            self.last_identity = details
            raise ProcessingError(
                "the separated sources do not clearly match the enrolled voice; more clean "
                "target speech would make the selection reliable", retryable=False,
                detail=f"similarities: {details['similarities']}")
        if second is not None and best - second < margin:
            details["refusal"] = "ambiguous"
            self.last_identity = details
            raise ProcessingError(
                "two separated sources match the enrolled voice equally well; the choice is "
                "ambiguous, so no target was selected", retryable=False,
                detail=f"similarities: {details['similarities']} margin required: {margin}")
        details["target_index"] = best_idx
        if self.output_mode == 'stem':
            details['source_output'] = 'full_selected_stem'
            details['local_identity_verified'] = False
            details['warnings'].append(
                'The separated source matches the enrollment across the clip. '
                'Local identity changes within that source have not been verified.')
            self.last_identity = details
            return best_idx, sims, {}
        overlap = self._overlap_spans(regions, stems[best_idx], voiceprint, cfg, details,
                                      [s for i, s in enumerate(stems) if i != best_idx])
        details["overlap"] = overlap
        self.last_identity = details
        return best_idx, sims, overlap

    def _overlap_spans(self, regions, chosen, voiceprint, cfg, details, competitors) -> dict:
        """Decide overlap handling for the chosen stem: a chunk of the stem is
        kept only when it still matches the enrollment there; uncertain, too
        short or silent chunks are muted. Discard uncertainty - uncertain
        identity is never given to the target."""
        # The mixture diarizer may label a dominant voice OTHER while a quiet
        # enrolled voice is still present underneath it. Verify separated audio
        # there too, instead of relying on the mixture's overlap detector.
        overlap_regions = merge([Segment(r.start, r.end) for r in regions if r.label != TARGET])
        details['verification_scope'] = 'all_non_target_speech'
        stats = {"kept": [], "kept_s": 0.0, "muted_s": 0.0, "unmeasured_s": 0.0}
        if not overlap_regions:
            return stats
        rate = SAMPLE_RATE
        voiceprint, embedder, _ = self._context
        for r in overlap_regions:
            duration = r.end - r.start
            if duration <= 0:
                continue
            n = max(1, int(np.ceil(duration / cfg.max_chunk_s)))
            step = duration / n
            for i in range(n):
                seg = Segment(r.start + i * step, r.start + (i + 1) * step)
                piece = slice_samples(chosen, seg, rate)
                if piece.size < int(math.ceil(cfg.min_region_s * rate)):
                    stats["unmeasured_s"] += seg.duration
                    details["warnings"].append(
                        f"overlap between {seg.start:.2f} s and {seg.end:.2f} s is shorter than "
                        f"{cfg.min_region_s:g} s and was muted because identity could not be measured")
                    continue
                if not np.all(np.isfinite(piece)) or \
                        float(np.sqrt(np.mean(np.square(piece, dtype=np.float64)))) <= 0.0:
                    stats["unmeasured_s"] += seg.duration
                    details["warnings"].append(
                        f"overlap between {seg.start:.2f} s and {seg.end:.2f} s is silent in the "
                        "selected source and was muted")
                    continue
                score = self._embedding_score(embedder, chosen, [seg], voiceprint, cfg)
                rival_scores = [self._embedding_score(embedder, s, [seg], voiceprint, cfg)
                                for s in competitors if self._reliable_windows(s, [seg], cfg)]
                margin = self.identity_margin if self.identity_margin is not None else cfg.target_threshold - cfg.other_threshold
                rivals = [v for v in rival_scores if v is not None]
                if score is not None and score >= cfg.target_threshold \
                        and all(score - rival >= margin for rival in rivals):
                    stats["kept"].append((float(seg.start), float(seg.end)))
                    stats["kept_s"] += seg.duration
                else:
                    stats["muted_s"] += seg.duration
                    details["warnings"].append(
                        f"overlap between {seg.start:.2f} s and {seg.end:.2f} s does not clearly "
                        "match the enrolled voice and was muted")
        return stats

    # -- extraction ---------------------------------------------------------
    def extract(self, samples, regions):
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        stems = self.separator.separate(x)
        if len(stems) < 2:
            raise ProcessingError("the speech separator returned fewer than two sources",
                                  retryable=False, detail=f"{len(stems)} stems")
        if these := [i for i, s in enumerate(stems) if len(s) != len(x)]:
            raise ProcessingError(
                "the speech separator returned sources of the wrong length", retryable=False,
                detail=f"stem indices with unexpected length: {these}")
        if self._context is None:
            return self._extract_timing(x, stems, regions)
        best, sims, overlap = self._identity_choice(stems, regions)
        chosen = stems[best]
        if self.output_mode == 'stem':
            return fit_samples(chosen, SAMPLE_RATE, SAMPLE_RATE, len(x))
        gate_regions = [r for r in regions if r.label == TARGET]
        for start, end in overlap.get("kept", []):
            gate_regions.append(LabelledRegion(start, end, TARGET, None, None, "overlap_kept"))
        gate = target_mask(len(x), gate_regions, fade_ms=self.ducked.fade_ms, floor=0.0,
                           bridge_ms=0.0)
        # Preserve only the selected source. Reintroducing another speaker in
        # pauses contradicts target-only isolation; optional ambience belongs
        # in the explicit result mixer, not in the supposedly isolated WAV.
        out = gate * chosen
        if not np.any(out):
            self.last_identity['refusal'] = 'no_verified_output'
            raise ProcessingError('No output interval could be verified; refusing a silent successful result',
                                  retryable=False)
        return fit_samples(out, SAMPLE_RATE, SAMPLE_RATE, len(x))

    def _extract_timing(self, x, stems, regions):
        scores = [self.target_contrast(s, regions) for s in stems]
        self.last_identity = {"selection": "timing_contrast", "scores": [round(float(s), 4)
                          for s in scores], "refusal": None, "target_index": None}
        if not any(r.label == TARGET for r in regions) or max(scores) - min(scores) < 1.0:
            self.last_identity["refusal"] = ("no_target" if
                                             not any(r.label == TARGET for r in regions) else "timing_ambiguous")
            raise ProcessingError(
                "the separated sources cannot be assigned to the target confidently; provide clean target speech",
                retryable=False, detail=f"timing contrast scores: {scores}")
        best = int(np.argmax(scores))
        self.last_identity["target_index"] = best
        chosen = stems[best]
        gate = target_mask(len(x), regions, fade_ms=self.ducked.fade_ms, floor=0.0,
                           bridge_ms=self.ducked.bridge_ms)
        # Preserve only the selected source. Reintroducing another speaker in
        # pauses contradicts target-only isolation; optional ambience belongs
        # in the explicit result mixer, not in the supposedly isolated WAV.
        out = gate * chosen
        return fit_samples(out, SAMPLE_RATE, SAMPLE_RATE, len(x))


def build_separation_extractor(env=None):
    """Factory used by ``extractor.build_extractor`` for ``separation``."""
    source = os.environ if env is None else env
    from .extractor import _env_float, DEFAULT_BRIDGE_MS, DEFAULT_FADE_MS, DEFAULT_FLOOR_DB

    return SpeechSeparationBaseline(
        floor_db=_env_float(source, "FOCUS_VOICE_FLOOR_DB", DEFAULT_FLOOR_DB),
        fade_ms=_env_float(source, "FOCUS_VOICE_FADE_MS", DEFAULT_FADE_MS),
        bridge_ms=_env_float(source, "FOCUS_VOICE_BRIDGE_MS", DEFAULT_BRIDGE_MS),
        separator=ClearerVoiceSeparator(env=source),
        output_mode=source.get('FOCUS_SEPARATION_OUTPUT', 'verified'),
    )
