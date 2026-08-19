from __future__ import annotations

from sert_parser.domain.models import parse_iso_date


def test_parse_iso_date_russian_month_name() -> None:
    assert str(parse_iso_date("1 июль 2026")) == "2026-07-01"
    assert str(parse_iso_date("30 июнь 2031")) == "2031-06-30"
    assert str(parse_iso_date("17 июнь 2025")) == "2025-06-17"
