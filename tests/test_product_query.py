from __future__ import annotations

from cert_parser.domain.product_query import (
    contiguous_search_terms,
    parse_product_search_query,
    registry_search_steps,
)


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


def test_long_marketplace_title_skips_phrase() -> None:
    query = parse_product_search_query(
        "Cordiant Comfort 2 SUV Шины летние 235/65 R17 108H"
    )
    assert query is not None
    steps = registry_search_steps(query)
    assert steps[0][1] == "tokens"
    assert steps[0][0] == ("Cordiant", "Comfort", "SUV")
    assert steps[1][1] == "first"
    assert steps[1][0] == ("Cordiant",)
    assert all(label != "phrase" for _, label in steps)
    assert contiguous_search_terms(query) == ["Cordiant Comfort", "Cordiant"]


def test_short_query_keeps_phrase_then_tokens() -> None:
    query = parse_product_search_query("насос погружной")
    assert query is not None
    steps = registry_search_steps(query)
    assert steps[0] == ((query.normalized,), "phrase")
    assert steps[1][1] == "tokens"
    assert contiguous_search_terms(query) == [query.normalized, "насос"]
