from __future__ import annotations

from cert_parser.domain.models import LookupResult


def lookup_result_to_cache_payload(result: LookupResult) -> dict:
    return {
        "query": result.query,
        "normalized": result.normalized,
        "country_code": result.country_code,
        "url": result.url,
        "valid_from": result.valid_from.isoformat() if result.valid_from else None,
        "valid_until": result.valid_until.isoformat() if result.valid_until else None,
        "status": result.status,
        "status_code": result.status_code,
        "registry_id": result.registry_id,
        "official_number": result.official_number,
        "error": result.error,
        "error_code": result.error_code,
        "cached": result.cached,
    }
