from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from cert_parser.domain.models import parse_iso_date

_VIEWSTATE_RE = re.compile(
    r'name=["\']javax\.faces\.ViewState["\'][^>]*value=["\']([^"\']+)["\']'
    r'|value=["\']([^"\']+)["\'][^>]*name=["\']javax\.faces\.ViewState["\']',
    re.IGNORECASE,
)
_FILTER_INPUT_RE = re.compile(
    r'<input[^>]*name=["\']([^"\']*filter[^"\']*)["\'][^>]*>',
    re.IGNORECASE,
)
_FORM_ID_RE = re.compile(
    r'<form[^>]*(?:id|name)=["\']([^"\']*ktrmListForm[^"\']*)["\']',
    re.IGNORECASE,
)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_NUMBER_HEADER_HINTS = ("тіркеу", "регистрац", "номері", "nөмір")
_VALID_FROM_HINTS = ("бастап", "valid from")
_VALID_TO_HINTS = ("дейін", "valid to")
_STATUS_HINTS = ("мәртебе", "статус", "status")
_TYPE_HINTS = ("тип", "типі", "вид")
_DECLARATION_HINTS = ("декларац",)
_STATUS_LABELS = {
    "ISSUED": "действует",
    "CANCELED": "прекращен",
    "CANCELLED": "прекращен",
    "SUSPENDED": "приостановлен",
    "EXTENDED": "продлен",
    "RENEWED": "возобновлен",
}


@dataclass(frozen=True)
class EoknoSearchForm:
    view_state: str
    form_id: str
    number_filter_name: str


@dataclass(frozen=True)
class EoknoRow:
    registry_id: str
    official_number: str
    valid_from_raw: str
    valid_until_raw: str
    status_raw: str
    doc_type: str


def extract_search_form(html: str) -> EoknoSearchForm | None:
    view_state = _first_group(_VIEWSTATE_RE.search(html or ""))
    if not view_state:
        return None
    form_match = _FORM_ID_RE.search(html or "")
    form_id = form_match.group(1) if form_match else "ktrmListForm"
    filter_name = _find_number_filter_name(html or "")
    if not filter_name:
        return None
    return EoknoSearchForm(view_state=view_state, form_id=form_id, number_filter_name=filter_name)


def parse_result_rows(payload: str) -> list[EoknoRow]:
    html = _unwrap_partial(payload)
    return _TableExtractor().extract(html)


def is_certificate_row(row: EoknoRow) -> bool:
    doc_type = row.doc_type.lower()
    if any(hint in doc_type for hint in _DECLARATION_HINTS):
        return False
    number = row.official_number.upper()
    if re.search(r"ЕАЭС\s+Д\s+KZ", number) or re.search(r"\bД\s+KZ\b", number):
        return False
    return True


def status_label(raw: str) -> tuple[str | None, str]:
    text = (raw or "").strip()
    if not text:
        return None, "не указан"
    key = text.upper()
    if key in _STATUS_LABELS:
        return key, _STATUS_LABELS[key]
    lowered = text.lower()
    if "берілді" in lowered or "выдан" in lowered or "действ" in lowered:
        return "ISSUED", "действует"
    if "жарамсыз" in lowered or "аннул" in lowered or "прекращ" in lowered:
        return "CANCELED", "прекращен"
    if "тоқтатыл" in lowered or "приостанов" in lowered:
        return "SUSPENDED", "приостановлен"
    return text, text


def row_valid_from(row: EoknoRow):
    return parse_iso_date(row.valid_from_raw)


def row_valid_until(row: EoknoRow):
    return parse_iso_date(row.valid_until_raw)


def _find_number_filter_name(html: str) -> str | None:
    lowered = html.lower()
    for match in _FILTER_INPUT_RE.finditer(html):
        name = match.group(1)
        start = max(0, match.start() - 400)
        context = lowered[start:match.end()]
        if any(hint in context for hint in _NUMBER_HEADER_HINTS):
            return name
    filters = _FILTER_INPUT_RE.findall(html)
    return filters[0] if filters else None


def _unwrap_partial(payload: str) -> str:
    chunks = _CDATA_RE.findall(payload or "")
    if chunks:
        return "\n".join(chunks)
    return payload or ""


def _first_group(match: re.Match[str] | None) -> str | None:
    if match is None:
        return None
    return match.group(1) or match.group(2)


class _TableExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_thead = False
        self._in_tbody = False
        self._in_th = False
        self._in_td = False
        self._in_tr = False
        self._th_text: list[str] = []
        self._current_th: list[str] = []
        self._current_cells: list[str] = []
        self._current_cell: list[str] = []
        self._current_id = ""
        self.headers: list[str] = []
        self.rows: list[EoknoRow] = []

    def extract(self, html: str) -> list[EoknoRow]:
        self.feed(html)
        self.close()
        return self.rows

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "thead":
            self._in_thead = True
        elif tag == "tbody":
            self._in_tbody = True
        elif tag == "th" and self._in_thead:
            self._in_th = True
            self._current_th = []
        elif tag == "tr" and self._in_tbody:
            self._in_tr = True
            self._current_cells = []
            self._current_id = str(attr.get("data-rk") or attr.get("data-ri") or "")
        elif tag == "td" and self._in_tr:
            self._in_td = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "thead":
            self._in_thead = False
            if self._th_text:
                self.headers = self._th_text
        elif tag == "tbody":
            self._in_tbody = False
        elif tag == "th" and self._in_th:
            self._in_th = False
            self._th_text.append(" ".join(self._current_th).strip())
        elif tag == "td" and self._in_td:
            self._in_td = False
            self._current_cells.append(" ".join(self._current_cell).strip())
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            row = self._row_from_cells(self._current_id, self._current_cells)
            if row and row.official_number:
                self.rows.append(row)

    def handle_data(self, data: str) -> None:
        if self._in_th:
            self._current_th.append(data)
        elif self._in_td:
            self._current_cell.append(data)

    def _row_from_cells(self, registry_id: str, cells: list[str]) -> EoknoRow | None:
        if not cells:
            return None
        number = _cell_by_hints(self.headers, cells, _NUMBER_HEADER_HINTS) or cells[0]
        valid_from = _cell_by_hints(self.headers, cells, _VALID_FROM_HINTS)
        if not valid_from:
            valid_from = cells[1] if len(cells) > 1 else ""
        valid_until = _cell_by_hints(self.headers, cells, _VALID_TO_HINTS)
        if not valid_until:
            valid_until = cells[2] if len(cells) > 2 else ""
        status = _cell_by_hints(self.headers, cells, _STATUS_HINTS)
        if not status:
            status = cells[3] if len(cells) > 3 else (cells[2] if len(cells) > 2 else "")
        doc_type = _cell_by_hints(self.headers, cells, _TYPE_HINTS) or ""
        return EoknoRow(
            registry_id=registry_id,
            official_number=number,
            valid_from_raw=valid_from,
            valid_until_raw=valid_until,
            status_raw=status,
            doc_type=doc_type,
        )


def _cell_by_hints(headers: list[str], cells: list[str], hints: tuple[str, ...]) -> str:
    for index, header in enumerate(headers):
        lowered = header.lower()
        if any(hint in lowered for hint in hints) and index < len(cells):
            return cells[index]
    return ""
