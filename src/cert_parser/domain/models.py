from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

_RU_MONTH_PREFIXES = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "май": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}
_RU_TEXT_DATE_RE = re.compile(
    r"(\d{1,2})\s+([a-zа-яё]+)\s+(\d{4})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CertificateNumber:
    raw: str
    normalized: str
    compact: str
    country_code: str
    search_term: str


@dataclass(frozen=True)
class RegistryRecord:
    url: str
    valid_from: date | None
    valid_until: date | None
    status_code: str | None
    status_label: str
    registry_id: str
    official_number: str
    pdf_url: str | None = None


@dataclass(frozen=True)
class LookupResult:
    query: str
    normalized: str | None = None
    country_code: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    status: str | None = None
    status_code: str | None = None
    registry_id: str | None = None
    official_number: str | None = None
    error: str | None = None
    error_code: str | None = None
    cached: bool = False
    trace: tuple[str, ...] = ()


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    russian = _parse_russian_text_date(text)
    if russian is not None:
        return russian
    candidates = (
        (text[:10], "%Y-%m-%d"),
        (text[:10], "%d.%m.%Y"),
        (text[:8], "%d.%m.%y"),
        (text[:19].rstrip("Z"), "%Y-%m-%dT%H:%M:%S"),
        (digits[:8], "%Y%m%d"),
    )
    if len(digits) < 8:
        candidates = candidates[:-1]
    for sample, fmt in candidates:
        try:
            return datetime.strptime(sample, fmt).date()
        except ValueError:
            continue
    return None


def _parse_russian_text_date(value: str) -> date | None:
    match = _RU_TEXT_DATE_RE.search(value.strip())
    if match is None:
        return None
    day = int(match.group(1))
    month_token = match.group(2).lower().replace("ё", "е")
    year = int(match.group(3))
    month = next(
        (number for prefix, number in _RU_MONTH_PREFIXES.items() if month_token.startswith(prefix)),
        None,
    )
    if month is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None
