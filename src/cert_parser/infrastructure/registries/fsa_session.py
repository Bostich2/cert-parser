from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import httpx

from cert_parser.config import Settings
from cert_parser.domain.errors import SourceUnavailableError
from cert_parser.domain.models import ProductSearchQuery
from cert_parser.domain.product_query import contiguous_search_terms
from cert_parser.infrastructure.registries.fsa_filters import (
    acting_status_ids,
    active_end_min,
    id_name_map,
    is_fsa_timeout,
    tech_reg_ids_for_query,
)
from cert_parser.logging_setup import log_step

logger = logging.getLogger(__name__)

FSA_WARMUP_TIMEOUT_SECONDS = 8.0
FSA_LOGIN_TIMEOUT_SECONDS = 15.0
FSA_LOGIN_ERROR_TTL_SECONDS = 30.0

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
        self._login_error: SourceUnavailableError | None = None
        self._login_error_at: float = 0.0

    @property
    def has_token(self) -> bool:
        return bool(self._token)

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
            if self._login_error and (
                time.monotonic() - self._login_error_at < FSA_LOGIN_ERROR_TTL_SECONDS
            ):
                raise self._login_error
            log_step(f"{log_prefix}: анонимный вход в pub.fsa.gov.ru")
            try:
                try:
                    await self._client.get(
                        f"{self._base}{referer_path}",
                        timeout=FSA_WARMUP_TIMEOUT_SECONDS,
                    )
                except httpx.TimeoutException:
                    log_step(f"{log_prefix}: страница входа не ответила, пробуем /login")
                response = await self._client.post(
                    f"{self._base}/login",
                    json={"username": self._username, "password": self._password},
                    headers={
                        "Origin": self._base,
                        "Referer": f"{self._base}{referer_path}",
                        "Content-Type": "application/json",
                    },
                    timeout=FSA_LOGIN_TIMEOUT_SECONDS,
                )
            except httpx.TimeoutException as exc:
                self._remember_login_error(
                    SourceUnavailableError("Реестр Росаккредитации не ответил вовремя")
                )
                raise self._login_error from exc
            except httpx.HTTPError as exc:
                self._remember_login_error(
                    SourceUnavailableError("Реестр Росаккредитации недоступен")
                )
                raise self._login_error from exc
            if response.status_code == 403:
                log_step(f"{log_prefix}: HTTP 403 на /login — нужен доступ из РФ или HTTPS_PROXY")
                self._remember_login_error(SourceUnavailableError(UNAVAILABLE_403))
                raise self._login_error
            if response.status_code >= 400:
                self._remember_login_error(
                    SourceUnavailableError("Не удалось авторизоваться в реестре Росаккредитации")
                )
                raise self._login_error
            token = response.headers.get("Authorization") or response.headers.get("authorization")
            if not token:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if isinstance(body, dict):
                    token = str(body.get("access_token") or body.get("token") or "")
            if not token:
                self._remember_login_error(
                    SourceUnavailableError("Реестр Росаккредитации не вернул токен")
                )
                raise self._login_error
            if token.lower().startswith("bearer "):
                token = token[7:]
            self._token = token
            self._login_error = None
            log_step(f"{log_prefix}: токен получен")

    def _remember_login_error(self, error: SourceUnavailableError) -> None:
        self._login_error = error
        self._login_error_at = time.monotonic()


def fsa_list_payload(
    column: str,
    term: str,
    *,
    size: int,
    sort_column: str = "date",
    active_only: bool = False,
    status_ids: list[int] | None = None,
    tech_reg_ids: list[int] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    filt: dict[str, Any] = {
        "idTechReg": list(tech_reg_ids or []),
        "regDate": {"minDate": "", "maxDate": ""},
        "endDate": {
            "minDate": active_end_min(as_of) if active_only else "",
            "maxDate": "",
        },
        "columnsSearch": [
            {"name": column, "search": term, "type": 0, "translated": False}
        ],
    }
    if active_only:
        filt["status"] = list(status_ids or acting_status_ids(None))
    return {
        "size": size,
        "page": 0,
        "filter": filt,
        "columnsSort": [{"column": sort_column, "sort": "DESC"}],
    }


async def fetch_fsa_product_items(
    session: FsaSession,
    query: ProductSearchQuery,
    *,
    column: str,
    size: int,
    sort_column: str,
    list_path: str,
    referer_path: str,
    log_prefix: str,
    load_identifiers: Callable[[], Awaitable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    identifiers = await load_identifiers()
    status_ids = acting_status_ids(identifiers)
    tech_reg_ids = tech_reg_ids_for_query(query, identifiers)
    for term in fsa_search_terms(query):
        log_step(f"{log_prefix}: поиск по продукции «{term}»")
        items = await _product_page(
            session,
            term,
            column=column,
            size=size,
            sort_column=sort_column,
            list_path=list_path,
            referer_path=referer_path,
            log_prefix=log_prefix,
            status_ids=status_ids,
            tech_reg_ids=[],
        )
        if items is None and tech_reg_ids:
            log_step(f"{log_prefix}: таймаут, повтор с техническим регламентом")
            items = await _product_page(
                session,
                term,
                column=column,
                size=size,
                sort_column=sort_column,
                list_path=list_path,
                referer_path=referer_path,
                log_prefix=log_prefix,
                status_ids=status_ids,
                tech_reg_ids=tech_reg_ids,
                raise_timeout=True,
            )
        if items:
            log_step(f"{log_prefix}: записей в ответе: {len(items)}")
            return items
        if items is None:
            raise SourceUnavailableError("Реестр Росаккредитации не ответил вовремя")
    return []


async def _product_page(
    session: FsaSession,
    term: str,
    *,
    column: str,
    size: int,
    sort_column: str,
    list_path: str,
    referer_path: str,
    log_prefix: str,
    status_ids: list[int],
    tech_reg_ids: list[int],
    raise_timeout: bool = False,
) -> list[dict[str, Any]] | None:
    payload = fsa_list_payload(
        column,
        term,
        size=size,
        sort_column=sort_column,
        active_only=True,
        status_ids=status_ids,
        tech_reg_ids=tech_reg_ids,
    )
    try:
        data = await session.api_json(
            "POST",
            list_path,
            json_body=payload,
            referer_path=referer_path,
            log_prefix=log_prefix,
        )
    except SourceUnavailableError as exc:
        if raise_timeout or not is_fsa_timeout(exc):
            raise
        return None
    return fsa_items(data)


async def load_fsa_identifiers(
    session: FsaSession,
    *,
    path: str,
    referer_path: str,
    log_prefix: str,
) -> dict[str, Any]:
    try:
        data = await session.api_json(
            "GET",
            path,
            referer_path=referer_path,
            log_prefix=log_prefix,
        )
    except SourceUnavailableError:
        return {}
    return data if isinstance(data, dict) else {}


def fsa_status_names(identifiers: dict[str, Any]) -> dict[str, str]:
    return id_name_map(identifiers.get("status"))


def fsa_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def fsa_search_terms(query: ProductSearchQuery) -> list[str]:
    return contiguous_search_terms(query)


def fsa_product_name(item: dict[str, Any]) -> str | None:
    for key in ("productFullName", "fullName", "productName"):
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
