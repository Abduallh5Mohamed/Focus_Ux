"""Arabic text normalisation and edit-distance error rates (CER / WER)."""
from __future__ import annotations

import re
from typing import Sequence

_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"
)


def normalize_arabic(text: str) -> str:
    """Normalise spelling variants that are not recognition errors.

    Removes diacritics, tatweel and punctuation; maps alef variants to ا,
    ى to ي, ة to ه and Arabic-Indic digits to ASCII; collapses whitespace.
    Underscore is treated as punctuation.
    """
    t = text.translate(_DIGITS)
    t = _DIACRITICS.sub("", t)
    t = t.replace("\u0640", "")
    t = re.sub("[إأآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه")
    t = t.replace("_", " ")
    t = _PUNCT.sub(" ", t)
    return _SPACES.sub(" ", t).strip()


def edit_distance(ref: Sequence, hyp: Sequence) -> int:
    """Levenshtein distance (substitution, insertion, deletion all cost 1)."""
    if not ref:
        return len(hyp)
    if not hyp:
        return len(ref)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def _units(text: str, level: str) -> list[str]:
    norm = normalize_arabic(text)
    if level == "word":
        return norm.split()
    # Character level ignores spaces: dialect text has unstable word boundaries,
    # and word-boundary errors are already counted by WER.
    return list(norm.replace(" ", ""))


def error_counts(ref: str, hyp: str, level: str) -> tuple[int, int]:
    """Return (edit errors, reference length) after normalisation."""
    if level not in ("char", "word"):
        raise ValueError("level must be 'char' or 'word'")
    r, h = _units(ref, level), _units(hyp, level)
    if not r:
        raise ValueError("reference transcript is empty after normalisation")
    return edit_distance(r, h), len(r)


def cer(ref: str, hyp: str) -> float:
    errors, n = error_counts(ref, hyp, "char")
    return errors / n


def wer(ref: str, hyp: str) -> float:
    errors, n = error_counts(ref, hyp, "word")
    return errors / n
