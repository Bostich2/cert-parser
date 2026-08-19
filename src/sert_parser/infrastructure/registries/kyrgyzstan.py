from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from sert_parser.config import Settings
from sert_parser.domain.certificate_number import compact_number, numbers_match
from sert_parser.domain.errors import (
    AmbiguousMatchError,
    CertificateNotFoundError,
    SourceUnavailableError,
)
from sert_parser.domain.models import CertificateNumber, RegistryRecord
from sert_parser.infrastructure.registries.base import RegistryProvider
from sert_parser.infrastructure.registries.matching import is_safe_contained_match
from sert_parser.infrastructure.registries.kyrgyzstan_html import (
    SwisRow,
    has_result_rows,
    is_not_found,
    parse_result_rows,
    row_valid_from,
    row_valid_until,
    status_label,
)
from sert_parser.logging_setup import log_step

_CERT_PATH = "/Registry/CertificateOfConformity"
_DECL_PATH = "/Registry/DeclarationOfConformity"
_EAEU_PREFIX_RE = re.compile(
    r"^(?:ЕАЭС|EAC|EAES|EADC|EAEC|EA3C|ТС|TC|CU)\s+",
    re.IGNORECASE,
)
_DECLARATION_HINT_RE = re.compile(r"(?:^|[\s./])[ДD]\.", re.IGNORECASE)


class SwisProvider(RegistryProvider):
    """Kyrgyzstan EAEU certificates and declarations via swis.trade.kg."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._base = settings.swis_base_url.rstrip("/")
        self._cert_url = f"{self._base}{_CERT_PATH}"
        self._decl_url = f"{self._base}{_DECL_PATH}"

    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        search_terms = _search_terms(number)
        registry_paths = _registry_paths(number)
        for path, kind in registry_paths:
            url = f"{self._base}{path}"
            for term in search_terms:
                log_step(f"KG: GET swis.trade.kg ({kind}), номер «{term}»")
                html = await self._search(url, term)
                if is_not_found(html) or not has_result_rows(html):
                    continue
                rows = parse_result_rows(html, registry_kind=kind)
                log_step(f"KG: строк в таблице ({kind}): {len(rows)}")
                match = _pick_row(rows, number)
                log_step(
                    f"KG: выбрана запись {match.official_number}, "
                    f"статус {match.status_raw or '—'}"
                )
                code, label = status_label(match.status_raw)
                registry_id = match.doc_path.rsplit("/", 1)[-1]
                return RegistryRecord(
                    url=_result_url(url, term),
                    valid_from=row_valid_from(match),
                    valid_until=row_valid_until(match),
                    status_code=code,
                    status_label=label,
                    registry_id=registry_id,
                    official_number=match.official_number,
                )
        raise CertificateNotFoundError(number.normalized)

    async def ping(self) -> bool:
        try:
            response = await self._client.get(self._cert_url)
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    async def _search(self, url: str, term: str) -> str:
        params = {
            "RegisterNumber": term,
            "Status": "Все",
            "Agency": "Все",
            "PageNumber": "1",
            "submitButton": "Найти",
        }
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError("Реестр swis.trade.kg не ответил вовремя") from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailableError("Реестр swis.trade.kg недоступен") from exc
        log_step(f"KG: HTTP {response.status_code}, {len(response.content)} байт")
        return response.text


def _search_terms(number: CertificateNumber) -> list[str]:
    terms: list[str] = []
    for candidate in (number.normalized, number.search_term):
        value = candidate.strip()
        if value and value not in terms:
            terms.append(value)
        if value and not _EAEU_PREFIX_RE.match(value):
            prefixed = f"ЕАЭС {value}"
            if prefixed not in terms:
                terms.append(prefixed)
    return terms


def _registry_paths(number: CertificateNumber) -> list[tuple[str, str]]:
    candidates = (
        number.normalized,
        number.search_term,
        f"ЕАЭС {number.search_term}",
    )
    declaration_first = any(
        _DECLARATION_HINT_RE.search(item)
        for item in candidates
        if item
    )
    paths = [
        (_DECL_PATH, "declaration"),
        (_CERT_PATH, "certificate"),
    ]
    if not declaration_first:
        paths.reverse()
    return paths


def _pick_row(rows: list[SwisRow], number: CertificateNumber) -> SwisRow:
    exact = [
        row
        for row in rows
        if numbers_match(row.official_number, number.normalized)
        or numbers_match(row.official_number, number.search_term)
        or numbers_match(row.official_number, f"ЕАЭС {number.search_term}")
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousMatchError(number.normalized)

    contained = [row for row in rows if _row_contains(row, number)]
    if len(contained) == 1:
        return contained[0]
    if len(contained) > 1:
        raise AmbiguousMatchError(number.normalized)
    if not rows:
        raise CertificateNotFoundError(number.normalized)
    raise CertificateNotFoundError(number.normalized)


def _row_contains(row: SwisRow, number: CertificateNumber) -> bool:
    doc_compact = compact_number(row.official_number)
    return is_safe_contained_match(
        number.compact,
        doc_compact,
        compact_number(number.search_term),
    )


def _result_url(register_url: str, term: str) -> str:
    encoded = quote(term)
    return (
        f"{register_url}?RegisterNumber={encoded}"
        f"&Status={quote('Все')}&Agency={quote('Все')}"
        f"&PageNumber=1&submitButton={quote('Найти')}"
    )
