from __future__ import annotations

import httpx

from cert_parser.config import Settings
from cert_parser.domain.errors import CertificateNotFoundError, SourceUnavailableError
from cert_parser.infrastructure.registries.pdf_urls import build_certificate_pdf_proxy_url
from cert_parser.logging_setup import log_step

_PRINT_PATHS = (
    "/api/v1/rss/common/certificates/print/{registry_id}",
    "/api/v1/rss/common/certificates/{registry_id}/print",
    "/api/v1/rss/common/certificates/extract/{registry_id}",
)


def build_fsa_pdf_proxy_url(registry_id: str) -> str:
    return build_certificate_pdf_proxy_url("fsa", registry_id)


async def fetch_fsa_certificate_pdf(
    client: httpx.AsyncClient,
    registry_id: str,
    settings: Settings,
    *,
    token: str | None = None,
) -> bytes:
    base = settings.fsa_base_url.rstrip("/")
    bearer = token
    if bearer is None:
        bearer = await _anonymous_token(client, settings)
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Origin": base,
        "Referer": f"{base}/rss/certificate",
    }
    last_error: Exception | None = None
    for path_template in _PRINT_PATHS:
        path = path_template.format(registry_id=registry_id)
        url = f"{base}{path}"
        log_step(f"RU PDF: GET {path}")
        try:
            response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            last_error = exc
            continue
        if response.status_code == 404:
            continue
        if response.status_code >= 400:
            last_error = SourceUnavailableError("Реестр Росаккредитации вернул ошибку")
            continue
        payload = response.content
        if payload.startswith(b"%PDF-"):
            return payload
        content_type = response.headers.get("content-type", "")
        if "pdf" in content_type.lower() and payload:
            return payload
    if last_error is not None:
        raise SourceUnavailableError("Реестр Росаккредитации недоступен") from last_error
    raise CertificateNotFoundError("PDF сертификата не найден в реестре Росаккредитации")


async def _anonymous_token(client: httpx.AsyncClient, settings: Settings) -> str:
    base = settings.fsa_base_url.rstrip("/")
    await client.get(f"{base}/rss/certificate")
    response = await client.post(
        f"{base}/login",
        json={
            "username": settings.fsa_login_username,
            "password": settings.fsa_login_password,
        },
        headers={
            "Origin": base,
            "Referer": f"{base}/rss/certificate",
            "Content-Type": "application/json",
        },
    )
    if response.status_code >= 400:
        raise SourceUnavailableError("Не удалось авторизоваться в реестре Росаккредитации")
    token = response.headers.get("Authorization") or response.headers.get("authorization")
    if not token:
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            token = str(body.get("access_token") or body.get("token") or "")
    if not token:
        raise SourceUnavailableError("Реестр Росаккредитации не вернул токен")
    if token.lower().startswith("bearer "):
        token = token[7:]
    return token
