from __future__ import annotations

import html
import re
from dataclasses import dataclass

from cert_parser.domain.models import parse_iso_date

_RESULT_TABLE_RE = re.compile(
    r'<table[^>]*\bid=["\']reportTable["\'][^>]*>(.*?)</table>',
    re.IGNORECASE | re.DOTALL,
)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(
    r"<td[^>]*\bclass=['\"]tb_td['\"][^>]*>(.*?)</td>",
    re.IGNORECASE | re.DOTALL,
)
_DOC_LINK_RE = re.compile(
    r'href=["\'](/Doc/[^"\']+)["\']',
    re.IGNORECASE,
)
_NOT_FOUND_RE = re.compile(r"не\s+найдены\s+документы", re.IGNORECASE)
_STATUS_CODES = {
    "действует": "01",
    "продлен": "04",
    "продлена": "04",
    "приостановлен": "02",
    "приостановлена": "02",
    "возобновлен": "05",
    "возобновлена": "05",
    "прекращен": "03",
    "прекращена": "03",
    "архивный": "09",
    "архивная": "09",
}


@dataclass(frozen=True)
class SwisRow:
    official_number: str
    status_raw: str
    valid_from_raw: str
    valid_until_raw: str
    doc_path: str
    registry_kind: str


def has_result_rows(payload: str) -> bool:
    return bool(parse_result_rows(payload))


def is_not_found(payload: str) -> bool:
    return bool(_NOT_FOUND_RE.search(payload or ""))


def parse_result_rows(payload: str, registry_kind: str = "certificate") -> list[SwisRow]:
    table_match = _RESULT_TABLE_RE.search(payload or "")
    if table_match is None:
        return []
    rows: list[SwisRow] = []
    for row_html in _ROW_RE.findall(table_match.group(1)):
        if "certificatesReport-header" in row_html:
            continue
        cells = [_clean_cell(value) for value in _CELL_RE.findall(row_html)]
        if len(cells) < 9:
            continue
        doc_match = _DOC_LINK_RE.search(row_html)
        if doc_match is None:
            continue
        rows.append(
            SwisRow(
                official_number=cells[1],
                status_raw=cells[2],
                valid_from_raw=cells[7],
                valid_until_raw=cells[8],
                doc_path=doc_match.group(1),
                registry_kind=registry_kind,
            )
        )
    return rows


def row_valid_from(row: SwisRow):
    return parse_iso_date(row.valid_from_raw)


def row_valid_until(row: SwisRow):
    return parse_iso_date(row.valid_until_raw)


def status_label(status_raw: str) -> tuple[str | None, str]:
    normalized = (status_raw or "").strip().lower().replace("ё", "е")
    if not normalized:
        return None, "не указан"
    code = _STATUS_CODES.get(normalized)
    if code is not None:
        return code, status_raw.strip()
    for prefix, mapped in _STATUS_CODES.items():
        if normalized.startswith(prefix):
            return mapped, status_raw.strip()
    return None, status_raw.strip()


def _clean_cell(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(re.sub(r"\s+", " ", without_tags)).strip()
