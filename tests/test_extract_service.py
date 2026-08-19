from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import Workbook

from cert_parser.application.export_service import ExportService
from cert_parser.application.extract_service import ExtractService
from cert_parser.config import Settings

EXAMPLE = "ЕАЭС BY/112 02.01. ТР018 010.02 00276"


def _xlsx_bytes(*values: str) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for index, value in enumerate(values, start=1):
        sheet.cell(row=index, column=1, value=value)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        lookup_delay_seconds=0,
        cache_path=tmp_path / "cache.sqlite",
        pdf_ocr_enabled=False,
    )


def test_extract_service_reads_xlsx(settings: Settings) -> None:
    service = ExtractService(settings)
    numbers = service.extract_from_xlsx(_xlsx_bytes(EXAMPLE))
    assert numbers == [EXAMPLE]


def test_export_service_builds_xlsx(settings: Settings) -> None:
    service = ExportService()
    content = service.build_results_xlsx([{"query": EXAMPLE, "country_code": "BY"}])
    assert content.startswith(b"PK")
