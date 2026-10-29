"""FOCUS local API (Round 2).

FastAPI + SQLite service that owns sessions, uploads, face candidates, jobs,
protected media and the single dispatcher. It never imports torch and never
loads a model inside a request: GPU work is injected via the provider/runner
protocols in :mod:`services.api.focus_api.interfaces`.
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
