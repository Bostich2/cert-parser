from __future__ import annotations

import re
from typing import Any

import httpx

from sert_parser.config import Settings
from sert_parser.domain.errors import CertificateNotFoundError, SourceUnavailableError
from sert_parser.domain.models import CertificateNumber, RegistryRecord
from sert_parser.infrastructure.registries.base import RegistryProvider
from sert_parser.infrastructure.registries.matching import (
    pick_matching_odata_item,
    record_from_odata_item,
)
from sert_parser.logging_setup import log_step

_EAEU_PREFIX_RE = re.compile(
    r"^(?:ЕАЭС|EAC|EAES|EADC|EAEC|EA3C|ТС|TC|CU)\s+",
    re.IGNORECASE,
)


class ArmeniaProvider(RegistryProvider):
    """Armenia EAEU certificates via tech.eaeunion.org OData."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._odata_url = settings.eaeu_odata_url.rstrip("/")
        self._view_base = settings.eaeu_register_view_url.rstrip("/")

    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        for doc_id in _doc_id_candidates(number):
            log_step(f"AM: OData eq docId «{doc_id}»")
            items = await self._query(f"docId eq '{_odata_escape(doc_id)}'")
            if items:
                match = pick_matching_odata_item(items, number)
                log_step(f"AM: выбрана запись id={match.get('Id')}")
                return record_from_odata_item(match, self._view_base)

        suffix = _contains_suffix(number)
        if suffix:
            filter_expr = (
                f"unifiedCountryCode/value eq 'AM' and "
                f"contains(docId,'{_odata_escape(suffix)}')"
            )
            log_step(f"AM: OData contains docId «{suffix}»")
            items = await self._query(filter_expr)
            if items:
                match = pick_matching_odata_item(items, number)
                log_step(f"AM: выбрана запись id={match.get('Id')}")
                return record_from_odata_item(match, self._view_base)

        raise CertificateNotFoundError(number.normalized)

    async def ping(self) -> bool:
        try:
            await self._query("unifiedCountryCode/value eq 'AM'", top=1)
        except SourceUnavailableError:
            return False
        return True

    async def _query(self, filter_expr: str, *, top: int = 25) -> list[dict[str, Any]]:
        params = {"$filter": filter_expr, "$top": str(top)}
        try:
            response = await self._client.get(self._odata_url, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError(
                "Реестр tech.eaeunion.org не ответил вовремя"
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailableError("Реестр tech.eaeunion.org недоступен") from exc
        log_step(f"AM: HTTP {response.status_code}, {len(response.content)} байт")
        values = payload.get("value") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            return []
        found = [item for item in values if isinstance(item, dict)]
        log_step(f"AM: записей в ответе: {len(found)}")
        return found


def _doc_id_candidates(number: CertificateNumber) -> list[str]:
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


def _contains_suffix(number: CertificateNumber) -> str | None:
    for candidate in _doc_id_candidates(number):
        if "/" in candidate:
            suffix = candidate.rsplit("/", 1)[-1].strip()
            if len(suffix) >= 5 and any(ch.isdigit() for ch in suffix):
                return suffix
        parts = [part.strip() for part in candidate.split("-") if part.strip()]
        if len(parts) >= 2:
            suffix = "-".join(parts[-2:])
            if len(suffix) >= 5 and any(ch.isdigit() for ch in suffix):
                return suffix
    return None


def _odata_escape(value: str) -> str:
    return value.replace("'", "''")
