from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from sert_parser.config import Settings
from sert_parser.domain.certificate_number import parse_certificate_number
from sert_parser.domain.errors import CertificateNotFoundError
from sert_parser.infrastructure.registries.armenia import ArmeniaProvider

FIXTURES = Path(__file__).parent / "fixtures"
REAL_EXAMPLE = "ЕАЭС AM-008/S.A-0175-2018"
CCN_EXAMPLE = "ЕАЭС AM C-CN.АБ12.В.00001/24"
ODATA_URL = "https://tech.eaeunion.org/odata/ConformityDocDetailsType"


def _provider() -> ArmeniaProvider:
    settings = Settings(lookup_delay_seconds=0)
    return ArmeniaProvider(httpx.AsyncClient(timeout=5.0), settings)


def _odata_response(name: str) -> httpx.Response:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return httpx.Response(200, json=payload)


@respx.mock
async def test_armenia_lookup_exact_doc_id() -> None:
    respx.get(ODATA_URL).mock(return_value=_odata_response("am_odata_result.json"))
    provider = _provider()
    record = await provider.lookup(parse_certificate_number(REAL_EXAMPLE))
    assert record.registry_id == "5d28aa003903dc22625ea619"
    assert record.official_number == REAL_EXAMPLE
    assert str(record.valid_from) == "2018-11-23"
    assert record.valid_until is None
    assert record.status_code == "01"
    assert record.status_label == "действует"
    assert record.url.endswith("/5d28aa003903dc22625ea619")
    await provider._client.aclose()


@respx.mock
async def test_armenia_lookup_ccn_format() -> None:
    respx.get(ODATA_URL).mock(return_value=_odata_response("am_odata_ccn_result.json"))
    provider = _provider()
    record = await provider.lookup(parse_certificate_number(CCN_EXAMPLE))
    assert record.registry_id == "am-test-id-00001"
    assert record.official_number == CCN_EXAMPLE
    assert str(record.valid_from) == "2024-01-15"
    assert str(record.valid_until) == "2029-01-14"
    await provider._client.aclose()


@respx.mock
async def test_armenia_not_found() -> None:
    respx.get(ODATA_URL).mock(return_value=httpx.Response(200, json={"value": []}))
    provider = _provider()
    with pytest.raises(CertificateNotFoundError):
        await provider.lookup(parse_certificate_number(REAL_EXAMPLE))
    await provider._client.aclose()


@respx.mock
async def test_armenia_ping() -> None:
    respx.get(ODATA_URL).mock(return_value=_odata_response("am_odata_result.json"))
    provider = _provider()
    assert await provider.ping() is True
    await provider._client.aclose()
