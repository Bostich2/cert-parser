from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sert_parser.api.app import create_app
from sert_parser.config import get_settings

# Stable semver for tests and local runs without git tags.
os.environ.setdefault("SERT_PARSER_VERSION", "0.2.0")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("LOOKUP_DELAY_SECONDS", "0")
    monkeypatch.setenv("PDF_OCR_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "1000/minute")
    monkeypatch.setenv("RATE_LIMIT_LOOKUP", "1000/minute")
    monkeypatch.setenv("RATE_LIMIT_UPLOAD", "1000/minute")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
