from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from cert_parser.config import Settings
from cert_parser.domain.certificate_number import compact_number, numbers_match
from cert_parser.domain.errors import (
    AmbiguousMatchError,
    CertificateNotFoundError,
    SourceUnavailableError,
)
from cert_parser.domain.models import CertificateNumber, ProductSearchHit, ProductSearchQuery, RegistryRecord, parse_iso_date
from cert_parser.domain.ports import ProductSearchProvider, RegistryProvider
from cert_parser.infrastructure.registries.fsa_pdf import build_fsa_pdf_proxy_url
from cert_parser.infrastructure.registries.fsa_session import (
    FsaSession,
    fsa_items,
    fsa_list_payload,
    fsa_product_name,
    fsa_search_terms,
)
from cert_parser.infrastructure.registries.matching import is_safe_contained_match
from cert_parser.logging_setup import log_step

FSA_CERT_PRODUCT_COLUMN = "fullName"
_REFERER_PATH = "/rss/certificate"
_LOG_PREFIX = "RU"


class FsaProvider(RegistryProvider, ProductSearchProvider):
    """Russia EAEU certificates via pub.fsa.gov.ru RSS API."""

    source = "fsa_cert"

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        session: FsaSession | None = None,
    ) -> None:
        self._client = client
        self._base = settings.fsa_base_url.rstrip("/")
        self._session = session or FsaSession(client, settings)
        self._status_names: dict[str, str] | None = None

    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        items = await self._search(number.normalized)
        log_step(f"RU: записей в ответе: {len(items)}")
        match = _pick_item(items, number)
        log_step(f"RU: выбрана запись id={match.get('id')}, номер {match.get('number')}")
        registry_id = str(match.get("id") or "")
        if not registry_id:
            raise CertificateNotFoundError(number.normalized)
        status_code = str(match.get("idStatus") or "") or None
        status_label = await self._status_label(status_code)
        return RegistryRecord(
            url=f"{self._base}/rss/certificate/view/{registry_id}/baseInfo",
            valid_from=_first_date(match.get("startDate"), match.get("date"), match.get("regDate")),
            valid_until=parse_iso_date(_stringify(match.get("endDate"))),
            status_code=status_code,
            status_label=status_label,
            registry_id=registry_id,
            official_number=str(match.get("number") or number.normalized),
            pdf_url=build_fsa_pdf_proxy_url(registry_id),
        )

    async def search_products(
        self,
        query: ProductSearchQuery,
        *,
        limit: int,
    ) -> list[ProductSearchHit]:
        size = max(1, limit)
        for term in fsa_search_terms(query):
            log_step(f"RU: поиск сертификатов по продукции «{term}»")
            items = await self._search_by_column(FSA_CERT_PRODUCT_COLUMN, term, size=size)
            if items:
                hits: list[ProductSearchHit] = []
                for item in items[:size]:
                    hit = await self._hit_from_item(item, query.raw)
                    if hit is not None:
                        hits.append(hit)
                if hits:
                    return hits
        return []

    async def ping(self) -> bool:
        try:
            await self._ensure_token()
            response = await self._client.get(f"{self._base}/rss/certificate")
            return response.status_code < 500
        except SourceUnavailableError:
            return False
        except httpx.HTTPError:
            return False

    async def _hit_from_item(self, item: dict[str, Any], query_raw: str) -> ProductSearchHit | None:
        registry_id = str(item.get("id") or "")
        if not registry_id:
            return None
        status_code = str(item.get("idStatus") or "") or None
        status_label = await self._status_label(status_code)
        official = str(item.get("number") or "") or None
        return ProductSearchHit(
            query=query_raw,
            official_number=official,
            country_code="RU",
            doc_kind="certificate",
            product_name=fsa_product_name(item),
            url=f"{self._base}/rss/certificate/view/{registry_id}/baseInfo",
            pdf_url=build_fsa_pdf_proxy_url(registry_id),
            valid_from=_first_date(item.get("startDate"), item.get("date"), item.get("regDate")),
            valid_until=parse_iso_date(_stringify(item.get("endDate"))),
            status=status_label,
            status_code=status_code,
            registry_id=registry_id,
            source=self.source,
        )

    async def _search(self, term: str) -> list[dict[str, Any]]:
        log_step(f"RU: POST /api/v1/rss/common/certificates/get, number={term}")
        payload = fsa_list_payload("number", term, size=10)
        data = await self._api_json(
            "POST",
            "/api/v1/rss/common/certificates/get",
            json_body=payload,
        )
        return fsa_items(data)

    async def _search_by_column(self, column: str, term: str, *, size: int) -> list[dict[str, Any]]:
        payload = fsa_list_payload(column, term, size=size)
        data = await self._api_json(
            "POST",
            "/api/v1/rss/common/certificates/get",
            json_body=payload,
        )
        items = fsa_items(data)
        log_step(f"RU: записей в ответе: {len(items)}")
        return items

    async def _status_label(self, status_code: str | None) -> str:
        if not status_code:
            return "не указан"
        names = await self._identifiers()
        return names.get(status_code, status_code)

    async def _identifiers(self) -> dict[str, str]:
        if self._status_names is not None:
            return self._status_names
        data = await self._api_json("GET", "/api/v1/rss/common/identifiers")
        mapping: dict[str, str] = {}
        status_block = data.get("status") if isinstance(data, dict) else None
        if isinstance(status_block, dict):
            for key, value in status_block.items():
                if isinstance(value, dict) and value.get("name"):
                    mapping[str(key)] = str(value["name"])
                elif isinstance(value, str):
                    mapping[str(key)] = value
        elif isinstance(status_block, list):
            for item in status_block:
                if isinstance(item, dict) and item.get("id") is not None:
                    mapping[str(item["id"])] = str(item.get("name") or item["id"])
        self._status_names = mapping
        return mapping

    async def _api_json(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        return await self._session.api_json(
            method,
            path,
            json_body=json_body,
            referer_path=_REFERER_PATH,
            log_prefix=_LOG_PREFIX,
            retry_auth=retry_auth,
        )

    async def _ensure_token(self) -> None:
        await self._session.ensure_token(referer_path=_REFERER_PATH, log_prefix=_LOG_PREFIX)


def _pick_item(items: list[dict[str, Any]], number: CertificateNumber) -> dict[str, Any]:
    exact = [
        item
        for item in items
        if numbers_match(str(item.get("number") or ""), number.normalized)
        or numbers_match(str(item.get("number") or ""), number.search_term)
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousMatchError(number.normalized)

    contained = [item for item in items if _item_contains(item, number)]
    if len(contained) == 1:
        return contained[0]
    if len(contained) > 1:
        raise AmbiguousMatchError(number.normalized)
    if not items:
        raise CertificateNotFoundError(number.normalized)
    raise CertificateNotFoundError(number.normalized)


def _item_contains(item: dict[str, Any], number: CertificateNumber) -> bool:
    doc_compact = compact_number(str(item.get("number") or ""))
    return is_safe_contained_match(
        number.compact,
        doc_compact,
        compact_number(number.search_term),
    )


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _first_date(*values: Any) -> date | None:
    for value in values:
        parsed = parse_iso_date(_stringify(value))
        if parsed is not None:
            return parsed
    return None
