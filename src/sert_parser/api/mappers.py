from __future__ import annotations

from sert_parser.application.serializers import lookup_result_to_cache_payload
from sert_parser.domain.models import LookupResult
from sert_parser.api.security import safe_http_url


def lookup_result_to_api_dict(result: LookupResult) -> dict:
    payload = lookup_result_to_cache_payload(result)
    payload["url"] = safe_http_url(payload.get("url"))
    return {
        **payload,
        "trace": list(result.trace),
    }
