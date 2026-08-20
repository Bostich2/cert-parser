from __future__ import annotations

from cert_parser.application.serializers import lookup_result_to_cache_payload
from cert_parser.domain.models import LookupResult, ProductSearchHit
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


def product_search_hit_to_api_dict(hit: ProductSearchHit, *, base_url: str = "") -> dict:
    pdf_url = hit.pdf_url
    if pdf_url and base_url:
        pdf_url = absolutize_url(str(pdf_url), base_url)
    return {
        "query": hit.query,
        "official_number": hit.official_number,
        "country_code": hit.country_code,
        "doc_kind": hit.doc_kind,
        "product_name": hit.product_name,
        "url": safe_http_url(hit.url),
        "pdf_url": safe_http_url(pdf_url if isinstance(pdf_url, str) else None),
        "valid_from": hit.valid_from.isoformat() if hit.valid_from else None,
        "valid_until": hit.valid_until.isoformat() if hit.valid_until else None,
        "status": hit.status,
        "status_code": hit.status_code,
        "registry_id": hit.registry_id,
        "source": hit.source,
        "error": hit.error,
        "error_code": hit.error_code,
        "trace": list(hit.trace),
    }
