from __future__ import annotations

import re
from typing import Any

import httpx

from cert_parser.config import Settings
from cert_parser.domain.errors import CertificateNotFoundError, SourceUnavailableError
from cert_parser.domain.models import CertificateNumber, RegistryRecord
from cert_parser.domain.ports import RegistryProvider
from cert_parser.infrastructure.registries.matching import (
    pick_matching_odata_item,
    record_from_odata_item,
)
from cert_parser.logging_setup import log_step

_EAEU_PREFIX_RE = re.compile(
    r"^(?:ЕАЭС|EAC|EAES|EADC|EAEC|EA3C|ТС|TC|CU)\s+",
    re.IGNORECASE,
)


class EaeuOdataProvider(RegistryProvider):
    """EAEU conformity documents via tech.eaeunion.org OData."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        *,
        country_code: str,
    ) -> None:
        self._client = client
        self._country_code = country_code.upper()
        self._odata_url = settings.eaeu_odata_url.rstrip("/")
        self._view_base = settings.eaeu_register_view_url.rstrip("/")

    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        prefix = self._country_code
        for doc_id in _doc_id_candidates(number):
            log_step(f"{prefix}: OData eq docId «{doc_id}»")
            items = await self._query(f"docId eq '{_odata_escape(doc_id)}'")
            if items:
                match = pick_matching_odata_item(items, number)
                log_step(f"{prefix}: выбрана запись id={match.get('Id')}")
                return record_from_odata_item(match, self._view_base)

        suffix = _contains_suffix(number, self._country_code)
        if suffix:
            filter_expr = (
                f"unifiedCountryCode/value eq '{self._country_code}' and "
                f"contains(docId,'{_odata_escape(suffix)}')"
            )
            log_step(f"{prefix}: OData contains docId «{suffix}»")
            items = await self._query(filter_expr)
            if items:
                match = pick_matching_odata_item(items, number)
                log_step(f"{prefix}: выбрана запись id={match.get('Id')}")
                return record_from_odata_item(match, self._view_base)

        raise CertificateNotFoundError(number.normalized)

    async def ping(self) -> bool:
        try:
            await self._query(
                f"unifiedCountryCode/value eq '{self._country_code}'",
                top=1,
            )
        except SourceUnavailableError:
            return False
        return True

    async def _query(self, filter_expr: str, *, top: int = 25) -> list[dict[str, Any]]:
        params = {"$filter": filter_expr, "$top": str(top)}
        prefix = self._country_code
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
        log_step(f"{prefix}: HTTP {response.status_code}, {len(response.content)} байт")
        values = payload.get("value") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            return []
        found = [item for item in values if isinstance(item, dict)]
        log_step(f"{prefix}: записей в ответе: {len(found)}")
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


def _contains_suffix(number: CertificateNumber, country_code: str) -> str | None:
    if country_code == "KZ":
        return _kz_contains_suffix(number)
    if country_code == "KG":
        return _kg_contains_suffix(number)
    if country_code == "RU":
        return _ru_contains_suffix(number)
    return _am_contains_suffix(number)


def _kz_contains_suffix(number: CertificateNumber) -> str | None:
    for candidate in _doc_id_candidates(number):
        match = re.search(r"KZ[.\s]+(\d[\d.]{10,})", candidate, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _kg_contains_suffix(number: CertificateNumber) -> str | None:
    for candidate in _doc_id_candidates(number):
        match = re.search(r"KG\d+/[^/\s]+/([^/\s]+)", candidate, re.IGNORECASE)
        if match:
            suffix = match.group(1).strip()
            if len(suffix) >= 5 and any(ch.isdigit() for ch in suffix):
                return suffix
        if "/" in candidate:
            suffix = candidate.rsplit("/", 1)[-1].strip()
            if len(suffix) >= 5 and any(ch.isdigit() for ch in suffix):
                return suffix
    return None


def _ru_contains_suffix(number: CertificateNumber) -> str | None:
    for candidate in _doc_id_candidates(number):
        match = re.search(r"RU\s+([^\s]+/[^\s]+)$", candidate, re.IGNORECASE)
        if match:
            suffix = match.group(1).strip()
            if len(suffix) >= 5:
                return suffix
    return None


def _am_contains_suffix(number: CertificateNumber) -> str | None:
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
