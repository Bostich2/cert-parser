from __future__ import annotations

from sert_parser.application.serializers import lookup_result_to_cache_payload
from sert_parser.domain.models import LookupResult


def lookup_result_to_api_dict(result: LookupResult) -> dict:
    return {
        **lookup_result_to_cache_payload(result),
        "trace": list(result.trace),
    }
