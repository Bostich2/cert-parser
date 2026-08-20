from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from cert_parser.config import Settings
from cert_parser.domain.errors import SourceUnavailableError
from cert_parser.domain.models import ProductSearchQuery
from cert_parser.logging_setup import log_step

logger = logging.getLogger(__name__)

UNAVAILABLE_403 = (
    "Реестр Росаккредитации недоступен (403). "
    "Нужен доступ из РФ или HTTPS_PROXY"
)


class FsaSession:
    """Anonymous login + JSON API calls to pub.fsa.gov.ru."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._base = settings.fsa_base_url.rstrip("/")
        self._username = settings.fsa_login_username
        self._password = settings.fsa_login_password
        self._token: str | None = None
        self._token_lock = asyncio.Lock()

    @property
    def base(self) -> str:
        return self._base

    async def api_json(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        referer_path: str,
        log_prefix: str,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        await self.ensure_token(referer_path=referer_path, log_prefix=log_prefix)
        url = f"{self._base}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Origin": self._base,
            "Referer": f"{self._base}{referer_path}",
            "Content-Type": "application/json",
        }
        try:
            response = await self._client.request(method, url, json=json_body, headers=headers)
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError("Реестр Росаккредитации не ответил вовремя") from exc
        except httpx.HTTPError as exc:
            logger.warning("FSA request failed: %s", exc)
            raise SourceUnavailableError("Реестр Росаккредитации недоступен") from exc
        if response.status_code == 401 and retry_auth:
            self._token = None
            return await self.api_json(
                method,
                path,
                json_body=json_body,
                referer_path=referer_path,
                log_prefix=log_prefix,
                retry_auth=False,
            )
        if response.status_code == 403:
            log_step(f"{log_prefix}: HTTP 403 — нужен доступ из РФ или HTTPS_PROXY")
            raise SourceUnavailableError(UNAVAILABLE_403)
        if response.status_code >= 400:
            log_step(f"{log_prefix}: HTTP {response.status_code} для {path}")
            logger.warning("FSA HTTP %s for %s", response.status_code, url)
            raise SourceUnavailableError("Реестр Росаккредитации вернул ошибку")
        try:
            data = response.json()
        except ValueError as exc:
            raise SourceUnavailableError("Реестр Росаккредитации вернул некорректный ответ") from exc
        return data if isinstance(data, dict) else {}

    async def ensure_token(self, *, referer_path: str, log_prefix: str) -> None:
        if self._token:
            return
        async with self._token_lock:
            if self._token:
                return
            log_step(f"{log_prefix}: анонимный вход в pub.fsa.gov.ru")
            try:
                await self._client.get(f"{self._base}{referer_path}")
                response = await self._client.post(
                    f"{self._base}/login",
                    json={"username": self._username, "password": self._password},
                    headers={
                        "Origin": self._base,
                        "Referer": f"{self._base}{referer_path}",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.TimeoutException as exc:
                raise SourceUnavailableError("Реестр Росаккредитации не ответил вовремя") from exc
            except httpx.HTTPError as exc:
                raise SourceUnavailableError("Реестр Росаккредитации недоступен") from exc
            if response.status_code == 403:
                log_step(f"{log_prefix}: HTTP 403 на /login — нужен доступ из РФ или HTTPS_PROXY")
                raise SourceUnavailableError(UNAVAILABLE_403)
            if response.status_code >= 400:
                raise SourceUnavailableError("Не удалось авторизоваться в реестре Росаккредитации")
            token = response.headers.get("Authorization") or response.headers.get("authorization")
            if not token:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if isinstance(body, dict):
                    token = str(body.get("access_token") or body.get("token") or "")
            if not token:
                raise SourceUnavailableError("Реестр Росаккредитации не вернул токен")
            if token.lower().startswith("bearer "):
                token = token[7:]
            self._token = token
            log_step(f"{log_prefix}: токен получен")


def fsa_list_payload(column: str, term: str, *, size: int) -> dict[str, Any]:
    return {
        "size": size,
        "page": 0,
        "filter": {
            "idTechReg": [],
            "regDate": {"minDate": "", "maxDate": ""},
            "endDate": {"minDate": "", "maxDate": ""},
            "columnsSearch": [
                {"name": column, "search": term, "type": 0, "translated": False}
            ],
        },
        "columnsSort": [{"column": "date", "sort": "DESC"}],
    }


def fsa_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def fsa_search_terms(query: ProductSearchQuery) -> list[str]:
    terms = [query.normalized]
    if query.tokens:
        joined = " ".join(query.tokens)
        if joined not in terms:
            terms.append(joined)
    if query.stems:
        joined = " ".join(query.stems)
        if joined not in terms:
            terms.append(joined)
    return terms


def fsa_product_name(item: dict[str, Any]) -> str | None:
    for key in ("fullName", "productName"):
        value = item.get(key)
        if value:
            return str(value)
    product = item.get("product")
    if isinstance(product, dict):
        for key in ("fullName", "name", "productName"):
            value = product.get(key)
            if value:
                return str(value)
    return None
