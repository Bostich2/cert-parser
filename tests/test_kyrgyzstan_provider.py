from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from cert_parser.config import Settings
from cert_parser.domain.certificate_number import parse_certificate_number
from cert_parser.domain.errors import AmbiguousMatchError, CertificateNotFoundError
from cert_parser.infrastructure.registries.kyrgyzstan import SwisProvider, _pick_row
from cert_parser.infrastructure.registries.kyrgyzstan_html import SwisRow, parse_result_rows, status_label

FIXTURES = Path(__file__).parent / "fixtures"
CERT_EXAMPLE = "ЕАЭС KG417/016.ru.02.04561"
DECL_EXAMPLE = "ЕАЭС KG417/18.д.0000338"
BASE = "https://swis.trade.kg"


def _provider() -> SwisProvider:
    settings = Settings(lookup_delay_seconds=0)
    return SwisProvider(httpx.AsyncClient(timeout=5.0), settings)


def test_parse_certificate_result_rows() -> None:
    html = (FIXTURES / "kg_swis_result.html").read_text(encoding="utf-8")
    rows = parse_result_rows(html, registry_kind="certificate")
    assert len(rows) == 1
    assert rows[0].official_number == "ЕАЭС KG417/016.RU.02.04561"
    assert rows[0].status_raw == "Действует"
    assert rows[0].valid_from_raw == "1 июль 2026"
    assert rows[0].valid_until_raw == "30 июнь 2031"
    assert rows[0].doc_path == "/Doc/06c84841-72f1-4e14-ac9f-0cbffa30a283"


def test_parse_declaration_result_rows() -> None:
    html = (FIXTURES / "kg_swis_decl_result.html").read_text(encoding="utf-8")
    rows = parse_result_rows(html, registry_kind="declaration")
    assert len(rows) == 1
    assert rows[0].official_number == "ЕАЭС KG417/18.Д.0000338"
    assert rows[0].status_raw == "Прекращена"


def test_status_label_maps_known_values() -> None:
    assert status_label("Действует") == ("01", "Действует")
    assert status_label("Прекращена") == ("03", "Прекращена")


@respx.mock
async def test_swis_lookup_certificate() -> None:
    html = (FIXTURES / "kg_swis_result.html").read_text(encoding="utf-8")
    respx.get(f"{BASE}/Registry/CertificateOfConformity").mock(return_value=httpx.Response(200, text=html))
    provider = _provider()
    record = await provider.lookup(parse_certificate_number(CERT_EXAMPLE))
    assert record.registry_id == "06c84841-72f1-4e14-ac9f-0cbffa30a283"
    assert record.official_number == "ЕАЭС KG417/016.RU.02.04561"
    assert str(record.valid_from) == "2026-07-01"
    assert str(record.valid_until) == "2031-06-30"
    assert record.status_label == "Действует"
    assert "RegisterNumber=" in record.url
    await provider._client.aclose()


@respx.mock
async def test_swis_lookup_declaration_when_certificate_empty() -> None:
    cert_html = (FIXTURES / "kg_swis_page.html").read_text(encoding="utf-8")
    decl_html = (FIXTURES / "kg_swis_decl_result.html").read_text(encoding="utf-8")
    respx.get(f"{BASE}/Registry/CertificateOfConformity").mock(return_value=httpx.Response(200, text=cert_html))
    respx.get(f"{BASE}/Registry/DeclarationOfConformity").mock(return_value=httpx.Response(200, text=decl_html))
    provider = _provider()
    record = await provider.lookup(parse_certificate_number(DECL_EXAMPLE))
    assert record.official_number == "ЕАЭС KG417/18.Д.0000338"
    assert record.status_label == "Прекращена"
    await provider._client.aclose()


@respx.mock
async def test_swis_not_found() -> None:
    html = (FIXTURES / "kg_swis_page.html").read_text(encoding="utf-8")
    respx.get(f"{BASE}/Registry/CertificateOfConformity").mock(return_value=httpx.Response(200, text=html))
    respx.get(f"{BASE}/Registry/DeclarationOfConformity").mock(return_value=httpx.Response(200, text=html))
    provider = _provider()
    with pytest.raises(CertificateNotFoundError):
        await provider.lookup(parse_certificate_number(CERT_EXAMPLE))
    await provider._client.aclose()


def test_swis_pick_row_rejects_single_non_matching_row() -> None:
    number = parse_certificate_number(CERT_EXAMPLE)
    rows = [
        SwisRow(
            official_number="ЕАЭС KG417/016.RU.02.99999",
            status_raw="Действует",
            valid_from_raw="",
            valid_until_raw="",
            doc_path="/Doc/other",
            registry_kind="certificate",
        )
    ]
    with pytest.raises(CertificateNotFoundError):
        _pick_row(rows, number)


def test_swis_pick_row_rejects_ambiguous_substring_hits() -> None:
    number = parse_certificate_number(CERT_EXAMPLE)
    rows = [
        SwisRow(
            official_number="ЕАЭС KG417/016.RU.02.04561-extra",
            status_raw="Действует",
            valid_from_raw="",
            valid_until_raw="",
            doc_path="/Doc/a",
            registry_kind="certificate",
        ),
        SwisRow(
            official_number="prefix-ЕАЭС KG417/016.RU.02.04561",
            status_raw="Действует",
            valid_from_raw="",
            valid_until_raw="",
            doc_path="/Doc/b",
            registry_kind="certificate",
        ),
    ]
    with pytest.raises(AmbiguousMatchError):
        _pick_row(rows, number)
