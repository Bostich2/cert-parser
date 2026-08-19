from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from cert_parser.config import Settings
from cert_parser.domain.certificate_number import parse_certificate_number
from cert_parser.domain.errors import CertificateNotFoundError, SourceUnavailableError
from cert_parser.infrastructure.registries.belarus import BelgissProvider
from cert_parser.infrastructure.registries.chained import build_lookup_chain
from cert_parser.infrastructure.registries.eaeu_odata import EaeuOdataProvider

EXAMPLE = "ЕАЭС BY/112 02.01. ТР018 010.02 00276"
API_PATTERN = r"https://api\.belgiss\.by/tsouz/tsouz-certifs-light"
ODATA_URL = "https://tech.eaeunion.org/odata/ConformityDocDetailsType"
FIXTURES = Path(__file__).parent / "fixtures"


def _belarus_chain(*, eaeu_first: bool = True):
    settings = Settings(lookup_delay_seconds=0)
    client = httpx.AsyncClient(timeout=5.0)
    belgiss = BelgissProvider(client, settings)
    eaeu = EaeuOdataProvider(client, settings, country_code="BY")
    return build_lookup_chain(
        "BY",
        eaeu,
        belgiss,
        eaeu_label="tech.eaeunion.org",
        national_label="api.belgiss.by",
        eaeu_first=eaeu_first,
    )


def _odata_response(name: str) -> httpx.Response:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return httpx.Response(200, json=payload)


def _mock_belgiss(response: httpx.Response) -> None:
    respx.route(method="GET", url__regex=API_PATTERN).mock(return_value=response)


@respx.mock
async def test_eaeu_first_returns_odata_without_calling_belgiss() -> None:
    respx.get(ODATA_URL).mock(return_value=_odata_response("by_odata_result.json"))
    belgiss_route = respx.route(method="GET", url__regex=API_PATTERN).mock(
        return_value=httpx.Response(200, json={"items": [], "_meta": {"totalCount": 0}})
    )
    provider = _belarus_chain(eaeu_first=True)
    record = await provider.lookup(parse_certificate_number(EXAMPLE))
    assert record.registry_id == "683995d030dcf80e6d482f40"
    assert "tech.eaeunion.org" in record.url
    assert not belgiss_route.called
    await provider._steps[0][0]._client.aclose()


@respx.mock
async def test_eaeu_first_falls_back_to_belgiss_when_odata_not_found() -> None:
    respx.get(ODATA_URL).mock(return_value=httpx.Response(200, json={"value": []}))
    _mock_belgiss(
        httpx.Response(
            200,
            json={
                "items": [
                    {
                        "certdecltr_id": 3345084,
                        "DocId": EXAMPLE,
                        "certdecltr_DocStartDate": "2025-05-30",
                        "certdecltr_DocValidityDate": "2029-05-29",
                        "certdecltr_DocStatusDetails": {"DocStatusCode": "01"},
                    }
                ],
                "_meta": {"totalCount": 1},
            },
        )
    )
    provider = _belarus_chain(eaeu_first=True)
    record = await provider.lookup(parse_certificate_number(EXAMPLE))
    assert record.registry_id == "3345084"
    assert "belgiss.by" in record.url
    await provider._steps[0][0]._client.aclose()


@respx.mock
async def test_eaeu_first_falls_back_to_belgiss_when_odata_unavailable() -> None:
    respx.get(ODATA_URL).mock(return_value=httpx.Response(503))
    _mock_belgiss(
        httpx.Response(
            200,
            json={
                "items": [
                    {
                        "certdecltr_id": 3345084,
                        "DocId": EXAMPLE,
                        "certdecltr_DocStartDate": "2025-05-30",
                        "certdecltr_DocValidityDate": "2029-05-29",
                        "certdecltr_DocStatusDetails": {"DocStatusCode": "01"},
                    }
                ],
                "_meta": {"totalCount": 1},
            },
        )
    )
    provider = _belarus_chain(eaeu_first=True)
    record = await provider.lookup(parse_certificate_number(EXAMPLE))
    assert record.registry_id == "3345084"
    await provider._steps[0][0]._client.aclose()


@respx.mock
async def test_national_first_falls_back_to_eaeu_when_belgiss_unavailable() -> None:
    respx.route(method="GET", url__regex=API_PATTERN).mock(
        side_effect=httpx.ConnectError("SSL verify failed")
    )
    respx.get(ODATA_URL).mock(return_value=_odata_response("by_odata_result.json"))
    provider = _belarus_chain(eaeu_first=False)
    record = await provider.lookup(parse_certificate_number(EXAMPLE))
    assert record.registry_id == "683995d030dcf80e6d482f40"
    assert "tech.eaeunion.org" in record.url
    await provider._steps[0][0]._client.aclose()


@respx.mock
async def test_chain_raises_when_all_sources_fail() -> None:
    respx.get(ODATA_URL).mock(return_value=httpx.Response(200, json={"value": []}))
    _mock_belgiss(httpx.Response(200, json={"items": [], "_meta": {"totalCount": 0}}))
    provider = _belarus_chain(eaeu_first=True)
    with pytest.raises(CertificateNotFoundError):
        await provider.lookup(parse_certificate_number(EXAMPLE))
    await provider._steps[0][0]._client.aclose()


@respx.mock
async def test_chain_ping_succeeds_if_any_provider_is_up() -> None:
    respx.get(ODATA_URL).mock(return_value=httpx.Response(503))
    _mock_belgiss(
        httpx.Response(
            200,
            json={"items": [], "_meta": {"totalCount": 0}},
        )
    )
    provider = _belarus_chain(eaeu_first=True)
    assert await provider.ping() is True
    await provider._steps[0][0]._client.aclose()
