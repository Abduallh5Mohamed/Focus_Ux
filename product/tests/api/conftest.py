"""Path bootstrap + shared app factory for the API test suite.

Runs with the product-local venv:
  A:/Focus_Ux/product/services/api/.venv/Scripts/python.exe -m pytest \
      A:/Focus_Ux/product/tests/api -q
"""
from __future__ import annotations

import os
import sys
from contextlib import ExitStack
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PRODUCT_ROOT = Path(__file__).resolve().parents[2]
TESTS_API_DIR = Path(__file__).resolve().parent
for candidate in (str(PRODUCT_ROOT), str(TESTS_API_DIR)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from harness import Harness, make_settings  # noqa: E402
from fakes import FakeCandidateProvider, FakeExtractionRunner  # noqa: E402

from services.api.focus_api.routes import create_app  # noqa: E402


@pytest.fixture
def make_api(tmp_path):
    stack = ExitStack()
    counter = {"n": 0}

    def factory(
        *,
        provider=None,
        runner=None,
        transcriber=None,
        settings=None,
        start_dispatcher=False,
    ) -> Harness:
        counter["n"] += 1
        resolved = settings or make_settings(tmp_path / f"api{counter['n']}")
        app = create_app(
            settings=resolved,
            candidate_provider=provider if provider is not None else FakeCandidateProvider(),
            extraction_runner=runner if runner is not None else FakeExtractionRunner(),
            transcriber=transcriber,
            start_dispatcher=start_dispatcher,
        )
        client = stack.enter_context(TestClient(app))
        return Harness(client=client, app=app, settings=resolved)

    yield factory
    stack.close()


@pytest.fixture
def make_settings_for(tmp_path):
    counter = {"n": 0}

    def factory(**overrides):
        counter["n"] += 1
        return make_settings(tmp_path / f"settings{counter['n']}", **overrides)

    return factory
