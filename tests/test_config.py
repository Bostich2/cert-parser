from __future__ import annotations

import pytest

from sert_parser.config import Settings, get_settings


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
