from __future__ import annotations

from pathlib import Path

import pytest

from cert_parser.config import Settings, get_settings


def test_belgiss_ssl_verify_env_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGISS_SSL_VERIFY", "false")
    get_settings.cache_clear()
    settings = Settings()
    assert settings.http_ssl_verify is False
    get_settings.cache_clear()


def test_http_ssl_verify_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_SSL_VERIFY", "false")
    monkeypatch.delenv("BELGISS_SSL_VERIFY", raising=False)
    get_settings.cache_clear()
    settings = Settings()
    assert settings.http_ssl_verify is False
    get_settings.cache_clear()


def test_lookup_eaeu_first_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOKUP_EAEU_FIRST", "false")
    get_settings.cache_clear()
    settings = Settings()
    assert settings.lookup_eaeu_first is False
    get_settings.cache_clear()


def test_production_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="AUTH_ENABLED"):
        Settings()
    get_settings.cache_clear()


def test_production_blocks_insecure_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("AUTH_USERS", '[{"username":"a","password_hash":"$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW","role":"admin"}]')
    monkeypatch.setenv("HTTP_SSL_VERIFY", "false")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="HTTP_SSL_VERIFY"):
        Settings()
    get_settings.cache_clear()


def test_auth_secret_key_min_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", "too-short")
    monkeypatch.setenv("AUTH_USERS", '[{"username":"a","password_hash":"$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW","role":"admin"}]')
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="AUTH_SECRET_KEY"):
        Settings()
    get_settings.cache_clear()


def test_auth_users_file_instead_of_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    users_file = tmp_path / "auth_users.json"
    users_file.write_text(
        '[{"username":"a","password_hash":"$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW","role":"admin"}]',
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", "x" * 32)
    monkeypatch.delenv("AUTH_USERS", raising=False)
    monkeypatch.setenv("AUTH_USERS_FILE", str(users_file))
    get_settings.cache_clear()
    settings = Settings()
    assert settings.auth_users_file == users_file
    get_settings.cache_clear()


def test_allowed_host_list_includes_internal_healthcheck_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    get_settings.cache_clear()
    settings = Settings()
    assert "example.com" in settings.allowed_host_list
    assert "localhost" in settings.allowed_host_list
    assert "127.0.0.1" in settings.allowed_host_list
    assert "web" in settings.allowed_host_list
    get_settings.cache_clear()


def test_health_live_allows_localhost_with_restricted_allowed_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from cert_parser.api.app import create_app

    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", "x" * 32)
    monkeypatch.setenv(
        "AUTH_USERS",
        '[{"username":"a","password_hash":"$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW","role":"admin"}]',
    )
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("PDF_OCR_ENABLED", "false")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers={"Host": "localhost:8000"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    get_settings.cache_clear()
