from __future__ import annotations

from datetime import date
from typing import Any

from cert_parser.domain.certificate_number import compact_number, numbers_match
from cert_parser.domain.errors import AmbiguousMatchError, CertificateNotFoundError
from cert_parser.domain.models import CertificateNumber, RegistryRecord, parse_iso_date
from cert_parser.infrastructure.registries.eaeu_pdf import build_eaeu_pdf_proxy_url

STATUS_LABELS = {
    "01": "действует",
    "02": "приостановлен",
    "03": "прекращен",
    "04": "продлен",
    "05": "возобновлен",
    "09": "архивный",
}

_MIN_CONTAINED_QUERY_LEN = 12
_MIN_CONTAINED_RATIO = 0.75


def is_safe_contained_match(
    query_compact: str,
    doc_compact: str,
    search_compact: str,
) -> bool:
    if not doc_compact:
        return False
    for needle in (query_compact, search_compact):
        if not needle or needle not in doc_compact:
            continue
        if len(needle) < _MIN_CONTAINED_QUERY_LEN:
            continue
        if len(needle) / len(doc_compact) < _MIN_CONTAINED_RATIO:
            continue
        return True
    return False


def pick_matching_item(items: list[dict[str, Any]], number: CertificateNumber) -> dict[str, Any]:
    exact = [item for item in items if _item_matches_exactly(item, number)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousMatchError(number.normalized)

    contained = [item for item in items if _query_contained_in_item(item, number)]
    if len(contained) == 1:
        return contained[0]
    if len(contained) > 1:
        raise AmbiguousMatchError(number.normalized)
    raise CertificateNotFoundError(number.normalized)


def pick_matching_odata_item(items: list[dict[str, Any]], number: CertificateNumber) -> dict[str, Any]:
    exact = [item for item in items if _odata_item_matches_exactly(item, number)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousMatchError(number.normalized)

    contained = [item for item in items if _query_contained_in_odata_item(item, number)]
    if len(contained) == 1:
        return contained[0]
    if len(contained) > 1:
        raise AmbiguousMatchError(number.normalized)
    raise CertificateNotFoundError(number.normalized)


def record_from_odata_item(item: dict[str, Any], view_base_url: str) -> RegistryRecord:
    registry_id = str(item["Id"])
    status_details = item.get("docStatusDetails") or {}
    status_code = status_details.get("docStatusCode")
    status_code = str(status_code) if status_code else None
    official_number = str(item.get("docId") or "")
    return RegistryRecord(
        url=f"{view_base_url.rstrip('/')}/{registry_id}",
        valid_from=parse_iso_date(item.get("docStartDate")),
        valid_until=parse_iso_date(item.get("docValidityDate")),
        status_code=status_code,
        status_label=STATUS_LABELS.get(status_code or "", status_code or "не указан"),
        registry_id=registry_id,
        official_number=official_number,
        pdf_url=build_eaeu_pdf_proxy_url(registry_id),
    )


def record_from_light_item(item: dict[str, Any], public_base_url: str) -> RegistryRecord:
    registry_id = str(item["certdecltr_id"])
    status_details = item.get("certdecltr_DocStatusDetails") or {}
    status_code = status_details.get("DocStatusCode") or item.get("DocStatusCode")
    status_code = str(status_code) if status_code else None
    valid_from = _extract_valid_from(item, status_details)
    valid_until = _extract_valid_until(item, status_details)
    official_number = str(item.get("DocId") or "")
    return RegistryRecord(
        url=f"{public_base_url.rstrip('/')}/#!/tsouz/certifs/{registry_id}/view",
        valid_from=valid_from,
        valid_until=valid_until,
        status_code=status_code,
        status_label=STATUS_LABELS.get(status_code or "", status_code or "не указан"),
        registry_id=registry_id,
        official_number=official_number,
    )


def _item_matches_exactly(item: dict[str, Any], number: CertificateNumber) -> bool:
    doc_id = str(item.get("DocId") or "")
    return numbers_match(doc_id, number.normalized) or numbers_match(doc_id, number.search_term)


def _odata_item_matches_exactly(item: dict[str, Any], number: CertificateNumber) -> bool:
    doc_id = str(item.get("docId") or "")
    return (
        numbers_match(doc_id, number.normalized)
        or numbers_match(doc_id, number.search_term)
        or numbers_match(doc_id, f"ЕАЭС {number.search_term}")
    )


def _query_contained_in_odata_item(item: dict[str, Any], number: CertificateNumber) -> bool:
    doc_compact = compact_number(str(item.get("docId") or ""))
    return is_safe_contained_match(
        number.compact,
        doc_compact,
        compact_number(number.search_term),
    )


def _query_contained_in_item(item: dict[str, Any], number: CertificateNumber) -> bool:
    doc_compact = compact_number(str(item.get("DocId") or ""))
    return is_safe_contained_match(
        number.compact,
        doc_compact,
        compact_number(number.search_term),
    )


def _extract_valid_from(item: dict[str, Any], status_details: dict[str, Any]) -> date | None:
    for value in (
        item.get("certdecltr_DocStartDate"),
        item.get("DocStartDate"),
        status_details.get("StartDate"),
        item.get("certdecltr_DocIssueDate"),
        item.get("DocIssueDate"),
    ):
        parsed = parse_iso_date(value if value is None else str(value))
        if parsed is not None:
            return parsed
    return None


def _extract_valid_until(item: dict[str, Any], status_details: dict[str, Any]) -> date | None:
    for value in (
        item.get("certdecltr_DocValidityDate"),
        status_details.get("EndDate"),
        item.get("DocValidityDate"),
    ):
        parsed = parse_iso_date(value if value is None else str(value))
        if parsed is not None:
            return parsed
    return None
