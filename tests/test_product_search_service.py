from __future__ import annotations

from cert_parser.application.product_search_service import ProductSearchService
from cert_parser.config import Settings
from cert_parser.domain.errors import SourceUnavailableError
from cert_parser.domain.models import ProductSearchHit, ProductSearchQuery
from cert_parser.domain.ports import ProductSearchProvider


class FakeSearch(ProductSearchProvider):
    def __init__(
        self,
        source: str,
        hits: list[ProductSearchHit] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.source = source
        self.hits = hits or []
        self.error = error
        self.calls = 0

    async def search_products(self, query: ProductSearchQuery, *, limit: int) -> list[ProductSearchHit]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.hits[:limit]


def _hit(**kwargs) -> ProductSearchHit:
    defaults = {
        "query": "насос погружной",
        "official_number": "ЕАЭС RU С-CN.АА01.В.00001/24",
        "country_code": "RU",
        "doc_kind": "certificate",
        "product_name": "Насос погружной",
        "status": "действует",
        "status_code": "01",
        "source": "fsa_cert",
        "registry_id": "1",
    }
    defaults.update(kwargs)
    return ProductSearchHit(**defaults)


def _service(*providers: ProductSearchProvider) -> ProductSearchService:
    return ProductSearchService(list(providers), Settings(lookup_delay_seconds=0, lookup_concurrency=2))


async def test_query_too_short() -> None:
    provider = FakeSearch("fsa_cert", hits=[_hit()])
    service = _service(provider)
    hits = await service.search_one("аб")
    assert len(hits) == 1
    assert hits[0].error_code == "query_too_short"
    assert provider.calls == 0
    assert hits[0].trace


async def test_gather_isolates_source_errors() -> None:
    ok = FakeSearch("eaeu_ru", hits=[_hit(source="eaeu_ru")])
    bad = FakeSearch("fsa_cert", error=SourceUnavailableError("403"))
    service = _service(bad, ok)
    hits = await service.search_one("насос погружной")
    assert any(hit.source == "eaeu_ru" and hit.error_code is None for hit in hits)
    assert ok.calls == 1
    assert bad.calls == 1


async def test_dedup_by_compact_official_number() -> None:
    first = _hit(source="fsa_cert", registry_id="1")
    second = _hit(
        source="eaeu_ru",
        registry_id="2",
        official_number="ЕАЭС RU C-CN.АА01.В.00001/24",
    )
    service = _service(
        FakeSearch("fsa_cert", hits=[first]),
        FakeSearch("eaeu_ru", hits=[second]),
    )
    hits = await service.search_one("насос погружной")
    assert len(hits) == 1


async def test_ru_sorted_before_other_countries() -> None:
    by_hit = _hit(
        source="eaeu_other",
        country_code="BY",
        official_number="ЕАЭС BY/112 02.01.00001",
        product_name="Насос погружной",
        registry_id="by",
    )
    ru_hit = _hit(source="eaeu_ru", country_code="RU", registry_id="ru")
    service = _service(
        FakeSearch("eaeu_other", hits=[by_hit]),
        FakeSearch("eaeu_ru", hits=[ru_hit]),
    )
    hits = await service.search_one("насос погружной")
    assert hits[0].country_code == "RU"
    assert hits[1].country_code == "BY"


async def test_not_found_when_sources_empty() -> None:
    service = _service(FakeSearch("fsa_cert"), FakeSearch("eaeu_ru"))
    hits = await service.search_one("насос погружной")
    assert len(hits) == 1
    assert hits[0].error_code == "not_found"


async def test_all_sources_unavailable() -> None:
    service = _service(
        FakeSearch("fsa_cert", error=SourceUnavailableError()),
        FakeSearch("eaeu_ru", error=SourceUnavailableError()),
    )
    hits = await service.search_one("насос погружной")
    assert len(hits) == 1
    assert hits[0].error_code == "source_unavailable"
    assert any("недоступен" in step for step in hits[0].trace)
