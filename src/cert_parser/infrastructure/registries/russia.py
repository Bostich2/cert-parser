from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from cert_parser.config import Settings
from cert_parser.domain.certificate_number import compact_number, numbers_match
from cert_parser.domain.errors import (
    AmbiguousMatchError,
    CertificateNotFoundError,
    SourceUnavailableError,
)
from cert_parser.domain.models import CertificateNumber, RegistryRecord, parse_iso_date
from cert_parser.domain.ports import RegistryProvider
from cert_parser.infrastructure.registries.fsa_pdf import build_fsa_pdf_proxy_url
from cert_parser.infrastructure.registries.matching import is_safe_contained_match
from cert_parser.logging_setup import log_step

logger = logging.getLogger(__name__)

_UNAVAILABLE_403 = (
    "Реестр Росаккредитации недоступен (403). "
    "Нужен доступ из РФ или HTTPS_PROXY"
)


class FsaProvider(RegistryProvider):
    """Russia EAEU certificates via pub.fsa.gov.ru RSS API."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._base = settings.fsa_base_url.rstrip("/")
        self._username = settings.fsa_login_username
        self._password = settings.fsa_login_password
        self._token: str | None = None
        self._status_names: dict[str, str] | None = None

    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        items = await self._search(number.normalized)
        log_step(f"RU: записей в ответе: {len(items)}")
        match = _pick_item(items, number)
        log_step(f"RU: выбрана запись id={match.get('id')}, номер {match.get('number')}")
        registry_id = str(match.get("id") or "")
        if not registry_id:
            raise CertificateNotFoundError(number.normalized)
        status_code = str(match.get("idStatus") or "") or None
        status_label = await self._status_label(status_code)
        return RegistryRecord(
            url=f"{self._base}/rss/certificate/view/{registry_id}/baseInfo",
            valid_from=_first_date(match.get("startDate"), match.get("date"), match.get("regDate")),
            valid_until=parse_iso_date(_stringify(match.get("endDate"))),
            status_code=status_code,
            status_label=status_label,
            registry_id=registry_id,
            official_number=str(match.get("number") or number.normalized),
            pdf_url=build_fsa_pdf_proxy_url(registry_id),
        )

    async def ping(self) -> bool:
        try:
            await self._ensure_token()
            response = await self._client.get(f"{self._base}/rss/certificate")
            return response.status_code < 500
        except SourceUnavailableError:
            return False
        except httpx.HTTPError:
            return False

    async def _search(self, term: str) -> list[dict[str, Any]]:
        log_step(f"RU: POST /api/v1/rss/common/certificates/get, number={term}")
        payload = {
            "size": 10,
            "page": 0,
            "filter": {
                "idTechReg": [],
                "regDate": {"minDate": "", "maxDate": ""},
                "endDate": {"minDate": "", "maxDate": ""},
                "columnsSearch": [
                    {"name": "number", "search": term, "type": 0, "translated": False}
                ],
            },
            "columnsSort": [{"column": "date", "sort": "DESC"}],
        }
        data = await self._api_json(
            "POST",
            "/api/v1/rss/common/certificates/get",
            json_body=payload,
        )
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    async def _status_label(self, status_code: str | None) -> str:
        if not status_code:
            return "не указан"
        names = await self._identifiers()
        return names.get(status_code, status_code)

    async def _identifiers(self) -> dict[str, str]:
        if self._status_names is not None:
            return self._status_names
        data = await self._api_json("GET", "/api/v1/rss/common/identifiers")
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

    async def _api_json(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        await self._ensure_token()
        url = f"{self._base}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Origin": self._base,
            "Referer": f"{self._base}/rss/certificate",
            "Content-Type": "application/json",
        }
        try:
            response = await self._client.request(method, url, json=json_body, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("FSA request failed: %s", exc)
            raise SourceUnavailableError("Реестр Росаккредитации недоступен") from exc
        if response.status_code == 401 and retry_auth:
            self._token = None
            return await self._api_json(method, path, json_body=json_body, retry_auth=False)
        if response.status_code == 403:
            log_step("RU: HTTP 403 — нужен доступ из РФ или HTTPS_PROXY")
            raise SourceUnavailableError(_UNAVAILABLE_403)
        if response.status_code >= 400:
            log_step(f"RU: HTTP {response.status_code} для {path}")
            logger.warning("FSA HTTP %s for %s", response.status_code, url)
            raise SourceUnavailableError("Реестр Росаккредитации вернул ошибку")
        try:
            data = response.json()
        except ValueError as exc:
            raise SourceUnavailableError("Реестр Росаккредитации вернул некорректный ответ") from exc
        return data if isinstance(data, dict) else {}

    async def _ensure_token(self) -> None:
        if self._token:
            return
        log_step("RU: анонимный вход в pub.fsa.gov.ru")
        try:
            await self._client.get(f"{self._base}/rss/certificate")
            response = await self._client.post(
                f"{self._base}/login",
                json={"username": self._username, "password": self._password},
                headers={
                    "Origin": self._base,
                    "Referer": f"{self._base}/rss/certificate",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise SourceUnavailableError("Реестр Росаккредитации недоступен") from exc
        if response.status_code == 403:
            log_step("RU: HTTP 403 на /login — нужен доступ из РФ или HTTPS_PROXY")
            raise SourceUnavailableError(_UNAVAILABLE_403)
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
        log_step("RU: токен получен")


def _pick_item(items: list[dict[str, Any]], number: CertificateNumber) -> dict[str, Any]:
    exact = [
        item
        for item in items
        if numbers_match(str(item.get("number") or ""), number.normalized)
        or numbers_match(str(item.get("number") or ""), number.search_term)
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousMatchError(number.normalized)

    contained = [item for item in items if _item_contains(item, number)]
    if len(contained) == 1:
        return contained[0]
    if len(contained) > 1:
        raise AmbiguousMatchError(number.normalized)
    if not items:
        raise CertificateNotFoundError(number.normalized)
    raise CertificateNotFoundError(number.normalized)


def _item_contains(item: dict[str, Any], number: CertificateNumber) -> bool:
    doc_compact = compact_number(str(item.get("number") or ""))
    return is_safe_contained_match(
        number.compact,
        doc_compact,
        compact_number(number.search_term),
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
