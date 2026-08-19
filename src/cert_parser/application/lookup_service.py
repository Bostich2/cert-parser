from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date

from cert_parser.application.country_router import CountryRouter
from cert_parser.application.serializers import lookup_result_to_cache_payload
from cert_parser.config import Settings
from cert_parser.domain.certificate_number import parse_certificate_number
from cert_parser.domain.errors import CertParserError
from cert_parser.domain.models import LookupResult, RegistryRecord
from cert_parser.domain.ports import LookupCache
from cert_parser.logging_setup import current_steps, log_step, start_steps

_COUNTRY_NAMES = {
    "BY": "Беларусь",
    "RU": "Россия",
    "KZ": "Казахстан",
    "KG": "Кыргызстан",
    "AM": "Армения",
}

_CHAIN_SOURCES = {
    "BY": ("tech.eaeunion.org", "api.belgiss.by"),
    "RU": ("tech.eaeunion.org", "pub.fsa.gov.ru"),
    "KZ": ("tech.eaeunion.org", "eokno.gov.kz (JSF)"),
    "KG": ("tech.eaeunion.org", "swis.trade.kg"),
}

_STATIC_SOURCES = {
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
        self._settings = settings
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
        except CertParserError as exc:
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
                    pdf_url=result.pdf_url,
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

        source = _country_source(number.country_code, self._settings.lookup_eaeu_first)
        log_step(f"Провайдер: {source}")
        try:
            provider = self._router.get(number.country_code)
            record = await provider.lookup(number)
            if self._delay_seconds:
                await asyncio.sleep(self._delay_seconds)
        except CertParserError as exc:
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
        pdf_url=record.pdf_url,
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
        pdf_url=payload.get("pdf_url"),
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


def _country_source(country_code: str, eaeu_first: bool) -> str:
    static = _STATIC_SOURCES.get(country_code)
    if static is not None:
        return static
    chain = _CHAIN_SOURCES.get(country_code)
    if chain is None:
        return f"страна {country_code}"
    primary, fallback = chain if eaeu_first else (chain[1], chain[0])
    name = _COUNTRY_NAMES.get(country_code, country_code)
    return f"{name}, {primary}, при отсутствии — {fallback}"
