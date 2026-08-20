from __future__ import annotations

import httpx
import pytest
import respx

from cert_parser.application.product_search_service import ProductSearchService
from cert_parser.config import Settings
from cert_parser.domain.errors import SourceUnavailableError
from cert_parser.domain.product_query import parse_product_search_query
from cert_parser.infrastructure.registries.eaeu_odata import EaeuProductSearchProvider
from cert_parser.infrastructure.registries.fsa_session import fsa_list_payload, fsa_product_name
from cert_parser.infrastructure.registries.fsa_declarations import FSA_DECL_PRODUCT_COLUMN, FsaDeclarationsProvider
from cert_parser.infrastructure.registries.russia import FSA_CERT_PRODUCT_COLUMN, FsaProvider

BASE = "https://pub.fsa.gov.ru"
ODATA_URL = "https://tech.eaeunion.org/odata/ConformityDocDetailsType"
QUERY = "насос погружной"


def _settings() -> Settings:
    return Settings(lookup_delay_seconds=0)


def _mock_fsa_auth() -> None:
    respx.get(f"{BASE}/rss/certificate").mock(return_value=httpx.Response(200, text="ok"))
    respx.get(f"{BASE}/rds/declaration").mock(return_value=httpx.Response(200, text="ok"))
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"Authorization": "Bearer test-token"})
    )
    respx.get(f"{BASE}/api/v1/rss/common/identifiers").mock(
        return_value=httpx.Response(200, json={"status": {"6": {"name": "Действует"}}})
    )
    respx.get(f"{BASE}/api/v1/rds/common/identifiers").mock(
        return_value=httpx.Response(200, json={"status": {"6": {"name": "Действует"}}})
    )


def test_fsa_product_columns_are_product_full_name() -> None:
    assert FSA_CERT_PRODUCT_COLUMN == "productFullName"
    assert FSA_DECL_PRODUCT_COLUMN == "productFullName"
    payload = fsa_list_payload("productFullName", "шины", size=5, sort_column="declDate")
    assert payload["columnsSort"] == [{"column": "declDate", "sort": "DESC"}]
    assert fsa_product_name({"productFullName": "Шины Cordiant", "applicantName": "ООО Ромашка"}) == "Шины Cordiant"


@respx.mock
async def test_fsa_cert_search_uses_product_fullname_column() -> None:
    _mock_fsa_auth()

    def check_payload(request: httpx.Request) -> httpx.Response:
        body = request.read()
        assert FSA_CERT_PRODUCT_COLUMN.encode() in body
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 111,
                        "number": "ЕАЭС RU С-CN.АА01.В.00001/24",
                        "productFullName": "Насос погружной",
                        "startDate": "2024-01-15",
                        "endDate": "2029-12-31",
                        "idStatus": 6,
                    }
                ]
            },
        )

    respx.post(f"{BASE}/api/v1/rss/common/certificates/get").mock(side_effect=check_payload)
    provider = FsaProvider(httpx.AsyncClient(timeout=5.0), _settings())
    query = parse_product_search_query(QUERY)
    assert query is not None
    hits = await provider.search_products(query, limit=10)
    await provider._client.aclose()
    assert len(hits) == 1
    assert hits[0].source == "fsa_cert"
    assert hits[0].doc_kind == "certificate"
    assert hits[0].country_code == "RU"
    assert hits[0].product_name == "Насос погружной"
    assert hits[0].url.endswith("/rss/certificate/view/111/baseInfo")
    assert hits[0].pdf_url


@respx.mock
async def test_fsa_decl_search_uses_product_fullname_and_no_pdf() -> None:
    _mock_fsa_auth()

    def check_payload(request: httpx.Request) -> httpx.Response:
        body = request.read()
        assert FSA_DECL_PRODUCT_COLUMN.encode() in body
        assert b"declDate" in body
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 222,
                        "number": "ЕАЭС N RU Д-DE.АА01.В.00002/24",
                        "productFullName": "Насос",
                        "declDate": "2024-02-01",
                        "declEndDate": "2029-02-01",
                        "idStatus": 6,
                    }
                ]
            },
        )

    respx.post(f"{BASE}/api/v1/rds/common/declarations/get").mock(side_effect=check_payload)
    provider = FsaDeclarationsProvider(httpx.AsyncClient(timeout=5.0), _settings())
    query = parse_product_search_query(QUERY)
    assert query is not None
    hits = await provider.search_products(query, limit=10)
    await provider._client.aclose()
    assert len(hits) == 1
    assert hits[0].source == "fsa_decl"
    assert hits[0].doc_kind == "declaration"
    assert hits[0].pdf_url is None
    assert hits[0].url.endswith("/rds/declaration/view/222/baseInfo")
    assert str(hits[0].valid_from) == "2024-02-01"
    assert str(hits[0].valid_until) == "2029-02-01"


@respx.mock
async def test_fsa_403_still_returns_eaeu_hits() -> None:
    respx.get(f"{BASE}/rss/certificate").mock(return_value=httpx.Response(200, text="ok"))
    respx.get(f"{BASE}/rds/declaration").mock(return_value=httpx.Response(200, text="ok"))
    respx.post(f"{BASE}/login").mock(return_value=httpx.Response(403, text="forbidden"))

    odata_item = {
        "docId": "ЕАЭС RU С-CN.АА01.В.00001/24",
        "docStartDate": "2024-01-15T00:00:00+03:00",
        "docValidityDate": "2029-01-14T00:00:00+03:00",
        "Id": "eaeu-1",
        "unifiedCountryCode": {"value": "RU"},
        "docStatusDetails": {"docStatusCode": "01"},
        "conformityDocKindName": "Сертификат соответствия",
        "technicalRegulationObjectDetails": {
            "productDetails": [{"productName": "Насос погружной"}]
        },
    }

    def odata_response(request: httpx.Request) -> httpx.Response:
        filt = request.url.params.get("$filter", "")
        if "eq 'RU'" in filt:
            return httpx.Response(200, json={"value": [odata_item]})
        return httpx.Response(200, json={"value": []})

    respx.get(ODATA_URL).mock(side_effect=odata_response)

    settings = _settings()
    client = httpx.AsyncClient(timeout=5.0)
    fsa = FsaProvider(client, settings)
    decls = FsaDeclarationsProvider(client, settings)
    eaeu_ru = EaeuProductSearchProvider(client, settings, russia_only=True)
    eaeu_other = EaeuProductSearchProvider(client, settings, russia_only=False)
    service = ProductSearchService([fsa, decls, eaeu_ru, eaeu_other], settings)
    hits = await service.search_one(QUERY)
    await client.aclose()
    assert any(hit.source == "eaeu_ru" and hit.error_code is None for hit in hits)
    assert all(hit.error_code != "source_unavailable" or hit.source is None for hit in hits)


@respx.mock
async def test_fsa_cert_forbidden_raises() -> None:
    respx.get(f"{BASE}/rss/certificate").mock(return_value=httpx.Response(200, text="ok"))
    respx.post(f"{BASE}/login").mock(return_value=httpx.Response(403, text="forbidden"))
    provider = FsaProvider(httpx.AsyncClient(timeout=5.0), _settings())
    query = parse_product_search_query(QUERY)
    assert query is not None
    with pytest.raises(SourceUnavailableError, match="403"):
        await provider.search_products(query, limit=10)
    await provider._client.aclose()


@respx.mock
async def test_fsa_cert_timeout_on_phrase_tries_next_term() -> None:
    _mock_fsa_auth()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = request.read().decode()
        if "насос погружной" in body:
            raise httpx.TimeoutException("slow phrase")
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 111,
                        "number": "ЕАЭС RU С-CN.АА01.В.00001/24",
                        "productFullName": "Насос погружной",
                        "idStatus": 6,
                    }
                ]
            },
        )

    respx.post(f"{BASE}/api/v1/rss/common/certificates/get").mock(side_effect=handler)
    provider = FsaProvider(httpx.AsyncClient(timeout=5.0), _settings())
    query = parse_product_search_query(QUERY)
    assert query is not None
    hits = await provider.search_products(query, limit=10)
    await provider._client.aclose()
    assert calls["n"] >= 2
    assert len(hits) == 1
    assert hits[0].source == "fsa_cert"
