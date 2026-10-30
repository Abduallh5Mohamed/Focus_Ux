"""Overlap-region extraction: one interface, six candidates, a hybrid scheduler.

Import-light: numpy only until a model is actually loaded.
"""
from .base import (BLIND_THEN_SELECT, TARGET_CONDITIONED, BlockedError, CandidateInfo,
                   OverlapExtractor, select_by_voiceprint)
from .hybrid import HybridConfig, HybridExtractor

__all__ = ["BLIND_THEN_SELECT", "TARGET_CONDITIONED", "BlockedError", "CandidateInfo",
           "OverlapExtractor", "select_by_voiceprint", "HybridConfig", "HybridExtractor"]
