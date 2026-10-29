"""API service package (FastAPI + SQLite) for FOCUS.

Import ``services.api.focus_api`` for the implementation. The package is kept
under ``product/`` so it can import the worker's plain data contracts
(``services.worker``) without pulling in torch.
"""
