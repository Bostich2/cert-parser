from __future__ import annotations

import httpx
import pytest
import respx

from cert_parser.config import Settings
from cert_parser.domain.certificate_number import parse_certificate_number
from cert_parser.domain.errors import CertificateNotFoundError, SourceUnavailableError
from cert_parser.infrastructure.registries.belarus import BelgissProvider

EXAMPLE = "ЕАЭС BY/112 02.01. ТР018 010.02 00276"
API_PATTERN = r"https://api\.belgiss\.by/tsouz/tsouz-certifs-light"


def _provider() -> BelgissProvider:
    settings = Settings(lookup_delay_seconds=0)
    client = httpx.AsyncClient(timeout=5.0)
    return BelgissProvider(client, settings)


def _mock_search(response: httpx.Response) -> None:
    respx.route(method="GET", url__regex=API_PATTERN).mock(return_value=response)


@respx.mock
async def test_belgiss_lookup_returns_card_url_and_validity() -> None:
    _mock_search(
        httpx.Response(
            200,
            json={
                "items": [
                    {
                        "certdecltr_id": 3345084,
                        "DocId": EXAMPLE,
                        "certdecltr_DocStartDate": "2024-05-29",
                        "certdecltr_DocValidityDate": "2029-05-29",
                        "certdecltr_DocStatusDetails": {"DocStatusCode": "01"},
                    }
                ],
                "_meta": {"totalCount": 1},
            },
        )
    )
    provider = _provider()
    record = await provider.lookup(parse_certificate_number(EXAMPLE))
    assert record.registry_id == "3345084"
    assert record.url.endswith("/#!/tsouz/certifs/3345084/view")
    assert str(record.valid_from) == "2024-05-29"
    assert str(record.valid_until) == "2029-05-29"
    assert record.status_label == "действует"
    await provider._client.aclose()


@respx.mock
async def test_belgiss_not_found() -> None:
    _mock_search(httpx.Response(200, json={"items": [], "_meta": {"totalCount": 0}}))
    provider = _provider()
    with pytest.raises(CertificateNotFoundError):
        await provider.lookup(parse_certificate_number(EXAMPLE))
    await provider._client.aclose()


@respx.mock
async def test_belgiss_source_unavailable() -> None:
    _mock_search(httpx.Response(500, json={"message": "error"}))
    provider = _provider()
    with pytest.raises(SourceUnavailableError):
        await provider.lookup(parse_certificate_number(EXAMPLE))
    await provider._client.aclose()
