from __future__ import annotations

import fitz

from cert_parser.config import Settings
from cert_parser.domain.certificate_number import parse_certificate_number
from cert_parser.infrastructure.pdf import extract_numbers_from_pdf

EXAMPLE = "ЕАЭС BY/112 02.01. ТР018 010.02 00276"


def _pdf_with_text(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_htmlbox(fitz.Rect(50, 50, 550, 250), f"<p>{text}</p>")
    payload = document.tobytes()
    document.close()
    return payload


def test_extract_numbers_from_text_layer() -> None:
    payload = _pdf_with_text(f"Регистрационный номер {EXAMPLE}")
    found = extract_numbers_from_pdf(payload, Settings(pdf_ocr_enabled=False))
    assert found == [EXAMPLE]
    assert parse_certificate_number(found[0]).country_code == "BY"


def test_extract_numbers_empty_when_no_certificate_text() -> None:
    payload = _pdf_with_text("Накладная без сертификата")
    assert extract_numbers_from_pdf(payload, Settings(pdf_ocr_enabled=False)) == []


def test_texts_from_new_and_legacy_ocr_results() -> None:
    from types import SimpleNamespace

    from cert_parser.infrastructure.pdf import _texts_from_ocr_result

    modern = SimpleNamespace(txts=("ЕАЭС BY/112", "02.01"))
    assert "ЕАЭС BY/112" in _texts_from_ocr_result(modern)
    legacy = ([[0, "ЕАЭС RU С-CN.СБ21.А.00039/19", 0.9]], 0.1)
    assert "ЕАЭС RU" in _texts_from_ocr_result(legacy)


def test_ocr_stops_after_first_page_when_number_found(monkeypatch) -> None:
    from cert_parser.infrastructure import pdf as pdf_module

    scanned: list[int] = []

    def fake_ocr_page(document, index, page_count, langs, chunks) -> bool:
        scanned.append(index)
        if index == 0:
            chunks.append(f"ЕАЭС KZ 7500533.01.01.06080")
            return True
        return False

    monkeypatch.setattr(pdf_module, "_ocr_page", fake_ocr_page)
    document = fitz.open()
    for _ in range(4):
        document.new_page()
    try:
        text = pdf_module._ocr_text(document, 5, ("eslav", "latin"))
    finally:
        document.close()

    assert scanned == [0]
    assert "7500533.01.01.06080" in text


def test_ocr_falls_back_to_next_pages_when_first_page_empty(monkeypatch) -> None:
    from cert_parser.infrastructure import pdf as pdf_module

    scanned: list[int] = []

    def fake_ocr_page(document, index, page_count, langs, chunks) -> bool:
        scanned.append(index)
        if index == 1:
            chunks.append(EXAMPLE)
            return True
        return False

    monkeypatch.setattr(pdf_module, "_ocr_page", fake_ocr_page)
    document = fitz.open()
    for _ in range(4):
        document.new_page()
    try:
        text = pdf_module._ocr_text(document, 5, ("eslav", "latin"))
    finally:
        document.close()

    assert scanned == [0, 1]
    assert EXAMPLE in text
