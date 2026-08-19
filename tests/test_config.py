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
