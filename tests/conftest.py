from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sert_parser.api.app import create_app
from sert_parser.api.auth import hash_password
from sert_parser.config import get_settings

# Stable semver for tests and local runs without git tags.
os.environ.setdefault("SERT_PARSER_VERSION", "0.2.0")


def _auth_users_json() -> str:
    return json.dumps(
        [
            {
                "username": "admin",
                "password_hash": hash_password("admin-pass"),
                "role": "admin",
            },
            {
                "username": "user",
                "password_hash": hash_password("user-pass"),
                "role": "user",
            },
        ]
    )


def _configure_auth_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("LOOKUP_DELAY_SECONDS", "0")
    monkeypatch.setenv("PDF_OCR_ENABLED", "false")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret-key-for-session-signing-32chars")
    monkeypatch.setenv("AUTH_USERS", _auth_users_json())
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "1000/minute")
    monkeypatch.setenv("RATE_LIMIT_LOOKUP", "1000/minute")
    monkeypatch.setenv("RATE_LIMIT_UPLOAD", "1000/minute")


def _login(client: TestClient, username: str, password: str) -> None:
    page = client.get("/login")
    assert page.status_code == 200
    csrf_token = page.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    response = client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": csrf_token,
            "next": "/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


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


@pytest.fixture
def admin_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _configure_auth_env(monkeypatch, tmp_path)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        _login(test_client, "admin", "admin-pass")
        yield test_client
    get_settings.cache_clear()
