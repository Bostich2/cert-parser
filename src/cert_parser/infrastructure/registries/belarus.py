from __future__ import annotations

import logging
from typing import Any

import httpx

from cert_parser.config import Settings
from cert_parser.domain.errors import CertificateNotFoundError, SourceUnavailableError
from cert_parser.domain.models import CertificateNumber, RegistryRecord
from cert_parser.domain.ports import RegistryProvider
from cert_parser.infrastructure.registries.matching import pick_matching_item, record_from_light_item
from cert_parser.logging_setup import log_step

logger = logging.getLogger(__name__)


class BelgissProvider(RegistryProvider):
    """Belarus EAEU certificates via api.belgiss.by (tsouz-certifs-light)."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._api_base = settings.belgiss_api_url.rstrip("/")
        self._public_base = settings.belgiss_public_url.rstrip("/")

    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        items = await self._search(number.normalized)
        if not items and number.search_term != number.normalized:
            log_step(f"BY: по полной строке пусто, повтор с «{number.search_term}»")
            items = await self._search(number.search_term)
        if not items:
            raise CertificateNotFoundError(number.normalized)
        match = pick_matching_item(items, number)
        log_step(f"BY: выбрана запись id={match.get('certdecltr_id')}")
        return record_from_light_item(match, self._public_base)

    async def ping(self) -> bool:
        try:
            payload = await self._get(
                "/tsouz/tsouz-certifs-light",
                {
                    "page": 1,
                    "per-page": 1,
                    "sort": "-certdecltr_id",
                    "query[trts]": 1,
                },
            )
        except SourceUnavailableError:
            return False
        return isinstance(payload, dict) and "items" in payload

    async def _search(self, term: str) -> list[dict[str, Any]]:
        log_step(f"BY: GET api.belgiss.by, filter[DocId][like]={term}")
        payload = await self._get(
            "/tsouz/tsouz-certifs-light",
            {
                "page": 1,
                "per-page": 25,
                "sort": "-certdecltr_id",
                "query[trts]": 1,
                "filter[DocId][like]": term,
            },
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            logger.warning("Belgiss search returned unexpected payload for %s", term)
            log_step("BY: неожиданный ответ API")
            return []
        found = [item for item in items if isinstance(item, dict)]
        log_step(f"BY: записей в ответе: {len(found)}")
        return found

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._api_base}{path}"
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("Belgiss HTTP %s for %s", exc.response.status_code, url)
            raise SourceUnavailableError("Реестр БелГИСС вернул ошибку") from exc
        except httpx.HTTPError as exc:
            logger.warning("Belgiss request failed: %s", exc)
            message = "Реестр БелГИСС недоступен"
            if isinstance(exc, httpx.ConnectError):
                message = f"Реестр БелГИСС недоступен: {exc}"
            raise SourceUnavailableError(message) from exc
        except ValueError as exc:
            raise SourceUnavailableError("Реестр БелГИСС вернул некорректный ответ") from exc
        if not isinstance(data, dict):
            raise SourceUnavailableError("Реестр БелГИСС вернул некорректный ответ")
        return data
