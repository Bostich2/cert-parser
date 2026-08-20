from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from cert_parser.config import Settings
from cert_parser.domain.errors import SourceUnavailableError
from cert_parser.domain.models import ProductSearchHit, ProductSearchQuery, parse_iso_date
from cert_parser.domain.ports import ProductSearchProvider
from cert_parser.infrastructure.registries.fsa_session import (
    FsaSession,
    fsa_items,
    fsa_list_payload,
    fsa_product_name,
    fsa_search_terms,
)
from cert_parser.logging_setup import log_step

FSA_DECL_PRODUCT_COLUMN = "productFullName"
_REFERER_PATH = "/rds/declaration"
_LOG_PREFIX = "RU декларации"
_LIST_PATH = "/api/v1/rds/common/declarations/get"
_IDENTIFIERS_PATH = "/api/v1/rds/common/identifiers"


class FsaDeclarationsProvider(ProductSearchProvider):
    """Russia declarations via pub.fsa.gov.ru RDS API."""

    source = "fsa_decl"

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

    async def search_products(
        self,
        query: ProductSearchQuery,
        *,
        limit: int,
    ) -> list[ProductSearchHit]:
        size = max(1, limit)
        last_unavailable: SourceUnavailableError | None = None
        for term in fsa_search_terms(query):
            log_step(f"{_LOG_PREFIX}: поиск по продукции «{term}»")
            try:
                items = await self._search_by_column(term, size=size)
            except SourceUnavailableError as exc:
                last_unavailable = exc
                if self._session.has_token:
                    log_step(f"{_LOG_PREFIX}: этот запрос не ответил, следующий шаг")
                    continue
                raise
            if items:
                hits: list[ProductSearchHit] = []
                for item in items[:size]:
                    hit = await self._hit_from_item(item, query.raw)
                    if hit is not None:
                        hits.append(hit)
                if hits:
                    return hits
        if last_unavailable is not None:
            raise last_unavailable
        return []

    async def _search_by_column(self, term: str, *, size: int) -> list[dict[str, Any]]:
        payload = fsa_list_payload(
            FSA_DECL_PRODUCT_COLUMN,
            term,
            size=size,
            sort_column="declDate",
        )
        data = await self._session.api_json(
            "POST",
            _LIST_PATH,
            json_body=payload,
            referer_path=_REFERER_PATH,
            log_prefix=_LOG_PREFIX,
        )
        items = fsa_items(data)
        log_step(f"{_LOG_PREFIX}: записей в ответе: {len(items)}")
        return items

    async def _hit_from_item(self, item: dict[str, Any], query_raw: str) -> ProductSearchHit | None:
        registry_id = str(item.get("id") or "")
        if not registry_id:
            return None
        status_code = str(item.get("idStatus") or "") or None
        return ProductSearchHit(
            query=query_raw,
            official_number=str(item.get("number") or "") or None,
            country_code="RU",
            doc_kind="declaration",
            product_name=fsa_product_name(item),
            url=f"{self._base}/rds/declaration/view/{registry_id}/baseInfo",
            pdf_url=None,
            valid_from=_first_date(
                item.get("declDate"),
                item.get("startDate"),
                item.get("date"),
                item.get("regDate"),
            ),
            valid_until=parse_iso_date(
                _stringify(item.get("declEndDate") or item.get("endDate"))
            ),
            status=await self._status_label(status_code),
            status_code=status_code,
            registry_id=registry_id,
            source=self.source,
        )

    async def _status_label(self, status_code: str | None) -> str:
        if not status_code:
            return "не указан"
        names = await self._identifiers()
        return names.get(status_code, status_code)

    async def _identifiers(self) -> dict[str, str]:
        if self._status_names is not None:
            return self._status_names
        try:
            data = await self._session.api_json(
                "GET",
                _IDENTIFIERS_PATH,
                referer_path=_REFERER_PATH,
                log_prefix=_LOG_PREFIX,
            )
        except SourceUnavailableError:
            self._status_names = {}
            return self._status_names
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
