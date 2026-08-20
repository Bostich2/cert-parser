from __future__ import annotations

from cert_parser.domain.product_query import parse_product_search_query


def test_normalizes_whitespace_yo_and_punctuation() -> None:
    query = parse_product_search_query('  «кабель»  силового  назначения  ')
    assert query is not None
    assert query.raw == '  «кабель»  силового  назначения  '
    assert query.normalized == "кабель силового назначения"
    assert query.tokens == ("кабель", "силового", "назначения")


def test_drops_short_tokens() -> None:
    query = parse_product_search_query("кабель от 12 мм")
    assert query is not None
    assert "от" not in query.tokens
    assert "мм" not in query.tokens
    assert query.tokens == ("кабель",)


def test_stems_drop_one_or_two_letters() -> None:
    query = parse_product_search_query("насос погружной кабель")
    assert query is not None
    assert "насос" in query.tokens
    assert "погружной" in query.tokens
    assert "кабель" in query.tokens
    assert "насо" in query.stems
    assert "погружн" in query.stems
    assert "кабе" in query.stems


def test_too_short_after_trim() -> None:
    assert parse_product_search_query("  аб  ") is None
    assert parse_product_search_query("xyz") is None
    assert parse_product_search_query("abcd") is not None


def test_punctuation_only_is_too_short() -> None:
    assert parse_product_search_query('""""') is None
