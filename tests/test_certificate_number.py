from __future__ import annotations

import pytest

from sert_parser.domain.certificate_number import (
    compact_number,
    numbers_match,
    parse_certificate_number,
)
from sert_parser.domain.errors import InvalidNumberError


EXAMPLE = "ЕАЭС BY/112 02.01. ТР018 010.02 00276"


def test_parse_example_belarus_number() -> None:
    parsed = parse_certificate_number(EXAMPLE)
    assert parsed.country_code == "BY"
    assert parsed.normalized == EXAMPLE
    assert "BY112" in parsed.compact
    assert parsed.search_term.startswith("BY/")


def test_parse_collapses_whitespace() -> None:
    parsed = parse_certificate_number("  ЕАЭС   BY/112  02.01.  ТР018  010.02  00276  ")
    assert parsed.country_code == "BY"
    assert parsed.normalized == EXAMPLE


def test_parse_tc_prefix() -> None:
    parsed = parse_certificate_number("ТС BY/112 10.06. 002.03 00276")
    assert parsed.country_code == "BY"
    assert parsed.search_term.startswith("BY/")


def test_parse_declaration_like_prefix_still_extracts_country() -> None:
    parsed = parse_certificate_number("ЕАЭС Д BY/112 11.01. ТР005 085.01 00276")
    assert parsed.country_code == "BY"


def test_parse_without_union_prefix() -> None:
    parsed = parse_certificate_number("BY/112 02.01. ТР018 010.02 00276")
    assert parsed.country_code == "BY"


def test_parse_russian_number() -> None:
    parsed = parse_certificate_number("ЕАЭС RU C-CN.АБ12.В.00001/24")
    assert parsed.country_code == "RU"


def test_parse_kazakhstan_number_with_spaces() -> None:
    parsed = parse_certificate_number("ЕАЭС KZ 1100317.05.01.05103")
    assert parsed.country_code == "KZ"
    assert parsed.search_term.startswith("KZ")


def test_parse_kyrgyzstan_agency_number_without_space() -> None:
    parsed = parse_certificate_number("ЕАЭС KG417/016.ru.02.04561")
    assert parsed.country_code == "KG"
    assert parsed.normalized == "ЕАЭС KG417/016.ru.02.04561"


def test_parse_kyrgyzstan_declaration_number() -> None:
    parsed = parse_certificate_number("ЕАЭС KG417/18.д.0000338")
    assert parsed.country_code == "KG"


def test_kg_number_with_ru_segment_is_not_russia() -> None:
    parsed = parse_certificate_number("KG417/016.ru.02.04561")
    assert parsed.country_code == "KG"


def test_latin_and_cyrillic_certificate_mark_match() -> None:
    latin = "ЕАЭС RU C-CN.СБ21.А.00039/19"
    cyrillic = "ЕАЭС RU С-CN.СБ21.А.00039/19"
    assert parse_certificate_number(latin).country_code == "RU"
    assert numbers_match(latin, cyrillic)
    assert compact_number(latin) == compact_number(cyrillic)


def test_extract_candidates_from_mixed_text() -> None:
    from sert_parser.domain.certificate_number import extract_certificate_candidates

    text = (
        "Документ ЕАЭС BY/112 02.01. ТР018 010.02 00276 выдан. "
        "Также ЕАЭС RU С-CN.СБ21.А.00039/19 и ЕАЭС KZ 1100317.05.01.05103."
    )
    found = extract_certificate_candidates(text)
    assert len(found) == 3
    countries = {parse_certificate_number(item).country_code for item in found}
    assert countries == {"BY", "RU", "KZ"}


def test_extract_ocr_garbled_belarus_header() -> None:
    from sert_parser.domain.certificate_number import extract_certificate_candidates

    text = "Ng EADC BY/112 02.01. TP018 010.02 00276"
    found = extract_certificate_candidates(text)
    assert found == ["ЕАЭС BY/112 02.01. ТР018 010.02 00276"]
    assert parse_certificate_number(found[0]).country_code == "BY"


def test_extract_ocr_mixed_script_eaeu_prefix_no_space_after_numero() -> None:
    """№ is often glued to EAЭC in RapidOCR eslav output."""
    from sert_parser.domain.certificate_number import extract_certificate_candidates

    text = "СООТВЕТСТВИЯ №EAЭC BY/112 02.01. TP018 010.02 00276"
    found = extract_certificate_candidates(text)
    assert found == ["ЕАЭС BY/112 02.01. ТР018 010.02 00276"]


def test_extract_does_not_keep_stray_c_from_mixed_eaeu() -> None:
    from sert_parser.domain.certificate_number import extract_certificate_candidates

    text = "EAC СЕРТИФИКАТ №EAЭC BY/112 02.01. TP018 010.02 00276"
    found = extract_certificate_candidates(text)
    assert found == ["ЕАЭС BY/112 02.01. ТР018 010.02 00276"]
    assert not any(item.startswith("C BY") for item in found)


def test_extract_ocr_ea3c_from_scanned_header() -> None:
    from sert_parser.domain.certificate_number import extract_certificate_candidates

    text = (
        "3 EAC EOT N EA3C BY/112 02.01. TP018 010.02 00276 "
        "CeBY N0061370 i » o , ; , 204, 213809"
    )
    found = extract_certificate_candidates(text)
    assert found
    assert parse_certificate_number(found[0]).country_code == "BY"
    assert "BY/112" in found[0]
    assert found[0].endswith("00276")
    assert "ЕАЭС" in found[0]


def test_parse_eac_before_kz_normalizes_to_eaeu() -> None:
    parsed = parse_certificate_number("EAC KZ 7500533.01.01.06080")
    assert parsed.normalized == "ЕАЭС KZ 7500533.01.01.06080"
    assert parsed.country_code == "KZ"


def test_extract_dedupes_kz_ocr_variants() -> None:
    from sert_parser.domain.certificate_number import extract_certificate_candidates

    text = (
        "EAC KZ7500533.01.01.06080 EA9C "
        "KZ 7500533.01.01.06080 "
        "ЕАЭС KZ 7500533.01.01.06080"
    )
    found = extract_certificate_candidates(text)
    assert found == ["ЕАЭС KZ 7500533.01.01.06080"]


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "сертификат без кода страны", "12345"],
)
def test_parse_rejects_invalid_numbers(raw: str) -> None:
    with pytest.raises(InvalidNumberError):
        parse_certificate_number(raw)


def test_numbers_match_ignores_spaces_and_punctuation() -> None:
    assert numbers_match(EXAMPLE, "ЕАЭС BY/112 02.01. ТР018 010.02 00276")
    assert numbers_match(EXAMPLE, "ЕАЭС  BY/112 02.01.ТР018 010.02 00276")
    assert compact_number(EXAMPLE).endswith("00276")
