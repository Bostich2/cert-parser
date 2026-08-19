from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from sert_parser.config import Settings
from sert_parser.domain.certificate_number import parse_certificate_number
from sert_parser.domain.errors import CertificateNotFoundError
from sert_parser.infrastructure.registries.kazakhstan import EoknoProvider
from sert_parser.infrastructure.registries.kazakhstan_html import (
    extract_search_form,
    is_certificate_row,
    parse_result_rows,
)

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = "ЕАЭС KZ 1100317.05.01.05103"
URL = "https://eokno.gov.kz/public-register/register-ktrm.xhtml"


def _provider() -> EoknoProvider:
    settings = Settings(lookup_delay_seconds=0)
    return EoknoProvider(httpx.AsyncClient(timeout=5.0), settings)


def test_extract_form_discovers_filter_from_header_context() -> None:
    html = (FIXTURES / "eokno_form.html").read_text(encoding="utf-8")
    form = extract_search_form(html)
    assert form is not None
    assert form.view_state == "VIEWSTATE123"
    assert form.number_filter_name.endswith(":filter")


def test_parse_partial_xml_rows() -> None:
    payload = (FIXTURES / "eokno_filtered.xml").read_text(encoding="utf-8")
    rows = parse_result_rows(payload)
    assert len(rows) == 1
    assert rows[0].official_number == EXAMPLE
    assert rows[0].registry_id == "3849075"
    assert rows[0].valid_from_raw == "01.01.2024"
    assert rows[0].valid_until_raw == "31.12.2027"
    assert is_certificate_row(rows[0]) is True


@respx.mock
async def test_eokno_lookup_parses_filtered_table() -> None:
    respx.get(URL).mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "eokno_form.html").read_text(encoding="utf-8"),
        )
    )
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "eokno_filtered.xml").read_text(encoding="utf-8"),
        )
    )
    provider = _provider()
    record = await provider.lookup(parse_certificate_number(EXAMPLE))
    assert record.registry_id == "3849075"
    assert str(record.valid_from) == "2024-01-01"
    assert str(record.valid_until) == "2027-12-31"
    assert record.status_label == "действует"
    assert "eokno.gov.kz" in record.url
    await provider._client.aclose()


@respx.mock
async def test_eokno_not_found() -> None:
    empty = """<?xml version="1.0"?><partial-response><changes><update id="x"><![CDATA[
    <table><thead><tr><th>Тіркеу нөмірі</th></tr></thead><tbody></tbody></table>
    ]]></update></changes></partial-response>"""
    respx.get(URL).mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "eokno_form.html").read_text(encoding="utf-8"),
        )
    )
    respx.post(URL).mock(return_value=httpx.Response(200, text=empty))
    provider = _provider()
    with pytest.raises(CertificateNotFoundError):
        await provider.lookup(parse_certificate_number(EXAMPLE))
    await provider._client.aclose()


def test_eokno_unrelated_rows_are_not_found() -> None:
    from sert_parser.infrastructure.registries.kazakhstan import _pick_row
    from sert_parser.infrastructure.registries.kazakhstan_html import EoknoRow

    number = parse_certificate_number("ЕАЭС KZ 7500533.01.01.06080")
    rows = [
        EoknoRow(
            registry_id="1",
            official_number="ЕАЭС KZ 1100317.05.01.05106",
            valid_from_raw="",
            valid_until_raw="",
            status_raw="действует",
            doc_type="",
        ),
        EoknoRow(
            registry_id="2",
            official_number="ЕАЭС KZ 1100317.05.01.05103",
            valid_from_raw="",
            valid_until_raw="",
            status_raw="действует",
            doc_type="",
        ),
    ]
    with pytest.raises(CertificateNotFoundError):
        _pick_row(rows, number)
