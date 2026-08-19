from __future__ import annotations

from cert_parser.application.serializers import lookup_result_to_cache_payload
from cert_parser.domain.models import LookupResult
from cert_parser.api.security import safe_http_url
from cert_parser.infrastructure.registries.pdf_urls import absolutize_url


def lookup_result_to_api_dict(result: LookupResult, *, base_url: str = "") -> dict:
    payload = lookup_result_to_cache_payload(result)
    payload["url"] = safe_http_url(payload.get("url"))
    pdf_url = payload.get("pdf_url")
    if pdf_url and base_url:
        pdf_url = absolutize_url(str(pdf_url), base_url)
    payload["pdf_url"] = safe_http_url(pdf_url if isinstance(pdf_url, str) else None)
    return {
        **payload,
        "trace": list(result.trace),
    }
