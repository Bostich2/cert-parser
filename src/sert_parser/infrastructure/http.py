from __future__ import annotations

import ssl

import httpx
import truststore

from sert_parser.config import Settings


def build_http_client(
    settings: Settings,
    extra_headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    verify: ssl.SSLContext | bool
    if settings.http_ssl_verify:
        verify = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    else:
        verify = False
    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    }
    if extra_headers:
        headers.update(extra_headers)
    return httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        headers=headers,
        follow_redirects=True,
        verify=verify,
    )
