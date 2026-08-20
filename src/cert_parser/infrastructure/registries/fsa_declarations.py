from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from cert_parser.config import Settings
from cert_parser.domain.models import ProductSearchHit, ProductSearchQuery, parse_iso_date
from cert_parser.domain.ports import ProductSearchProvider
from cert_parser.infrastructure.registries.fsa_session import (
    FsaSession,
    fetch_fsa_product_items,
    fsa_product_name,
    fsa_status_names,
    load_fsa_identifiers,
)

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
        self._identifiers: dict[str, Any] | None = None

    async def search_products(
        self,
        query: ProductSearchQuery,
        *,
        limit: int,
    ) -> list[ProductSearchHit]:
        size = max(1, limit)
        items = await fetch_fsa_product_items(
            self._session,
            query,
            column=FSA_DECL_PRODUCT_COLUMN,
            size=size,
            sort_column="declDate",
            list_path=_LIST_PATH,
            referer_path=_REFERER_PATH,
            log_prefix=_LOG_PREFIX,
            load_identifiers=self._identifiers_data,
        )
        hits: list[ProductSearchHit] = []
        for item in items[:size]:
            hit = await self._hit_from_item(item, query.raw)
            if hit is not None:
                hits.append(hit)
        return hits

    async def _status_label(self, status_code: str | None) -> str:
        if not status_code:
            return "не указан"
        names = fsa_status_names(await self._identifiers_data())
        return names.get(status_code, status_code)

    async def _identifiers_data(self) -> dict[str, Any]:
        if self._identifiers is not None:
            return self._identifiers
        self._identifiers = await load_fsa_identifiers(
            self._session,
            path=_IDENTIFIERS_PATH,
            referer_path=_REFERER_PATH,
            log_prefix=_LOG_PREFIX,
        )
        return self._identifiers

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
