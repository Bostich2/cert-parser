from __future__ import annotations

import time
from urllib.parse import quote

import httpx

from cert_parser.config import Settings
from cert_parser.domain.certificate_number import compact_number, numbers_match
from cert_parser.domain.errors import (
    AmbiguousMatchError,
    CertificateNotFoundError,
    SourceUnavailableError,
)
from cert_parser.domain.models import CertificateNumber, RegistryRecord
from cert_parser.domain.ports import RegistryProvider
from cert_parser.infrastructure.registries.matching import is_safe_contained_match
from cert_parser.infrastructure.registries.kazakhstan_html import (
    EoknoRow,
    extract_search_form,
    is_certificate_row,
    parse_result_rows,
    row_valid_from,
    row_valid_until,
    status_label,
)
from cert_parser.logging_setup import log_step


class KazakhstanProvider(RegistryProvider):
    """Kazakhstan: eokno.gov.kz first, tech.eaeunion.org OData as fallback."""

    def __init__(
        self,
        eokno: EoknoProvider,
        eaeu: RegistryProvider,
    ) -> None:
        self._eokno = eokno
        self._eaeu = eaeu

    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        try:
            return await self._eokno.lookup(number)
        except CertificateNotFoundError:
            log_step("KZ: eokno.gov.kz — не найден, пробуем tech.eaeunion.org")
            return await self._eaeu.lookup(number)
        except SourceUnavailableError as exc:
            log_step(
                f"KZ: eokno.gov.kz недоступен ({exc.message}), пробуем tech.eaeunion.org"
            )
            return await self._eaeu.lookup(number)

    async def ping(self) -> bool:
        eokno_ok = await self._eokno.ping()
        eaeu_ok = await self._eaeu.ping()
        return eokno_ok or eaeu_ok


class EoknoProvider(RegistryProvider):
    """Kazakhstan EAEU certificates via eokno.gov.kz JSF public register."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._url = settings.eokno_register_url

    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        form_html = await self._get_text(self._url)
        form = extract_search_form(form_html)
        if form is None:
            log_step("KZ: не удалось разобрать форму поиска (нет ViewState или поля фильтра)")
            raise SourceUnavailableError("Реестр eokno.gov.kz вернул неожиданную форму поиска")
        log_step(
            f"KZ: форма {form.form_id}, поле фильтра {form.number_filter_name}"
        )
        payload = _build_filter_payload(form, number.normalized)
        result_html = await self._post_text(self._url, payload)
        rows = [row for row in parse_result_rows(result_html) if is_certificate_row(row)]
        log_step(f"KZ: сертификатов в таблице: {len(rows)}")
        if rows:
            preview = ", ".join(row.official_number for row in rows[:5])
            log_step(f"KZ: номера в выборке: {preview}")
        match = _pick_row(rows, number)
        log_step(
            f"KZ: выбрана запись {match.official_number}, статус {match.status_raw or '—'}"
        )
        code, label = status_label(match.status_raw)
        registry_id = match.registry_id or match.official_number
        return RegistryRecord(
            url=_card_url(self._url, number.normalized, match.registry_id),
            valid_from=row_valid_from(match),
            valid_until=row_valid_until(match),
            status_code=code,
            status_label=label,
            registry_id=registry_id,
            official_number=match.official_number,
        )

    async def ping(self) -> bool:
        try:
            response = await self._client.get(self._url)
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    async def _get_text(self, url: str) -> str:
        timeout = _client_timeout(self._client)
        log_step(f"KZ: GET страницы реестра, лимит {timeout}")
        return await self._request("GET", url)

    async def _post_text(self, url: str, data: dict[str, str]) -> str:
        timeout = _client_timeout(self._client)
        log_step(
            f"KZ: POST фильтра по номеру (JSF, может занять почти весь лимит {timeout})"
        )
        return await self._request(
            "POST",
            url,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Faces-Request": "partial/ajax",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": url,
            },
        )

    async def _request(
        self,
        method: str,
        url: str,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        started = time.perf_counter()
        try:
            response = await self._client.request(method, url, data=data, headers=headers)
        except httpx.TimeoutException as exc:
            log_step(f"KZ: {method} таймаут после {_elapsed(started)}")
            raise SourceUnavailableError("Реестр eokno.gov.kz не ответил вовремя") from exc
        except httpx.HTTPError as exc:
            log_step(f"KZ: {method} сеть: {exc}")
            raise SourceUnavailableError("Реестр eokno.gov.kz недоступен") from exc
        log_step(
            f"KZ: {method} HTTP {response.status_code} за {_elapsed(started)}, "
            f"{len(response.content)} байт"
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SourceUnavailableError("Реестр eokno.gov.kz вернул ошибку") from exc
        return response.text


def _elapsed(started: float) -> str:
    return f"{time.perf_counter() - started:.1f} с"


def _client_timeout(client: httpx.AsyncClient) -> str:
    timeout = client.timeout
    value = timeout.read if timeout.read is not None else timeout.connect
    if value is None:
        return "без лимита"
    return f"{value:.0f} с"


def _build_filter_payload(form, term: str) -> dict[str, str]:
    table_id = _table_id(form.number_filter_name, form.form_id)
    return {
        "javax.faces.partial.ajax": "true",
        "javax.faces.source": table_id,
        "javax.faces.partial.execute": table_id,
        "javax.faces.partial.render": table_id,
        table_id: table_id,
        form.number_filter_name: term,
        form.form_id: form.form_id,
        "javax.faces.ViewState": form.view_state,
    }


def _table_id(filter_name: str, form_id: str) -> str:
    parts = filter_name.split(":")
    if "listTable" in parts:
        index = parts.index("listTable")
        return ":".join(parts[: index + 1])
    if len(parts) >= 2:
        return ":".join(parts[:-1])
    return form_id


def _pick_row(rows: list[EoknoRow], number: CertificateNumber) -> EoknoRow:
    exact = [row for row in rows if _row_matches(row, number)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousMatchError(number.normalized)

    contained = [row for row in rows if _row_contains(row, number)]
    if len(contained) == 1:
        return contained[0]
    if len(contained) > 1:
        raise AmbiguousMatchError(number.normalized)
    if not rows:
        raise CertificateNotFoundError(number.normalized)
    raise CertificateNotFoundError(number.normalized)


def _row_matches(row: EoknoRow, number: CertificateNumber) -> bool:
    return numbers_match(row.official_number, number.normalized) or numbers_match(
        row.official_number, number.search_term
    )


def _row_contains(row: EoknoRow, number: CertificateNumber) -> bool:
    doc_compact = compact_number(row.official_number)
    return is_safe_contained_match(
        number.compact,
        doc_compact,
        compact_number(number.search_term),
    )


def _card_url(register_url: str, number: str, registry_id: str) -> str:
    encoded = quote(number)
    if registry_id:
        return f"{register_url}?rk={quote(registry_id)}&q={encoded}"
    return f"{register_url}?q={encoded}"
