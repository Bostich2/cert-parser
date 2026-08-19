"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    allowed_hosts: str = "*"
    auth_enabled: bool = False
    auth_secret_key: str = ""
    auth_session_max_age: int = 86400
    auth_users: str = ""
    auth_secure_cookies: bool = False
    rate_limit_login: str = "5/minute"
    rate_limit_upload: str = "10/minute"
    rate_limit_lookup: str = "30/minute"
    belgiss_api_url: str = "https://api.belgiss.by"
    belgiss_public_url: str = "https://tsouz.belgiss.by"
    request_timeout_seconds: float = 30.0
    lookup_concurrency: int = 2
    lookup_delay_seconds: float = 0.25
    cache_ttl_seconds: int = 86400
    cache_path: Path = Path("data/cache.sqlite")
    max_batch_size: int = 100
    http_ssl_verify: bool = Field(
        default=True,
        validation_alias=AliasChoices("http_ssl_verify", "belgiss_ssl_verify"),
    )
    fsa_base_url: str = "https://pub.fsa.gov.ru"
    fsa_login_username: str = "anonymous"
    fsa_login_password: str = "hrgesf7HDR67Bd"
    eokno_register_url: str = (
        "https://eokno.gov.kz/public-register/register-ktrm.xhtml"
    )
    swis_base_url: str = "https://swis.trade.kg"
    eaeu_odata_url: str = "https://tech.eaeunion.org/odata/ConformityDocDetailsType"
    eaeu_register_view_url: str = (
        "https://tech.eaeunion.org/tech/registers/35-1/ru/registryList/conformityDocs/view"
    )
    pdf_max_bytes: int = 15 * 1024 * 1024
    xlsx_max_bytes: int = 15 * 1024 * 1024
    pdf_ocr_max_pages: int = 5
    pdf_ocr_enabled: bool = True
    pdf_ocr_rec_lang: str = "eslav"
    log_level: str = "INFO"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    @property
    def belgiss_ssl_verify(self) -> bool:
        """Deprecated alias for :attr:`http_ssl_verify`."""
        return self.http_ssl_verify

    @property
    def allowed_host_list(self) -> list[str]:
        raw = self.allowed_hosts.strip()
        if not raw or raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() == "production"

    @model_validator(mode="after")
    def validate_auth_settings(self) -> Settings:
        if not self.auth_enabled:
            return self
        if not self.auth_secret_key.strip():
            raise ValueError("AUTH_SECRET_KEY is required when AUTH_ENABLED=true")
        if not self.auth_users.strip():
            raise ValueError("AUTH_USERS is required when AUTH_ENABLED=true")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
