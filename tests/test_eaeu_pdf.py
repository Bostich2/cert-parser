from __future__ import annotations

import httpx
import pytest
import respx

from cert_parser.config import Settings
from cert_parser.infrastructure.registries.eaeu_pdf import (
    build_eaeu_pdf_proxy_url,
    fetch_eaeu_card_pdf,
)

BASE = "https://tech.eaeunion.org/platformsvc"
REGISTRY_ID = "683995d030dcf80e6d482f40"
PDF_BYTES = b"%PDF-1.4 test"


def test_build_eaeu_pdf_proxy_url() -> None:
    url = build_eaeu_pdf_proxy_url(REGISTRY_ID)
    assert url == f"/api/certificate-pdf?source=eaeu&registry_id={REGISTRY_ID}"


@respx.mock
async def test_fetch_eaeu_card_pdf_downloads_file() -> None:
    settings = Settings()
    client = httpx.AsyncClient(timeout=5.0)
    respx.post(f"{BASE}/nonauthorizedplatform/executewithjson").mock(
        return_value=httpx.Response(200, json={"instanceid": "inst-1", "status": 0})
    )
    respx.get(f"{BASE}/nonauthorizedplatform/status").mock(
        return_value=httpx.Response(200, json={"status": 0, "instanceid": "inst-1"})
    )
    respx.get(f"{BASE}/nonauthorizedplatform/gettoken").mock(
        return_value=httpx.Response(
            200,
            json={"parameters": [{"name": "fileid", "stringvalue": "file-1"}]},
        )
    )
    respx.get(f"{BASE}/nonauthorizedplatform/filedownload").mock(
        return_value=httpx.Response(200, content=PDF_BYTES)
    )

    payload = await fetch_eaeu_card_pdf(client, REGISTRY_ID, settings)
    assert payload == PDF_BYTES
    await client.aclose()
