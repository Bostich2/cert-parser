from __future__ import annotations

from datetime import date
from typing import Any

from cert_parser.domain.errors import SourceUnavailableError
from cert_parser.domain.models import ProductSearchQuery

FALLBACK_ACTING_STATUS_ID = 6
_TIMEOUT_HINT = "вовремя"

# Official TR codes (not FSA internal ids). Matched against identifier names.
_TR_KEYWORD_CODES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("шин", "покрышк"), "018/2011"),
    (("игруш",), "008/2011"),
    (("кабел", "провод"), "004/2011"),
    (("светильник", "ламп"), "004/2011"),
    (("одежд", "трикотаж", "белье", "обув"), "017/2011"),
    (("мебел",), "025/2012"),
    (("космет", "парфюм"), "009/2011"),
)


def id_name_map(block: Any) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if isinstance(block, dict):
        for key, value in block.items():
            if isinstance(value, dict) and value.get("name"):
                mapping[str(key)] = str(value["name"])
            elif isinstance(value, str):
                mapping[str(key)] = value
    elif isinstance(block, list):
        for item in block:
            if isinstance(item, dict) and item.get("id") is not None:
                mapping[str(item["id"])] = str(item.get("name") or item["id"])
    return mapping


def acting_status_ids(identifiers: dict[str, Any] | None) -> list[int]:
    names = id_name_map((identifiers or {}).get("status"))
    ids: list[int] = []
    for key, name in names.items():
        parsed = _as_int(key)
        if _is_acting_status(name) and parsed is not None:
            ids.append(parsed)
    return ids or [FALLBACK_ACTING_STATUS_ID]


def tech_reg_ids_for_query(
    query: ProductSearchQuery,
    identifiers: dict[str, Any] | None,
) -> list[int]:
    codes = tr_codes_for_query(query)
    if not codes:
        return []
    names = id_name_map(_tech_reg_block(identifiers or {}))
    ids: list[int] = []
    for key, name in names.items():
        folded = _fold(name)
        if any(code.lower() in folded for code in codes):
            parsed = _as_int(key)
            if parsed is not None and parsed not in ids:
                ids.append(parsed)
    return ids


def tr_codes_for_query(query: ProductSearchQuery) -> tuple[str, ...]:
    text = _fold(f"{query.normalized} {' '.join(query.tokens)}")
    found: list[str] = []
    for stems, code in _TR_KEYWORD_CODES:
        if any(stem in text for stem in stems) and code not in found:
            found.append(code)
    return tuple(found)


def active_end_min(as_of: date | None = None) -> str:
    day = as_of or date.today()
    return f"{day.isoformat()}T00:00:00.000Z"


def is_fsa_timeout(exc: BaseException) -> bool:
    return isinstance(exc, SourceUnavailableError) and _TIMEOUT_HINT in str(exc)


def _tech_reg_block(identifiers: dict[str, Any]) -> Any:
    for key, value in identifiers.items():
        lowered = str(key).lower()
        if "tech" in lowered and "reg" in lowered:
            return value
        if "регламент" in lowered:
            return value
    return identifiers.get("techReg")


def _is_acting_status(name: str) -> bool:
    folded = _fold(name)
    return folded == "действует" or folded.startswith("действует")


def _fold(value: str) -> str:
    return value.lower().replace("ё", "е")


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
