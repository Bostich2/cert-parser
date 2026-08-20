from __future__ import annotations

import asyncio
from dataclasses import replace

from cert_parser.config import Settings
from cert_parser.domain.certificate_number import compact_number
from cert_parser.domain.errors import SourceUnavailableError
from cert_parser.domain.models import ProductSearchHit, ProductSearchQuery
from cert_parser.domain.ports import ProductSearchProvider
from cert_parser.domain.product_query import parse_product_search_query
from cert_parser.logging_setup import current_steps, log_step, start_steps

PER_SOURCE_CAP = 10
DEFAULT_LIMIT_PER_QUERY = 25
MAX_LIMIT_PER_QUERY = 50

_QUERY_TOO_SHORT = "Слишком короткий запрос"
_NOT_FOUND = "По наименованию продукции ничего не найдено"
_ALL_UNAVAILABLE = "Реестры недоступны"


class ProductSearchService:
    def __init__(
        self,
        providers: list[ProductSearchProvider],
        settings: Settings,
    ) -> None:
        self._providers = providers
        self._concurrency = max(1, settings.lookup_concurrency)
        self._delay_seconds = max(0.0, settings.lookup_delay_seconds)

    async def search_many(
        self,
        raw_queries: list[str],
        *,
        limit_per_query: int = DEFAULT_LIMIT_PER_QUERY,
    ) -> list[ProductSearchHit]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run_one(raw: str) -> list[ProductSearchHit]:
            async with semaphore:
                return await self.search_one(raw, limit_per_query=limit_per_query)

        batches = await asyncio.gather(*[run_one(raw) for raw in raw_queries])
        return [hit for batch in batches for hit in batch]

    async def search_one(
        self,
        raw: str,
        *,
        limit_per_query: int = DEFAULT_LIMIT_PER_QUERY,
    ) -> list[ProductSearchHit]:
        start_steps()
        log_step(f"Поиск по продукции: «{str(raw).strip()}»")
        query = parse_product_search_query(raw)
        if query is None:
            log_step("Запрос слишком короткий")
            return [_with_trace(_error_hit(raw, _QUERY_TOO_SHORT, "query_too_short"))]

        limit = _clamp_limit(limit_per_query)
        log_step(f"Нормализован: {query.normalized}")
        gathered = await asyncio.gather(
            *[self._search_source(provider, query, PER_SOURCE_CAP) for provider in self._providers],
            return_exceptions=True,
        )

        hits: list[ProductSearchHit] = []
        failures = 0
        for provider, result in zip(self._providers, gathered, strict=True):
            if isinstance(result, BaseException):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                if not isinstance(result, SourceUnavailableError):
                    log_step(f"{provider.source}: ошибка — {result}")
                failures += 1
                continue
            hits.extend(result)

        if not hits:
            if failures == len(self._providers) and self._providers:
                log_step("Все источники недоступны")
                error_hit = _error_hit(query.raw, _ALL_UNAVAILABLE, "source_unavailable")
                return [_with_trace(error_hit)]
            log_step("Ничего не найдено")
            return [_with_trace(_error_hit(query.raw, _NOT_FOUND, "not_found"))]

        ranked = _dedup_ranked(hits, query)
        limited = ranked[:limit]
        log_step(f"Готово: {len(limited)} записей")
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        return [_with_trace(hit) for hit in limited]

    async def _search_source(
        self,
        provider: ProductSearchProvider,
        query: ProductSearchQuery,
        limit: int,
    ) -> list[ProductSearchHit]:
        log_step(f"{provider.source}: поиск")
        try:
            hits = await provider.search_products(query, limit=limit)
        except SourceUnavailableError as exc:
            log_step(f"{provider.source}: недоступен — {exc.message}")
            raise
        log_step(f"{provider.source}: найдено {len(hits)}")
        return hits[:limit]


def _clamp_limit(limit_per_query: int) -> int:
    return max(1, min(int(limit_per_query), MAX_LIMIT_PER_QUERY))


def _error_hit(query: str, message: str, error_code: str) -> ProductSearchHit:
    return ProductSearchHit(query=query, error=message, error_code=error_code)


def _with_trace(hit: ProductSearchHit) -> ProductSearchHit:
    return replace(hit, trace=tuple(current_steps()))


def _dedup_ranked(hits: list[ProductSearchHit], query: ProductSearchQuery) -> list[ProductSearchHit]:
    ordered = sorted(hits, key=lambda hit: _rank_key(hit, query))
    seen: set[str] = set()
    unique: list[ProductSearchHit] = []
    for hit in ordered:
        key = _dedup_key(hit)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def _dedup_key(hit: ProductSearchHit) -> str:
    if hit.official_number:
        compact = compact_number(hit.official_number)
        if compact:
            return compact
    return f"{hit.source}:{hit.registry_id or ''}:{id(hit)}"


def _rank_key(hit: ProductSearchHit, query: ProductSearchQuery) -> tuple:
    country = (hit.country_code or "").upper()
    ru_first = 0 if country == "RU" else 1
    name = (hit.product_name or "").lower().replace("ё", "е")
    needle = query.normalized.lower()
    phrase_miss = 0 if needle and needle in name else 1
    token_hits = -sum(1 for token in query.tokens if token.lower() in name)
    inactive = 0 if _is_active(hit) else 1
    return (ru_first, phrase_miss, token_hits, inactive)


def _is_active(hit: ProductSearchHit) -> bool:
    code = (hit.status_code or "").strip()
    if code in {"01", "04", "05"}:
        return True
    label = (hit.status or "").lower().replace("ё", "е")
    return "действ" in label and "не действ" not in label
