from __future__ import annotations

import pytest

from cert_parser.domain.certificate_number import compact_number, parse_certificate_number
from cert_parser.domain.errors import AmbiguousMatchError, CertificateNotFoundError
from cert_parser.infrastructure.registries.matching import is_safe_contained_match, pick_matching_item, record_from_light_item

EXAMPLE = "ЕАЭС BY/112 02.01. ТР018 010.02 00276"


def _item(doc_id: str, registry_id: int = 3345084, valid_until: str = "2029-05-29") -> dict:
    return {
        "certdecltr_id": registry_id,
        "DocId": doc_id,
        "certdecltr_DocStartDate": "2024-05-29",
        "certdecltr_DocValidityDate": valid_until,
        "certdecltr_DocStatusDetails": {"DocStatusCode": "01", "EndDate": "29.05.2029"},
    }


def test_pick_exact_match_among_similar_numbers() -> None:
    number = parse_certificate_number(EXAMPLE)
    items = [
        _item("ЕАЭС BY/112 02.02. ТР020 030.01 00276", 1),
        _item(EXAMPLE, 3345084),
    ]
    match = pick_matching_item(items, number)
    assert match["certdecltr_id"] == 3345084


def test_pick_match_without_union_prefix() -> None:
    number = parse_certificate_number("BY/112 02.01. ТР018 010.02 00276")
    match = pick_matching_item([_item(EXAMPLE)], number)
    assert match["DocId"] == EXAMPLE


def test_short_query_does_not_use_contained_match() -> None:
    from cert_parser.domain.models import CertificateNumber

    number = CertificateNumber(
        raw="00276",
        normalized="00276",
        compact="00276",
        country_code="BY",
        search_term="00276",
    )
    with pytest.raises(CertificateNotFoundError):
        pick_matching_item([_item(EXAMPLE)], number)


def test_ambiguous_when_several_safe_substring_hits() -> None:
    number = parse_certificate_number(EXAMPLE)
    with pytest.raises(AmbiguousMatchError):
        pick_matching_item(
            [
                _item(f"{EXAMPLE}-A", 1),
                _item(f"{EXAMPLE}-B", 2),
            ],
            number,
        )


def test_is_safe_contained_match_requires_length_and_ratio() -> None:
    assert is_safe_contained_match("00276", "BY1120201TR0180100200276", "00276") is False
    long_query = "BY1120201TR0180100200276"
    assert is_safe_contained_match(
        long_query,
        long_query + "EXTRAEXTRAEXTRA",
        long_query,
    ) is False
    assert is_safe_contained_match(long_query, long_query, long_query) is True


def test_record_builds_public_card_url() -> None:
    record = record_from_light_item(_item(EXAMPLE), "https://tsouz.belgiss.by")
    assert record.url == "https://tsouz.belgiss.by/#!/tsouz/certifs/3345084/view"
    assert str(record.valid_from) == "2024-05-29"
    assert str(record.valid_until) == "2029-05-29"
    assert record.status_label == "действует"
