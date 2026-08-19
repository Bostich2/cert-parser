from __future__ import annotations

import httpx
import pytest
import respx

from cert_parser.config import Settings
from cert_parser.domain.certificate_number import parse_certificate_number
from cert_parser.domain.errors import AmbiguousMatchError, CertificateNotFoundError, SourceUnavailableError
from cert_parser.infrastructure.registries.russia import FsaProvider, _pick_item

EXAMPLE = "ЕАЭС RU С-CN.СБ21.А.00039/19"
BASE = "https://pub.fsa.gov.ru"


def _provider() -> FsaProvider:
    settings = Settings(lookup_delay_seconds=0)
    client = httpx.AsyncClient(timeout=5.0)
    return FsaProvider(client, settings)


def _mock_auth() -> None:
    respx.get(f"{BASE}/rss/certificate").mock(return_value=httpx.Response(200, text="ok"))
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"Authorization": "Bearer test-token"})
    )
    respx.get(f"{BASE}/api/v1/rss/common/identifiers").mock(
        return_value=httpx.Response(
            200,
            json={"status": {"6": {"name": "Действует"}, "7": {"name": "Приостановлен"}}},
        )
    )


@respx.mock
async def test_fsa_lookup_returns_card_and_validity() -> None:
    _mock_auth()
    respx.post(f"{BASE}/api/v1/rss/common/certificates/get").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "items": [
                    {
                        "id": 2360455,
                        "number": EXAMPLE,
                        "startDate": "2024-01-15",
                        "endDate": "2029-12-31",
                        "idStatus": 6,
                    }
                ],
            },
        )
    )
    provider = _provider()
    record = await provider.lookup(parse_certificate_number("ЕАЭС RU C-CN.СБ21.А.00039/19"))
    assert record.registry_id == "2360455"
    assert record.url == f"{BASE}/rss/certificate/view/2360455/baseInfo"
    assert record.pdf_url == f"/api/certificate-pdf?source=fsa&registry_id=2360455"
    assert str(record.valid_from) == "2024-01-15"
    assert str(record.valid_until) == "2029-12-31"
    assert record.status_label == "Действует"
    await provider._client.aclose()


@respx.mock
async def test_fsa_not_found() -> None:
    _mock_auth()
    respx.post(f"{BASE}/api/v1/rss/common/certificates/get").mock(
        return_value=httpx.Response(200, json={"total": 0, "items": []})
    )
    provider = _provider()
    with pytest.raises(CertificateNotFoundError):
        await provider.lookup(parse_certificate_number(EXAMPLE))
    await provider._client.aclose()


@respx.mock
async def test_fsa_rejects_single_non_matching_item() -> None:
    _mock_auth()
    other = "ЕАЭС RU С-CN.СБ21.А.99999/99"
    respx.post(f"{BASE}/api/v1/rss/common/certificates/get").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "items": [
                    {
                        "id": 999,
                        "number": other,
                        "startDate": "2024-01-15",
                        "endDate": "2029-12-31",
                        "idStatus": 6,
                    }
                ],
            },
        )
    )
    provider = _provider()
    with pytest.raises(CertificateNotFoundError):
        await provider.lookup(parse_certificate_number(EXAMPLE))
    await provider._client.aclose()


def test_fsa_pick_item_rejects_ambiguous_substring_hits() -> None:
    number = parse_certificate_number(EXAMPLE)
    items = [
        {"id": 1, "number": "ЕАЭС RU С-CN.СБ21.А.00039/19-extra"},
        {"id": 2, "number": "prefix-ЕАЭС RU С-CN.СБ21.А.00039/19"},
    ]
    with pytest.raises(AmbiguousMatchError):
        _pick_item(items, number)


@respx.mock
async def test_fsa_forbidden_explains_geo() -> None:
    respx.get(f"{BASE}/rss/certificate").mock(return_value=httpx.Response(200, text="ok"))
    respx.post(f"{BASE}/login").mock(return_value=httpx.Response(403, text="forbidden"))
    provider = _provider()
    with pytest.raises(SourceUnavailableError, match="403"):
        await provider.lookup(parse_certificate_number(EXAMPLE))
    await provider._client.aclose()
