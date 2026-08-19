from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date

from sert_parser.application.country_router import CountryRouter
from sert_parser.application.serializers import lookup_result_to_cache_payload
from sert_parser.config import Settings
from sert_parser.domain.certificate_number import parse_certificate_number
from sert_parser.domain.errors import SertParserError
from sert_parser.domain.models import LookupResult, RegistryRecord
from sert_parser.domain.ports import LookupCache
from sert_parser.logging_setup import current_steps, log_step, start_steps

_COUNTRY_SOURCES = {
    "BY": "Беларусь, api.belgiss.by",
    "RU": "Россия, pub.fsa.gov.ru",
    "KZ": "Казахстан, eokno.gov.kz (JSF), при отсутствии — tech.eaeunion.org",
    "KG": "Кыргызстан, swis.trade.kg",
    "AM": "Армения, ARMNAB (armnab.am), поиск через OData tech.eaeunion.org",
}


class LookupService:
    def __init__(
        self,
        router: CountryRouter,
        cache: LookupCache,
        settings: Settings,
    ) -> None:
        self._router = router
        self._cache = cache
        self._concurrency = max(1, settings.lookup_concurrency)
        self._delay_seconds = max(0.0, settings.lookup_delay_seconds)

    async def lookup_many(self, raw_numbers: list[str]) -> list[LookupResult]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run_one(raw: str) -> LookupResult:
            async with semaphore:
                return await self.lookup_one(raw)

        return await asyncio.gather(*[run_one(raw) for raw in raw_numbers])

    async def lookup_one(self, raw: str) -> LookupResult:
        start_steps()
        log_step(f"Поиск: «{raw.strip()}»")
        try:
            number = parse_certificate_number(raw)
        except SertParserError as exc:
            log_step(f"Номер не разобран: {exc.message}")
            return _with_trace(
                LookupResult(query=raw, error=exc.message, error_code=exc.error_code)
            )

        log_step(f"Нормализован: {number.normalized}, страна {number.country_code}")
        cached = self._cache.get(number.compact)
        if cached is not None and "valid_from" not in cached:
            cached = None
        if cached is not None and cached.get("error_code") == "unsupported_country":
            log_step("Кэш unsupported_country пропущен, повторный запрос в реестр")
            cached = None
        if cached is not None and _cache_has_invalid_dates(cached):
            log_step("Кэш с некорректными датами пропущен, повторный запрос в реестр")
            self._cache.delete(number.compact)
            cached = None
        if cached is not None:
            log_step("Результат взят из локального кэша")
            result = _result_from_payload(cached, cached_flag=True)
            return _with_trace(
                LookupResult(
                    query=raw,
                    normalized=result.normalized,
                    country_code=result.country_code,
                    url=result.url,
                    valid_from=result.valid_from,
                    valid_until=result.valid_until,
                    status=result.status,
                    status_code=result.status_code,
                    registry_id=result.registry_id,
                    official_number=result.official_number,
                    error=result.error,
                    error_code=result.error_code,
                    cached=True,
                )
            )

        source = _COUNTRY_SOURCES.get(
            number.country_code,
            f"страна {number.country_code}",
        )
        log_step(f"Провайдер: {source}")
        try:
            provider = self._router.get(number.country_code)
            record = await provider.lookup(number)
            if self._delay_seconds:
                await asyncio.sleep(self._delay_seconds)
        except SertParserError as exc:
            log_step(f"Ошибка: {exc.error_code} — {exc.message}")
            result = _with_trace(
                LookupResult(
                    query=raw,
                    normalized=number.normalized,
                    country_code=number.country_code,
                    error=exc.message,
                    error_code=exc.error_code,
                )
            )
            if exc.error_code == "not_found":
                self._cache.set(number.compact, _cache_payload(result))
            return result

        log_step(_success_summary(record))
        result = _with_trace(
            _result_from_record(raw, number.normalized, number.country_code, record)
        )
        self._cache.set(number.compact, _cache_payload(result))
        return result


def _with_trace(result: LookupResult) -> LookupResult:
    return replace(result, trace=tuple(current_steps()))


def _cache_payload(result: LookupResult) -> dict:
    return lookup_result_to_cache_payload(result)


def _success_summary(record: RegistryRecord) -> str:
    parts = [f"Готово: {record.status_label}"]
    if record.valid_from is not None:
        parts.append(f"с {record.valid_from.isoformat()}")
    if record.valid_until is not None:
        parts.append(f"до {record.valid_until.isoformat()}")
    if record.official_number:
        parts.append(record.official_number)
    return ", ".join(parts)


def _result_from_record(
    query: str,
    normalized: str,
    country_code: str,
    record: RegistryRecord,
) -> LookupResult:
    return LookupResult(
        query=query,
        normalized=normalized,
        country_code=country_code,
        url=record.url,
        valid_from=record.valid_from,
        valid_until=record.valid_until,
        status=record.status_label,
        status_code=record.status_code,
        registry_id=record.registry_id,
        official_number=record.official_number,
    )


def _parse_cached_date(value: object) -> date | None:
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _cache_has_invalid_dates(payload: dict) -> bool:
    for key in ("valid_from", "valid_until"):
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None or value == "":
            continue
        if _parse_cached_date(value) is None:
            return True
    return False


def _result_from_payload(payload: dict, cached_flag: bool) -> LookupResult:
    return LookupResult(
        query=str(payload.get("query") or ""),
        normalized=payload.get("normalized"),
        country_code=payload.get("country_code"),
        url=payload.get("url"),
        valid_from=_parse_cached_date(payload.get("valid_from")),
        valid_until=_parse_cached_date(payload.get("valid_until")),
        status=payload.get("status"),
        status_code=payload.get("status_code"),
        registry_id=payload.get("registry_id"),
        official_number=payload.get("official_number"),
        error=payload.get("error"),
        error_code=payload.get("error_code"),
        cached=cached_flag,
    )
