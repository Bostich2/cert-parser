from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sert_parser.application.country_router import CountryRouter
from sert_parser.application.lookup_service import LookupService
from sert_parser.config import Settings
from sert_parser.domain.errors import CertificateNotFoundError, SourceUnavailableError
from sert_parser.domain.models import CertificateNumber, LookupResult, RegistryRecord
from sert_parser.infrastructure.cache import SqliteLookupCache
from sert_parser.infrastructure.registries.base import RegistryProvider

EXAMPLE = "ЕАЭС BY/112 02.01. ТР018 010.02 00276"


class FakeBelgiss(RegistryProvider):
    def __init__(self, record: RegistryRecord | None = None, error: Exception | None = None) -> None:
        self.record = record
        self.error = error
        self.calls = 0

    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        self.calls += 1
        if self.error:
            raise self.error
        assert self.record is not None
        return self.record


def _service(tmp_path: Path, provider: RegistryProvider) -> LookupService:
    settings = Settings(lookup_delay_seconds=0, cache_path=tmp_path / "cache.sqlite")
    cache = SqliteLookupCache(settings.cache_path, ttl_seconds=3600)
    router = CountryRouter({"BY": provider})
    return LookupService(router, cache, settings)


@pytest.fixture
def sample_record() -> RegistryRecord:
    return RegistryRecord(
        url="https://tsouz.belgiss.by/#!/tsouz/certifs/3345084/view",
        valid_from=date(2024, 5, 29),
        valid_until=date(2029, 5, 29),
        status_code="01",
        status_label="действует",
        registry_id="3345084",
        official_number=EXAMPLE,
    )


async def test_lookup_success_and_cache(tmp_path: Path, sample_record: RegistryRecord) -> None:
    provider = FakeBelgiss(record=sample_record)
    service = _service(tmp_path, provider)
    first = await service.lookup_one(EXAMPLE)
    second = await service.lookup_one(f"  {EXAMPLE}  ")
    assert first.url == sample_record.url
    assert first.valid_from == date(2024, 5, 29)
    assert first.valid_until == date(2029, 5, 29)
    assert second.valid_from == date(2024, 5, 29)
    assert any("страна BY" in step for step in first.trace)
    assert any("Готово" in step for step in first.trace)
    assert second.cached is True
    assert any("кэш" in step.lower() for step in second.trace)
    assert provider.calls == 1


async def test_legacy_cache_without_valid_from_is_refetched(
    tmp_path: Path, sample_record: RegistryRecord
) -> None:
    from sert_parser.application.lookup_service import _cache_payload
    from sert_parser.domain.certificate_number import parse_certificate_number

    provider = FakeBelgiss(record=sample_record)
    service = _service(tmp_path, provider)
    first = await service.lookup_one(EXAMPLE)
    payload = _cache_payload(first)
    payload.pop("valid_from")
    service._cache.set(parse_certificate_number(EXAMPLE).compact, payload)
    second = await service.lookup_one(EXAMPLE)
    assert first.valid_from == date(2024, 5, 29)
    assert second.cached is False
    assert second.valid_from == date(2024, 5, 29)
    assert provider.calls == 2


async def test_lookup_unsupported_country(tmp_path: Path, sample_record: RegistryRecord) -> None:
    service = _service(tmp_path, FakeBelgiss(record=sample_record))
    result = await service.lookup_one("ЕАЭС RU C-CN.АБ12.В.00001/24")
    assert result.error_code == "unsupported_country"
    assert result.country_code == "RU"


async def test_cached_unsupported_country_is_refetched(tmp_path: Path, sample_record: RegistryRecord) -> None:
    from sert_parser.application.lookup_service import _cache_payload
    from sert_parser.domain.certificate_number import parse_certificate_number

    provider = FakeBelgiss(record=sample_record)
    service = _service(tmp_path, provider)
    number = "ЕАЭС BY/112 02.01. ТР018 010.02 00276"
    service._cache.set(
        parse_certificate_number(number).compact,
        _cache_payload(
            LookupResult(
                query=number,
                normalized=number,
                country_code="BY",
                error="Страна BY пока не поддерживается",
                error_code="unsupported_country",
            )
        ),
    )
    result = await service.lookup_one(number)
    assert result.error_code is None
    assert result.url == sample_record.url
    assert result.cached is False
    assert any("unsupported_country" in step for step in result.trace)
    assert provider.calls == 1


async def test_unsupported_country_is_not_cached(tmp_path: Path, sample_record: RegistryRecord) -> None:
    from sert_parser.domain.certificate_number import parse_certificate_number

    service = _service(tmp_path, FakeBelgiss(record=sample_record))
    number = "ЕАЭС RU C-CN.АБ12.В.00001/24"
    first = await service.lookup_one(number)
    second = await service.lookup_one(number)
    assert first.error_code == "unsupported_country"
    assert second.error_code == "unsupported_country"
    assert service._cache.get(parse_certificate_number(number).compact) is None


async def test_lookup_not_found(tmp_path: Path) -> None:
    service = _service(tmp_path, FakeBelgiss(error=CertificateNotFoundError(EXAMPLE)))
    result = await service.lookup_one(EXAMPLE)
    assert result.error_code == "not_found"


async def test_cached_invalid_date_is_refetched(
    tmp_path: Path, sample_record: RegistryRecord
) -> None:
    from sert_parser.domain.certificate_number import parse_certificate_number

    provider = FakeBelgiss(record=sample_record)
    service = _service(tmp_path, provider)
    service._cache.set(
        parse_certificate_number(EXAMPLE).compact,
        {
            "query": EXAMPLE,
            "normalized": EXAMPLE,
            "country_code": "BY",
            "url": "https://example.invalid",
            "valid_from": "not-a-date",
            "valid_until": "2029-05-29",
            "status": "действует",
            "error_code": None,
        },
    )
    result = await service.lookup_one(EXAMPLE)
    assert result.cached is False
    assert result.valid_from == date(2024, 5, 29)
    assert provider.calls == 1
    assert any("некорректными датами" in step for step in result.trace)


async def test_source_error_is_not_cached(tmp_path: Path, sample_record: RegistryRecord) -> None:
    provider = FakeBelgiss(error=SourceUnavailableError())
    service = _service(tmp_path, provider)
    first = await service.lookup_one(EXAMPLE)
    provider.error = None
    provider.record = sample_record
    second = await service.lookup_one(EXAMPLE)
    assert first.error_code == "source_unavailable"
    assert second.url == sample_record.url
    assert provider.calls == 2
