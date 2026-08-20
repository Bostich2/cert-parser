from __future__ import annotations

from datetime import date

from cert_parser.domain.product_query import parse_product_search_query
from cert_parser.infrastructure.registries.eaeu_odata import (
    build_product_search_filter,
    hit_from_odata_item,
    odata_escape,
    product_filter_cascade,
    product_name_any_filter,
)

VIEW = "https://tech.eaeunion.org/tech/registers/35-1/ru/registryList/conformityDocs/view"


def test_odata_escape_doubles_quotes() -> None:
    assert odata_escape("O'Reilly") == "O''Reilly"


def test_product_name_any_filter_phrase_and_tokens() -> None:
    phrase = product_name_any_filter(("кабель силовой",))
    assert phrase == (
        "technicalRegulationObjectDetails/productDetails/any("
        "p: contains(p/productName,'кабель силовой'))"
    )
    tokens = product_name_any_filter(("кабель", "силовой"))
    assert "contains(p/productName,'кабель') and contains(p/productName,'силовой')" in tokens


def test_country_filters_ru_and_other() -> None:
    ru = build_product_search_filter(russia_only=True, needles=("насос",))
    other = build_product_search_filter(russia_only=False, needles=("насос",))
    assert ru.startswith("unifiedCountryCode/value eq 'RU' and ")
    assert other.startswith("unifiedCountryCode/value ne 'RU' and ")


def test_cascade_phrase_then_tokens_then_stems() -> None:
    query = parse_product_search_query("насос погружной")
    assert query is not None
    steps = product_filter_cascade(query)
    assert steps[0][1] == "phrase"
    assert steps[0][0] == (query.normalized,)
    assert steps[1][1] == "tokens"
    assert steps[1][0] == query.tokens
    assert steps[2][1] == "stems"
    assert steps[2][0] == query.stems


def test_hit_from_odata_item_maps_fields() -> None:
    item = {
        "docId": "ЕАЭС RU С-CN.АА01.В.00001/24",
        "docStartDate": "2024-01-15T00:00:00+03:00",
        "docValidityDate": "2029-01-14T00:00:00+03:00",
        "Id": "odata-id-1",
        "unifiedCountryCode": {"value": "RU"},
        "docStatusDetails": {"docStatusCode": "01"},
        "conformityDocKindName": "Сертификат соответствия",
        "technicalRegulationObjectDetails": {
            "productDetails": [{"productName": "Насос погружной"}]
        },
    }
    hit = hit_from_odata_item(item, "насос погружной", VIEW, source="eaeu_ru")
    assert hit.official_number == "ЕАЭС RU С-CN.АА01.В.00001/24"
    assert hit.country_code == "RU"
    assert hit.doc_kind == "certificate"
    assert hit.product_name == "Насос погружной"
    assert hit.url.endswith("/odata-id-1")
    assert hit.pdf_url and "source=eaeu" in hit.pdf_url
    assert hit.valid_from == date(2024, 1, 15)
    assert hit.valid_until == date(2029, 1, 14)
    assert hit.status_code == "01"
    assert hit.source == "eaeu_ru"


def test_hit_from_odata_item_declaration_kind() -> None:
    item = {
        "docId": "ЕАЭС N RU Д-DE.АА01.В.00002/24",
        "Id": "odata-id-2",
        "unifiedCountryCode": {"value": "BY"},
        "docStatusDetails": {"docStatusCode": "01"},
        "conformityDocKindName": "Декларация о соответствии",
        "technicalRegulationObjectDetails": {
            "productDetails": [{"productName": "Кабель"}]
        },
    }
    hit = hit_from_odata_item(item, "кабель", VIEW, source="eaeu_other")
    assert hit.doc_kind == "declaration"
    assert hit.country_code == "BY"
    assert hit.source == "eaeu_other"
