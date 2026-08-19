from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from cert_parser.config import Settings
from cert_parser.domain.errors import CertificateNotFoundError, SourceUnavailableError
from cert_parser.infrastructure.registries.pdf_urls import build_certificate_pdf_proxy_url
from cert_parser.logging_setup import log_step

_POLL_ATTEMPTS = 30
_POLL_DELAY_SECONDS = 0.5


def build_eaeu_pdf_proxy_url(registry_id: str) -> str:
    return build_certificate_pdf_proxy_url("eaeu", registry_id)


def _export_query(registry_id: str) -> str:
    object_id = f"ObjectId('{registry_id}')"
    return json.dumps({"$and": [{"_id": {"$eq": object_id}}]}, ensure_ascii=False)


def _export_payload(registry_id: str, settings: Settings) -> dict[str, Any]:
    return {
        "registrykey": settings.eaeu_card_pdf_registry_key,
        "section": settings.eaeu_card_pdf_section,
        "registry": settings.eaeu_card_pdf_registry,
        "data": {
            "query": _export_query(registry_id),
            "collection": settings.eaeu_card_pdf_collection,
        },
        "id": settings.eaeu_card_pdf_process_id,
    }


async def fetch_eaeu_card_pdf(
    client: httpx.AsyncClient,
    registry_id: str,
    settings: Settings,
) -> bytes:
    base = settings.eaeu_platform_url.rstrip("/")
    process_id = settings.eaeu_card_pdf_process_id
    payload = _export_payload(registry_id, settings)
    log_step(f"EAEU PDF: export card id={registry_id}")
    try:
        response = await client.post(
            f"{base}/nonauthorizedplatform/executewithjson",
            params={"jobid": process_id},
            content=json.dumps(payload, ensure_ascii=False),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        start_body = response.json()
    except httpx.HTTPError as exc:
        raise SourceUnavailableError("Реестр tech.eaeunion.org недоступен") from exc
    except ValueError as exc:
        raise SourceUnavailableError("Реестр tech.eaeunion.org вернул некорректный ответ") from exc

    instance_id = str(start_body.get("instanceid") or "")
    if not instance_id:
        raise SourceUnavailableError("Реестр tech.eaeunion.org не запустил экспорт PDF")

    await _wait_for_platform_ready(client, base, instance_id)
    file_id = await _resolve_file_id(client, base, instance_id)
    return await _download_platform_file(client, base, file_id, instance_id)


async def _wait_for_platform_ready(client: httpx.AsyncClient, base: str, instance_id: str) -> None:
    for _ in range(_POLL_ATTEMPTS):
        status = await _platform_status(client, base, instance_id)
        code = status.get("status")
        if code in (0, 1, 10, 11):
            return
        if code not in (None, 2, 3):
            raise SourceUnavailableError("Реестр tech.eaeunion.org не смог сформировать PDF")
        await asyncio.sleep(_POLL_DELAY_SECONDS)
    raise SourceUnavailableError("Превышено время ожидания PDF из реестра tech.eaeunion.org")


async def _platform_status(client: httpx.AsyncClient, base: str, instance_id: str) -> dict[str, Any]:
    response = await client.get(
        f"{base}/nonauthorizedplatform/status",
        params={"instanceid": instance_id},
    )
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {}


async def _resolve_file_id(client: httpx.AsyncClient, base: str, instance_id: str) -> str:
    response = await client.get(
        f"{base}/nonauthorizedplatform/gettoken",
        params={"instanceid": instance_id},
    )
    response.raise_for_status()
    body = response.json()
    parameters = body.get("parameters") if isinstance(body, dict) else None
    if not isinstance(parameters, list):
        raise SourceUnavailableError("Реестр tech.eaeunion.org не вернул файл PDF")
    for item in parameters:
        if isinstance(item, dict) and item.get("name") == "fileid":
            file_id = str(item.get("stringvalue") or item.get("value") or "")
            if file_id:
                return file_id
    raise CertificateNotFoundError("PDF сертификата не найден в реестре tech.eaeunion.org")


async def _download_platform_file(
    client: httpx.AsyncClient,
    base: str,
    file_id: str,
    instance_id: str,
) -> bytes:
    response = await client.get(
        f"{base}/nonauthorizedplatform/filedownload",
        params={"id": file_id, "instanceid": instance_id},
    )
    response.raise_for_status()
    payload = response.content
    if not payload.startswith(b"%PDF-"):
        raise SourceUnavailableError("Реестр tech.eaeunion.org вернул не PDF")
    return payload
