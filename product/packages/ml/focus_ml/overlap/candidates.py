"""The six extraction candidates behind the one interface (see ``base``).

Call shapes follow each project's public inference code (links in
``docs/OVERLAP_EXTRACTION.md``). The three target-conditioned candidates (WeSep,
USEF-TSE, SpEx+) have been run on real weights on CPU (see ``product/experiments/real_tse``);
the three blind separators have not. Any candidate that cannot run is reported as
blocked, with the concrete error as evidence.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ..clearervoice_backend import SS_MODEL, ClearerVoiceBackend, require_weights as cv_require_weights
from ..errors import ModelUnavailableError
from ..isolation_engines import read_wav, write_wav
from ..voice.types import SAMPLE_RATE
from . import weights as W
from .base import (BLIND_THEN_SELECT, TARGET_CONDITIONED, BlindSelectExtractor, BlockedError,
                   CandidateInfo, OverlapExtractor, resample, trim_enrollment)


def _import(name: str, hint: str):
    W.activate_overlap_site()
    try:
        return __import__(name, fromlist=["_"])
    except ImportError as exc:
        raise BlockedError(f"the package {name} needed for {hint} is not installed; " + W.SETUP_HINT,
                           "missing_package", f"{type(exc).__name__}: {exc}") from exc


def _load_module(path: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        raise BlockedError("a model source file could not be imported", "broken_code",
                           f"{path.name}: {type(exc).__name__}: {exc}") from exc
    return mod


# The USEF checkpoint is a pickle (it contains numpy objects), so loading it needs weights_only=False, which can
# run code. It is therefore loaded only when its SHA-256 equals the one reviewed here (the file fetched from
# ZBang/USEF-TSE revision 6e2bd14dd3a2d4fcb6abd246cce5f91538c08dbf).
USEF_CHECKPOINT_SHA256 = "a0515c8c90eee2b2b39cc02eca8f3cc4f2749660131e60fbee3224e97cb193b9"


def verify_sha256(path: Path, expected: str) -> None:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    if h.hexdigest() != expected:
        raise BlockedError(f"{path.name} is not the reviewed checkpoint, so it is not loaded (unsafe pickle); "
                           + W.SETUP_HINT, "broken_code", f"sha256 {h.hexdigest()} != expected {expected}")


def _strip_state(obj, prefix: str = "") -> dict:
    """A checkpoint's weights, whichever key the trainer used, without 'module.'
    (and without ``prefix``, e.g. SpEx+'s ``sep_network.`` wrapper)."""
    for key in ("model_state_dict", "model", "state_dict"):
        if isinstance(obj, dict) and key in obj and isinstance(obj[key], dict):
            obj = obj[key]
            break
    out = {k.replace("module.", "", 1): v for k, v in obj.items()}
    if prefix:
        out = {(k[len(prefix):] if k.startswith(prefix) else k): v for k, v in out.items()}
    return out


def _namespace(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _namespace(v) for k, v in d.items()})
    return d


def match_to_mixture(est, mixture) -> np.ndarray:
    """Give ``est`` the polarity and level it has inside ``mixture``: scale by <est, mix> / <est, est>
    (the least-squares share of the mixture that is est). The three real checkpoints are trained with
    scale-invariant (SI-SDR) losses, so their output level and even polarity are arbitrary: SpEx+ peaks
    at ~1e5 on a +-0.6 mixture, USEF-TSE came out inverted and 3x too loud. Without this the hybrid
    would cross-fade a polarity-flipped signal into the target's own audio. Uses only the mixture, never
    a reference; the same step is applied to all three candidates."""
    est = np.asarray(est, dtype=np.float32)
    denom = float(np.dot(est.astype(np.float64), est.astype(np.float64)))
    if denom < 1e-12:
        return est
    return (est * (float(np.dot(est.astype(np.float64), np.asarray(mixture, np.float64))) / denom)).astype(np.float32)


class _Stateful:
    home: Path | None = None
    _model = None

    def _unload(self):
        self._model = None


def _shim_optional_frontends() -> None:
    """wespeaker's frontend package imports the s3prl, whisper and w2v-bert (transformers) frontends
    eagerly, but only those frontends (not used by the BSRNN extractor) need them,
    and they do not import under the newer torch/torchaudio or Python 3.12. When a
    real package cannot be imported, a stub that raises on use takes its place;
    the BSRNN path never touches it."""
    import types
    W.activate_overlap_site()
    try:
        import setuptools  # noqa: F401  -- gives Python 3.12 the distutils s3prl wants
    except ImportError:
        pass

    def _unavailable(*_a, **_k):
        raise RuntimeError("this wespeaker frontend is not available in this environment")

    def _getattr(name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _unavailable
    for top, subs in (("s3prl", ("s3prl.nn",)), ("whisper", ()), ("transformers", ()), ("peft", ())):
        try:
            for m in (top, *subs):
                importlib.import_module(m)
            continue
        except Exception:
            for k in [k for k in sys.modules if k == top or k.startswith(top + ".")]:
                del sys.modules[k]
        pkg = types.ModuleType(top)
        pkg.__getattr__ = _getattr          # any public attribute raises on use
        sys.modules[top] = pkg
        for m in subs:
            sub = types.ModuleType(m)
            sub.__getattr__ = _getattr
            sys.modules[m] = sub
            setattr(pkg, m.split(".")[-1], sub)


# ---------------------------------------------------------------- 1. WeSep
class WesepBsrnn(_Stateful, OverlapExtractor):
    info = CandidateInfo(
        name="wesep_bsrnn", title="REAL-TSE WeSep BSRNN (spk_emb_100, 16 kHz)",
        mechanism=TARGET_CONDITIONED, code_licence="Apache-2.0 (as stated for the project; no LICENSE file "
        "was found at the repository root when checked)", weights_licence="no explicit licence",
        model_rate=16000, version="wenet-e2e/wesep fork REAL-TSE/wesep-real-tse @ 2a54097",
        notes="Conditioned on a WeSpeaker speaker embedding computed from the enrollment audio. "
              "Checkpoints are distributed on Google Drive (not Hugging Face).",
        fp16_note="The library call is file based; fp16 autocast is tried and falls back to fp32 on NaN.",
        vram_base_mib=500.0, vram_per_window_s_mib=70.0)

    def __init__(self, device="cpu", fp16=True, home=None):
        super().__init__(device, fp16)
        self.home = home

    def check_ready(self):
        W.require_candidate_files(self.info.name, self.info.title, self.home)

    def _load(self):
        code = str(W.code_dir(self.info.name, self.home))
        if code not in sys.path:
            sys.path.append(code)
        W.activate_overlap_site()
        try:                  # wespeaker's s3prl frontend imports distutils (removed in Python 3.12);
            import setuptools  # noqa: F401  -- importing setuptools first provides it
        except ImportError:
            pass
        _shim_optional_frontends()
        wesep = _import("wesep", self.info.title)
        m = wesep.load_model_local(str(W.weights_dir(self.info.name, self.home)))
        m.set_resample_rate(SAMPLE_RATE)
        m.set_vad(False)
        m.set_device(self.device)
        m.set_output_norm(False)      # keep the model's own level (no peak normalisation)
        self._model = m

    def _extract_batch(self, windows, voiceprint, enrollment):
        # The in-memory entry point: the file one needs torchaudio.load, which newer
        # torchaudio only provides with TorchCodec (not installed). Same pre/post-processing.
        import torch
        enroll = torch.from_numpy(trim_enrollment(enrollment)).reshape(1, -1)
        outs = []
        for w in windows:
            mix = torch.from_numpy(w).reshape(1, -1)
            speech = self._guarded(lambda: self._model.extract_speech_from_pcm(mix, SAMPLE_RATE, enroll, SAMPLE_RATE))
            if speech is None:
                raise BlockedError("the model returned no audio", "broken_code", "extract_speech_from_pcm -> None")
            outs.append(match_to_mixture(speech[0].float().cpu().numpy().reshape(-1), w))
        return outs


# ---------------------------------------------------------------- 2. USEF-TSE
class UsefTse(_Stateful, OverlapExtractor):
    info = CandidateInfo(
        name="usef_tse", title="USEF-TSE (USEF-SepFormer, WSJ0-2mix, 8 kHz)",
        mechanism=TARGET_CONDITIONED, code_licence="CC-BY-NC-4.0 (non-commercial)",
        weights_licence="CC-BY-NC-4.0 (non-commercial)", model_rate=8000,
        version="ZBang/USEF-TSE @ bdaeb36, checkpoint chkpt/USEF-SepFormer/wsj0-2mix",
        notes="Embedding-free: the enrollment audio is encoded by the same encoder and fused by cross "
              "attention. The TFGridNet variant is larger and is not tried (4 GB VRAM).",
        fp16_note="fp16 autocast with fp32 fallback.", vram_base_mib=900.0, vram_per_window_s_mib=120.0)

    def __init__(self, device="cpu", fp16=True, home=None):
        super().__init__(device, fp16)
        self.home = home

    def check_ready(self):
        W.require_candidate_files(self.info.name, self.info.title, self.home)

    def _load(self):
        torch = _import("torch", self.info.title)
        code = str(W.code_dir(self.info.name, self.home))
        if code not in sys.path:
            sys.path.insert(0, code)         # the config refers to models.model_USEF_SepFormer
        hp = _import("hyperpyyaml", self.info.title)
        wdir = W.weights_dir(self.info.name, self.home)
        verify_sha256(wdir / "temp_best.pth.tar", USEF_CHECKPOINT_SHA256)
        try:
            with open(wdir / "config.yaml", encoding="utf-8") as f:
                cfg = hp.load_hyperpyyaml(f)
            model = cfg["modules"]["masknet"]
            state = torch.load(wdir / "temp_best.pth.tar", map_location="cpu", weights_only=False)   # hash-verified above
            model.load_state_dict(_strip_state(state))
        except Exception as exc:     # hyperpyyaml wraps import errors in its own type
            raise BlockedError("the USEF-TSE model could not be built from its config and code",
                               "broken_code", f"{type(exc).__name__}: {exc}") from exc
        self._model = model.to(self.device).eval()

    def _extract_batch(self, windows, voiceprint, enrollment):
        import torch
        aux = resample(trim_enrollment(enrollment), SAMPLE_RATE, self.info.model_rate)
        outs = []
        by_len: dict[int, list[int]] = {}
        for i, w in enumerate(windows):
            by_len.setdefault(len(w), []).append(i)
        res: dict[int, np.ndarray] = {}
        for idxs in by_len.values():
            mix = np.stack([resample(windows[i], SAMPLE_RATE, self.info.model_rate) for i in idxs])
            m = torch.from_numpy(mix).to(self.device)
            a = torch.from_numpy(aux).unsqueeze(0).repeat(len(idxs), 1).to(self.device)

            def run():
                with torch.inference_mode():
                    return self._model(m, a).float().cpu().numpy().reshape(len(idxs), -1)
            est = self._guarded(run)
            for j, i in enumerate(idxs):
                res[i] = resample(match_to_mixture(est[j], mix[j]), self.info.model_rate, SAMPLE_RATE)
        return [res[i] for i in range(len(windows))]


# ---------------------------------------------------------------- 3. SpEx+
class SpExPlus(_Stateful, OverlapExtractor):
    info = CandidateInfo(
        name="spexplus", title="ClearerVoice SpEx+ (WSJ0-2mix, 8 kHz)",
        mechanism=TARGET_CONDITIONED, code_licence="MIT (SpEx+ reference code, via ClearerVoice-Studio)",
        weights_licence="Apache-2.0 (Hugging Face model card)", model_rate=8000,
        version="modelscope/ClearerVoice-Studio @ 6b3774d, alibabasglab/log_wsj0-2mix_speech_SpEx-plus_2spk",
        notes="Trained on clean English 2-speaker WSJ0-2mix only: weaker on noise, Arabic and 3+ voices "
              "is expected. The audio-only checkpoint lives in the training code, not the clearvoice "
              "inference package, so the model class is imported from the pinned source file.",
        fp16_note="fp16 autocast with fp32 fallback. Output level and polarity are arbitrary "
                  "(scale-invariant training); matched to the mixture by least squares.",
        vram_base_mib=500.0, vram_per_window_s_mib=50.0)

    def __init__(self, device="cpu", fp16=True, home=None):
        super().__init__(device, fp16)
        self.home = home

    def check_ready(self):
        W.require_candidate_files(self.info.name, self.info.title, self.home)

    def _load(self):
        torch = _import("torch", self.info.title)
        yaml = _import("yaml", self.info.title)
        wdir = W.weights_dir(self.info.name, self.home)
        mod = _load_module(W.code_dir(self.info.name, self.home) / "SpEx_plus.py", "focus_spex_plus")
        try:
            cfg = _namespace(yaml.safe_load((wdir / "config.yaml").read_text("utf-8")))
            model = mod.SpEx_plus(cfg)
            model.load_state_dict(_strip_state(torch.load(wdir / "last_best_checkpoint.pt", map_location="cpu"),
                                              "sep_network."))
        except (AttributeError, KeyError, RuntimeError, OSError) as exc:
            raise BlockedError("the SpEx+ model could not be built from its config and checkpoint",
                               "broken_code", f"{type(exc).__name__}: {exc}") from exc
        self._model = model.to(self.device).eval()

    def _extract_batch(self, windows, voiceprint, enrollment):
        import torch
        aux = resample(trim_enrollment(enrollment), SAMPLE_RATE, self.info.model_rate)
        res: dict[int, np.ndarray] = {}
        by_len: dict[int, list[int]] = {}
        for i, w in enumerate(windows):
            by_len.setdefault(len(w), []).append(i)
        for idxs in by_len.values():
            mix = np.stack([resample(windows[i], SAMPLE_RATE, self.info.model_rate) for i in idxs])
            m = torch.from_numpy(mix).to(self.device)
            a = torch.from_numpy(aux).unsqueeze(0).repeat(len(idxs), 1).to(self.device)
            alen = torch.full((len(idxs),), aux.shape[0], dtype=torch.long, device=self.device)

            def run():
                with torch.inference_mode():
                    return self._model(m, a, alen)[0].float().cpu().numpy().reshape(len(idxs), -1)
            est = self._guarded(run)
            for j, i in enumerate(idxs):
                res[i] = resample(match_to_mixture(est[j], mix[j]), self.info.model_rate, SAMPLE_RATE)
        return [res[i] for i in range(len(windows))]


# ------------------------------------------------- 4. MossFormer2 blind + voiceprint
class MossFormer2Voiceprint(_Stateful, BlindSelectExtractor):
    info = CandidateInfo(
        name="mossformer2_ss_voiceprint",
        title="MossFormer2_SS_16K blind separation + voiceprint selection",
        mechanism=BLIND_THEN_SELECT, code_licence="Apache-2.0 (ClearerVoice-Studio)",
        weights_licence="Apache-2.0 (Hugging Face model card)", model_rate=16000,
        version="clearvoice package, alibabasglab/MossFormer2_SS_16K",
        notes="Blind 2-speaker separation. The existing separate-then-select engine is reused; its "
              "lip-sync selection is replaced by voiceprint selection. With 3 voices in a window one "
              "source necessarily contains a mix.",
        fp16_note="ClearVoice's file API does not expose precision; runs as the library decides.",
        vram_base_mib=1200.0, vram_per_window_s_mib=150.0)

    def __init__(self, embedder, device="cpu", fp16=True, clearervoice_dir=None, backend=None):
        super().__init__(embedder, device, fp16)
        self.clearervoice_dir = clearervoice_dir
        self.backend = backend or ClearerVoiceBackend(clearervoice_dir, device)

    def check_ready(self):
        try:
            cv_require_weights(self.clearervoice_dir or self.backend.base_dir, (SS_MODEL,))
        except ModelUnavailableError as exc:
            raise BlockedError(exc.message, "missing_weights", exc.detail) from exc

    def _unload(self):
        self.backend._models.clear()

    def _separate_batch(self, windows):
        out = []
        with tempfile.TemporaryDirectory(prefix="focus-mf2-") as tmp:
            for i, w in enumerate(windows):
                wav = os.path.join(tmp, f"w{i}.wav")
                write_wav(wav, w, SAMPLE_RATE)
                try:
                    paths = self.backend.separate(wav, os.path.join(tmp, f"o{i}"))
                except ModelUnavailableError as exc:
                    raise BlockedError(exc.message, "missing_package", exc.detail) from exc
                srcs = []
                for p in paths:
                    s, sr = read_wav(p)
                    srcs.append(resample(s, sr, SAMPLE_RATE))
                out.append(srcs)
        return out


# ---------------------------------------------------- 5. SepFormer libri3mix (3+)
class SepformerLibri3Mix(_Stateful, BlindSelectExtractor):
    info = CandidateInfo(
        name="sepformer_libri3mix", title="SepFormer libri3mix (8 kHz, 3 sources) + voiceprint selection",
        mechanism=BLIND_THEN_SELECT, code_licence="Apache-2.0 (SpeechBrain)",
        weights_licence="Apache-2.0 (Hugging Face model card)", model_rate=8000,
        categories=("overlap_3plus",), version="speechbrain/sepformer-libri3mix",
        notes="Blind 3-speaker separation trained on English LibriMix at 8 kHz; always returns three "
              "outputs, so with only two voices one output is an artefact.",
        fp16_note="fp16 autocast with fp32 fallback.", vram_base_mib=800.0, vram_per_window_s_mib=420.0)

    def __init__(self, embedder, device="cpu", fp16=True, home=None):
        super().__init__(embedder, device, fp16)
        self.home = home

    def check_ready(self):
        W.require_candidate_files(self.info.name, self.info.title, self.home)

    def _load(self):
        sep = _import("speechbrain.inference.separation", self.info.title)
        src = W.weights_dir(self.info.name, self.home)
        try:
            self._model = sep.SepformerSeparation.from_hparams(
                source=str(src), savedir=str(src / ".sb_run"), run_opts={"device": self.device})
        except Exception as exc:
            raise BlockedError("the SepFormer model could not be loaded", "broken_code",
                               f"{type(exc).__name__}: {exc}") from exc

    def _separate_batch(self, windows):
        import torch
        res: dict[int, list] = {}
        by_len: dict[int, list[int]] = {}
        for i, w in enumerate(windows):
            by_len.setdefault(len(w), []).append(i)
        for idxs in by_len.values():
            mix = np.stack([resample(windows[i], SAMPLE_RATE, self.info.model_rate) for i in idxs])
            m = torch.from_numpy(mix).to(self.device)

            def run():
                with torch.inference_mode():
                    return self._model.separate_batch(m).float().cpu().numpy()   # (B, T, n_src)
            est = self._guarded(run)
            for j, i in enumerate(idxs):
                res[i] = [resample(est[j, :, k], self.info.model_rate, SAMPLE_RATE)
                          for k in range(est.shape[-1])]
        return [res[i] for i in range(len(windows))]


# ---------------------------------------------------- 6. pyannote PixIT (3+)
class PyannoteAmiSeparation(_Stateful, BlindSelectExtractor):
    info = CandidateInfo(
        name="pyannote_ami_pixit", title="pyannote speech-separation-ami-1.0 (PixIT) + voiceprint selection",
        mechanism=BLIND_THEN_SELECT, code_licence="MIT (pyannote.audio)",
        weights_licence="MIT (Hugging Face model card; gated, accept the terms first)", model_rate=16000,
        categories=("overlap_3plus",), version="pyannote/speech-separation-ami-1.0",
        notes="Joint diarization and separation trained on AMI meeting speech (English, far-field). "
              "One source per detected speaker; windows with fewer detected speakers give fewer sources.",
        fp16_note="fp16 autocast with fp32 fallback.", vram_base_mib=1500.0, vram_per_window_s_mib=200.0)

    def __init__(self, embedder, device="cpu", fp16=True, home=None):
        super().__init__(embedder, device, fp16)
        self.home = home

    def check_ready(self):
        W.require_candidate_files(self.info.name, self.info.title, self.home)
        if not (W.weights_dir(self.info.name, self.home) / "hf_cache").is_dir():
            raise BlockedError(self.info.title + ": the model cache is not installed; " + W.SETUP_HINT,
                               "missing_weights", f"missing: weights/{self.info.name}/hf_cache")

    def _load(self):
        torch = _import("torch", self.info.title)
        pa = _import("pyannote.audio", self.info.title)
        base = W.weights_dir(self.info.name, self.home)
        for k, v in (("HF_HUB_CACHE", str(base / "hf_cache")), ("HF_HUB_OFFLINE", "1")):
            os.environ[k] = v
        try:
            pipe = pa.Pipeline.from_pretrained("pyannote/speech-separation-ami-1.0")
        except Exception as exc:
            raise BlockedError("the pyannote separation pipeline could not be loaded", "broken_code",
                               f"{type(exc).__name__}: {exc}") from exc
        if pipe is None:
            raise BlockedError("the pyannote separation pipeline could not be loaded", "missing_weights",
                               "Pipeline.from_pretrained returned None (terms not accepted?)")
        self._model = pipe.to(torch.device(self.device))

    def _separate_batch(self, windows):
        import torch
        out = []
        for w in windows:       # the pipeline is one-file-at-a-time
            wav = torch.from_numpy(w).reshape(1, -1)

            def run():
                with torch.inference_mode():
                    return self._model({"waveform": wav, "sample_rate": SAMPLE_RATE})
            _, sources = self._guarded(run)
            data = np.asarray(getattr(sources, "data", sources), dtype=np.float32)   # (T, n_speakers)
            out.append([data[:, k] for k in range(data.shape[1])] or [np.zeros_like(w)])
        return out


# ------------------------------------------------------------------ registry
ORDER = ("wesep_bsrnn", "usef_tse", "spexplus", "mossformer2_ss_voiceprint",
         "sepformer_libri3mix", "pyannote_ami_pixit")
INFO = {c.info.name: c.info for c in (WesepBsrnn, UsefTse, SpExPlus, MossFormer2Voiceprint,
                                      SepformerLibri3Mix, PyannoteAmiSeparation)}
_BLIND = {"mossformer2_ss_voiceprint": MossFormer2Voiceprint, "sepformer_libri3mix": SepformerLibri3Mix,
          "pyannote_ami_pixit": PyannoteAmiSeparation}
_COND = {"wesep_bsrnn": WesepBsrnn, "usef_tse": UsefTse, "spexplus": SpExPlus}


def build_candidate(name: str, *, device: str = "cpu", fp16: bool = True, embedder=None,
                    home=None, clearervoice_dir=None) -> OverlapExtractor:
    if name in _COND:
        return _COND[name](device=device, fp16=fp16, home=home)
    if name == "mossformer2_ss_voiceprint":
        return MossFormer2Voiceprint(embedder, device, fp16, clearervoice_dir)
    if name in _BLIND:
        return _BLIND[name](embedder, device, fp16, home)
    raise ValueError(f"unknown candidate {name!r}; choose one of {ORDER}")


def candidate_status(home=None, clearervoice_dir=None) -> dict[str, dict]:
    """Read-only: is each candidate's weights/code present? Never loads a model."""
    out = {}
    for name in ORDER:
        probe = build_candidate(name, home=home, clearervoice_dir=clearervoice_dir,
                                embedder=SimpleNamespace(name="probe"))
        try:
            probe.check_ready()
            out[name] = {"ready": True, "blocker": None}
        except BlockedError as exc:
            out[name] = {"ready": False, "blocker": exc.as_record()}
    return out
