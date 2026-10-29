"""Uvicorn entry point.

Start from the product root so ``services.worker`` is importable::

    A:/Focus_Ux/product/services/api/.venv/Scripts/python.exe -m uvicorn \
        services.api.focus_api.main:app --host 127.0.0.1 --port 8000

The app factory reads ``FOCUS_API_*`` environment variables; defaults are
127.0.0.1:8000 and A:/Focus_Ux/runtime/round2/api.
"""
from __future__ import annotations

from .routes import create_app

app = create_app()


if __name__ == "__main__":  # pragma: no cover - convenience only
    import uvicorn

    from .config import Settings

    cfg = Settings.from_env()
    uvicorn.run("services.api.focus_api.main:app", host=cfg.api_host, port=cfg.api_port)
