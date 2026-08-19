from __future__ import annotations

import httpx
import pytest
import respx

from cert_parser.config import Settings
from cert_parser.infrastructure.registries.fsa_pdf import (
    build_fsa_pdf_proxy_url,
    fetch_fsa_certificate_pdf,
)

BASE = "https://pub.fsa.gov.ru"
REGISTRY_ID = "2360455"
PDF_BYTES = b"%PDF-1.4 fsa"


def test_build_fsa_pdf_proxy_url() -> None:
    url = build_fsa_pdf_proxy_url(REGISTRY_ID)
    assert url == f"/api/certificate-pdf?source=fsa&registry_id={REGISTRY_ID}"


@respx.mock
async def test_fetch_fsa_certificate_pdf_uses_print_endpoint() -> None:
    settings = Settings(lookup_delay_seconds=0)
    client = httpx.AsyncClient(timeout=5.0)
    respx.get(f"{BASE}/rss/certificate").mock(return_value=httpx.Response(200, text="ok"))
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"Authorization": "Bearer token"})
    )
    respx.get(f"{BASE}/api/v1/rss/common/certificates/print/{REGISTRY_ID}").mock(
        return_value=httpx.Response(200, content=PDF_BYTES)
    )

    payload = await fetch_fsa_certificate_pdf(client, REGISTRY_ID, settings)
    assert payload == PDF_BYTES
    await client.aclose()
