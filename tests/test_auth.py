from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sert_parser.api.app import create_app
from sert_parser.api.auth import hash_password
from sert_parser.config import get_settings


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


@pytest.fixture
def auth_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("LOOKUP_DELAY_SECONDS", "0")
    monkeypatch.setenv("PDF_OCR_ENABLED", "false")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret-key-for-session-signing")
    monkeypatch.setenv("AUTH_USERS", _auth_users_json())
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "1000/minute")
    monkeypatch.setenv("RATE_LIMIT_LOOKUP", "1000/minute")
    monkeypatch.setenv("RATE_LIMIT_UPLOAD", "1000/minute")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _login(client: TestClient, username: str, password: str, *, next_url: str = "/") -> None:
    page = client.get(f"/login?next={next_url}")
    assert page.status_code == 200
    csrf_token = page.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    response = client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": csrf_token,
            "next": next_url,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_public_endpoints_without_auth(auth_client: TestClient) -> None:
    assert auth_client.get("/health/live").status_code == 200
    assert auth_client.get("/login").status_code == 200
    assert auth_client.get("/static/style.css").status_code == 200


def test_unauthenticated_api_returns_401(auth_client: TestClient) -> None:
    response = auth_client.post("/api/lookup", json={"numbers": ["test"]})
    assert response.status_code == 401


def test_unauthenticated_index_redirects_to_login(auth_client: TestClient) -> None:
    response = auth_client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_login_success(auth_client: TestClient) -> None:
    _login(auth_client, "user", "user-pass")
    response = auth_client.get("/")
    assert response.status_code == 200
    assert "user" in response.text


def test_login_invalid_credentials(auth_client: TestClient) -> None:
    page = auth_client.get("/login")
    csrf_token = page.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    response = auth_client.post(
        "/login",
        data={
            "username": "user",
            "password": "wrong",
            "csrf_token": csrf_token,
            "next": "/",
        },
    )
    assert response.status_code == 401
    assert "Неверный логин или пароль" in response.text


def test_logout(auth_client: TestClient) -> None:
    _login(auth_client, "user", "user-pass")
    response = auth_client.post("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert auth_client.post("/api/cache/clear").status_code == 401


def test_user_cannot_clear_cache(auth_client: TestClient) -> None:
    _login(auth_client, "user", "user-pass")
    response = auth_client.post("/api/cache/clear")
    assert response.status_code == 403


def test_admin_can_clear_cache(auth_client: TestClient) -> None:
    _login(auth_client, "admin", "admin-pass")
    response = auth_client.post("/api/cache/clear")
    assert response.status_code == 200


def test_user_cannot_access_detailed_health(auth_client: TestClient) -> None:
    _login(auth_client, "user", "user-pass")
    response = auth_client.get("/health")
    assert response.status_code == 403


def test_admin_can_access_detailed_health(auth_client: TestClient) -> None:
    _login(auth_client, "admin", "admin-pass")
    response = auth_client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert "status" in payload
    assert "version" in payload


def test_health_live_is_public(auth_client: TestClient) -> None:
    response = auth_client.get("/health/live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "version" in payload


def test_auth_disabled_keeps_public_access(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert client.post("/api/cache/clear").status_code == 200


def test_login_rejects_external_next_url(auth_client: TestClient) -> None:
    _login(auth_client, "user", "user-pass", next_url="https://evil.example/")
    response = auth_client.get("/", follow_redirects=False)
    assert response.status_code == 200
