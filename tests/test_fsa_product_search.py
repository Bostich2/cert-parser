from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
import respx

from cert_parser.application.product_search_service import ProductSearchService
from cert_parser.config import Settings
from cert_parser.domain.errors import SourceUnavailableError
from cert_parser.domain.product_query import parse_product_search_query
from cert_parser.infrastructure.registries.eaeu_odata import EaeuProductSearchProvider
from cert_parser.infrastructure.registries.fsa_filters import (
    acting_status_ids,
    tech_reg_ids_for_query,
    tr_codes_for_query,
)
from cert_parser.infrastructure.registries.fsa_session import FsaSession, fsa_list_payload, fsa_product_name
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
    assert "status" not in payload["filter"]
    assert payload["filter"]["endDate"]["minDate"] == ""
    assert fsa_product_name({"productFullName": "Шины Cordiant", "applicantName": "ООО Ромашка"}) == "Шины Cordiant"


def test_fsa_product_payload_narrows_to_acting_and_unexpired() -> None:
    payload = fsa_list_payload(
        "productFullName",
        "шины",
        size=5,
        sort_column="declDate",
        active_only=True,
        status_ids=[6],
        as_of=date(2026, 8, 20),
    )
    assert payload["filter"]["status"] == [6]
    assert payload["filter"]["endDate"]["minDate"] == "2026-08-20T00:00:00.000Z"
    assert payload["filter"]["idTechReg"] == []


def test_lookup_payload_does_not_narrow_by_status_or_date() -> None:
    payload = fsa_list_payload("number", "ЕАЭС RU", size=10)
    assert "status" not in payload["filter"]
    assert payload["filter"]["endDate"]["minDate"] == ""
    assert payload["filter"]["idTechReg"] == []


def test_tr_codes_and_ids_from_identifiers() -> None:
    query = parse_product_search_query("шины легковые Cordiant")
    assert query is not None
    assert tr_codes_for_query(query) == ("018/2011",)
    ids = tech_reg_ids_for_query(
        query,
        {"techReg": {"11": {"name": "ТР ТС 018/2011 О безопасности колесных транспортных средств"}}},
    )
    assert ids == [11]
    assert acting_status_ids({"status": {"6": {"name": "Действует"}, "7": {"name": "Приостановлен"}}}) == [6]


def _assert_active_product_filter(body: dict, *, tech_reg_ids: list[int] | None = None) -> None:
    filt = body["filter"]
    assert filt["status"] == [6]
    assert filt["endDate"]["minDate"].startswith(date.today().isoformat())
    assert filt["idTechReg"] == (tech_reg_ids or [])


@respx.mock
async def test_fsa_cert_search_uses_product_fullname_column() -> None:
    _mock_fsa_auth()

    def check_payload(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["filter"]["columnsSearch"][0]["name"] == FSA_CERT_PRODUCT_COLUMN
        _assert_active_product_filter(body)
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
        body = json.loads(request.content)
        assert body["filter"]["columnsSearch"][0]["name"] == FSA_DECL_PRODUCT_COLUMN
        assert body["columnsSort"] == [{"column": "declDate", "sort": "DESC"}]
        _assert_active_product_filter(body)
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
        return httpx.Response(200, json={"value": [odata_item]})

    respx.get(ODATA_URL).mock(side_effect=odata_response)

    settings = _settings()
    client = httpx.AsyncClient(timeout=5.0)
    fsa = FsaProvider(client, settings)
    decls = FsaDeclarationsProvider(client, settings)
    eaeu = EaeuProductSearchProvider(client, settings)
    service = ProductSearchService([fsa, decls, eaeu], settings)
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
async def test_fsa_cert_timeout_on_phrase_does_not_retry_term() -> None:
    _mock_fsa_auth()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.TimeoutException("slow phrase")

    respx.post(f"{BASE}/api/v1/rss/common/certificates/get").mock(side_effect=handler)
    provider = FsaProvider(httpx.AsyncClient(timeout=5.0), _settings())
    query = parse_product_search_query(QUERY)
    assert query is not None
    with pytest.raises(SourceUnavailableError, match="вовремя"):
        await provider.search_products(query, limit=10)
    await provider._client.aclose()
    assert calls["n"] == 1


@respx.mock
async def test_fsa_cert_timeout_retries_with_tech_reg() -> None:
    _mock_fsa_auth()
    respx.get(f"{BASE}/api/v1/rss/common/identifiers").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": {"6": {"name": "Действует"}},
                "techReg": {
                    "11": {"name": "ТР ТС 018/2011 О безопасности колесных транспортных средств"}
                },
            },
        )
    )
    calls: list[list[int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        tech_ids = body["filter"]["idTechReg"]
        calls.append(tech_ids)
        _assert_active_product_filter(body, tech_reg_ids=tech_ids)
        if not tech_ids:
            raise httpx.TimeoutException("slow phrase")
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 333,
                        "number": "ЕАЭС RU С-RU.АА01.В.00003/24",
                        "productFullName": "Шины легковые Cordiant",
                        "idStatus": 6,
                    }
                ]
            },
        )

    respx.post(f"{BASE}/api/v1/rss/common/certificates/get").mock(side_effect=handler)
    provider = FsaProvider(httpx.AsyncClient(timeout=5.0), _settings())
    query = parse_product_search_query("шины легковые")
    assert query is not None
    hits = await provider.search_products(query, limit=10)
    await provider._client.aclose()
    assert calls == [[], [11]]
    assert len(hits) == 1
    assert hits[0].product_name == "Шины легковые Cordiant"


@respx.mock
async def test_shared_fsa_session_does_not_login_twice_on_failure() -> None:
    login_calls = {"n": 0}
    respx.get(f"{BASE}/rss/certificate").mock(return_value=httpx.Response(200, text="ok"))
    respx.get(f"{BASE}/rds/declaration").mock(return_value=httpx.Response(200, text="ok"))

    def login(_request: httpx.Request) -> httpx.Response:
        login_calls["n"] += 1
        raise httpx.TimeoutException("slow login")

    respx.post(f"{BASE}/login").mock(side_effect=login)
    client = httpx.AsyncClient(timeout=5.0)
    session = FsaSession(client, _settings())
    certs = FsaProvider(client, _settings(), session=session)
    decls = FsaDeclarationsProvider(client, _settings(), session=session)
    query = parse_product_search_query(QUERY)
    assert query is not None
    with pytest.raises(SourceUnavailableError):
        await certs.search_products(query, limit=10)
    with pytest.raises(SourceUnavailableError):
        await decls.search_products(query, limit=10)
    await client.aclose()
    assert login_calls["n"] == 1
