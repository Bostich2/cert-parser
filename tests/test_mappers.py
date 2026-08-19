from __future__ import annotations

from datetime import date

from cert_parser.api.mappers import lookup_result_to_api_dict
from cert_parser.application.serializers import lookup_result_to_cache_payload
from cert_parser.domain.models import LookupResult


def test_lookup_result_to_api_dict_includes_trace() -> None:
    result = LookupResult(
        query="raw",
        normalized="norm",
        country_code="BY",
        pdf_url="/api/certificate-pdf?source=eaeu&registry_id=abc",
        valid_from=date(2024, 1, 15),
        valid_until=date(2029, 1, 14),
        status="Действует",
        cached=True,
        trace=("step one", "step two"),
    )
    payload = lookup_result_to_api_dict(
        result,
        base_url="https://example.test/",
    )
    assert payload["query"] == "raw"
    assert payload["normalized"] == "norm"
    assert payload["country_code"] == "BY"
    assert payload["pdf_url"] == "https://example.test/api/certificate-pdf?source=eaeu&registry_id=abc"
    assert payload["valid_from"] == "2024-01-15"
    assert payload["valid_until"] == "2029-01-14"
    assert payload["status"] == "Действует"
    assert payload["cached"] is True
    assert payload["trace"] == ["step one", "step two"]


def test_lookup_result_to_cache_payload_omits_trace() -> None:
    result = LookupResult(
        query="raw",
        normalized="norm",
        trace=("hidden",),
    )
    payload = lookup_result_to_cache_payload(result)
    assert "trace" not in payload
    assert payload["query"] == "raw"
    assert payload["normalized"] == "norm"
