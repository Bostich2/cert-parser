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
    auth_users_file: Path | None = None
    auth_secure_cookies: bool = False
    rate_limit_login: str = "5/minute"
    rate_limit_upload: str = "10/minute"
    rate_limit_lookup: str = "30/minute"
    belgiss_api_url: str = "https://api.belgiss.by"
    belgiss_public_url: str = "https://tsouz.belgiss.by"
    request_timeout_seconds: float = 30.0
    lookup_concurrency: int = 2
    lookup_delay_seconds: float = 0.25
    lookup_eaeu_first: bool = True
    cache_ttl_seconds: int = 86400
    cache_path: Path = Path("data/cache.sqlite")
    max_batch_size: int = 100
    http_ssl_verify: bool = Field(
        default=True,
        validation_alias=AliasChoices("http_ssl_verify", "belgiss_ssl_verify"),
    )
    fsa_base_url: str = "https://pub.fsa.gov.ru"
    fsa_login_username: str = Field(default="anonymous", validation_alias="FSA_LOGIN_USERNAME")
    fsa_login_password: str = Field(default="hrgesf7HDR67Bd", validation_alias="FSA_LOGIN_PASSWORD")
    eokno_register_url: str = (
        "https://eokno.gov.kz/public-register/register-ktrm.xhtml"
    )
    swis_base_url: str = "https://swis.trade.kg"
    eaeu_odata_url: str = "https://tech.eaeunion.org/odata/ConformityDocDetailsType"
    eaeu_register_view_url: str = (
        "https://tech.eaeunion.org/tech/registers/35-1/ru/registryList/conformityDocs/view"
    )
    eaeu_platform_url: str = "https://tech.eaeunion.org/platformsvc"
    eaeu_card_pdf_process_id: str = "592344f3-1b37-4837-9bea-a1df3702cf72"
    eaeu_card_pdf_registry_key: str = "r035_1"
    eaeu_card_pdf_section: str = "ОП 36"
    eaeu_card_pdf_registry: str = "conformityDocs"
    eaeu_card_pdf_collection: str = "service-prop-35_1-conformityDocDetailsType"
    pdf_max_bytes: int = 15 * 1024 * 1024
    xlsx_max_bytes: int = 15 * 1024 * 1024
    pdf_ocr_max_pages: int = 5
    pdf_ocr_enabled: bool = True
    pdf_ocr_rec_lang: str = "eslav"
    pdf_processing_timeout_seconds: float = 120.0
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
        hosts = [item.strip() for item in raw.split(",") if item.strip()]
        for host in ("localhost", "127.0.0.1", "web"):
            if host not in hosts:
                hosts.append(host)
        return hosts

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() == "production"

    @model_validator(mode="after")
    def validate_auth_settings(self) -> Settings:
        if self.is_production:
            if not self.auth_enabled:
                raise ValueError("AUTH_ENABLED must be true when ENV=production")
            if not self.http_ssl_verify:
                raise ValueError("HTTP_SSL_VERIFY must be true when ENV=production")
        if not self.auth_enabled:
            return self
        secret = self.auth_secret_key.strip()
        if not secret:
            raise ValueError("AUTH_SECRET_KEY is required when AUTH_ENABLED=true")
        if len(secret) < 32:
            raise ValueError("AUTH_SECRET_KEY must be at least 32 characters when AUTH_ENABLED=true")
        if not self.auth_users.strip() and self.auth_users_file is None:
            raise ValueError("AUTH_USERS or AUTH_USERS_FILE is required when AUTH_ENABLED=true")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
