from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from sert_parser.application.country_router import CountryRouter
from sert_parser.application.lookup_service import LookupService
from sert_parser.config import Settings, get_settings
from sert_parser.domain.errors import PdfReadError, XlsxReadError
from sert_parser.infrastructure.cache import SqliteLookupCache
from sert_parser.infrastructure.http import build_http_client
from sert_parser.infrastructure.pdf import extract_numbers_from_pdf, reset_ocr_engines
from sert_parser.infrastructure.xlsx import build_results_xlsx, extract_numbers_from_xlsx
from sert_parser.infrastructure.registries.armenia import ArmeniaProvider
from sert_parser.infrastructure.registries.belarus import BelgissProvider
from sert_parser.infrastructure.registries.kazakhstan import EoknoProvider
from sert_parser.infrastructure.registries.kyrgyzstan import SwisProvider
from sert_parser.infrastructure.registries.russia import FsaProvider
from sert_parser.api.ndjson import STREAM_HEADERS, stream_async_work, stream_sync_work
from sert_parser.logging_setup import configure_logging, current_steps, logger, start_steps
from sert_parser.version import get_version

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


class LookupRequest(BaseModel):
    numbers: list[str] = Field(min_length=1)


class ExportRow(BaseModel):
    query: str | None = None
    normalized: str | None = None
    country_code: str | None = None
    url: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    status: str | None = None
    status_code: str | None = None
    registry_id: str | None = None
    official_number: str | None = None
    error: str | None = None
    error_code: str | None = None
    cached: bool = False


class ExportRequest(BaseModel):
    results: list[ExportRow] = Field(min_length=1)


_reload_lock = asyncio.Lock()
RELOAD_WAIT_TIMEOUT_SECONDS = 30.0
_RELOAD_BUSY_DETAIL = "Сервис перезапускается, повторите запрос"
_RELOAD_BLOCKED_DETAIL = (
    "Не удалось перезапустить: активны запросы поиска. Повторите через несколько секунд"
)


async def configure_runtime(app: FastAPI) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(settings.log_level)
    cache = SqliteLookupCache(settings.cache_path, settings.cache_ttl_seconds)
    belgiss_client = build_http_client(settings)
    fsa_client = build_http_client(
        settings,
        extra_headers={
            "Origin": settings.fsa_base_url.rstrip("/"),
            "Referer": f"{settings.fsa_base_url.rstrip('/')}/rss/certificate",
        },
    )
    eokno_client = build_http_client(
        settings,
        extra_headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": settings.eokno_register_url,
        },
    )
    swis_client = build_http_client(
        settings,
        extra_headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{settings.swis_base_url.rstrip('/')}/Registry/CertificateOfConformity",
        },
    )
    eaeu_client = build_http_client(
        settings,
        extra_headers={
            "Accept": "application/json",
            "Referer": "https://tech.eaeunion.org/tech/registers/35-1/ru/registryList/conformityDocs",
        },
    )
    belgiss = BelgissProvider(belgiss_client, settings)
    fsa = FsaProvider(fsa_client, settings)
    eokno = EoknoProvider(eokno_client, settings)
    swis = SwisProvider(swis_client, settings)
    armenia = ArmeniaProvider(eaeu_client, settings)
    router = CountryRouter({"BY": belgiss, "RU": fsa, "KZ": eokno, "KG": swis, "AM": armenia})
    app.state.settings = settings
    app.state.cache = cache
    app.state.http_clients = [belgiss_client, fsa_client, eokno_client, swis_client, eaeu_client]
    app.state.providers = {
        "belgiss": belgiss,
        "fsa": fsa,
        "eokno": eokno,
        "swis": swis,
        "eaeu": armenia,
    }
    app.state.lookup_service = LookupService(router, cache, settings)
    app.state.runtime_generation = int(getattr(app.state, "runtime_generation", 0)) + 1


async def shutdown_runtime(app: FastAPI) -> None:
    await _close_runtime(
        getattr(app.state, "http_clients", []) or [],
        getattr(app.state, "cache", None),
    )
    app.state.http_clients = []
    app.state.providers = {}
    app.state.lookup_service = None
    app.state.cache = None


async def _close_runtime(
    http_clients: list,
    cache: SqliteLookupCache | None,
) -> None:
    for client in http_clients:
        await client.aclose()
    if cache is not None:
        cache.close()


async def _wait_for_active_lookups(app: FastAPI) -> bool:
    deadline = time.monotonic() + RELOAD_WAIT_TIMEOUT_SECONDS
    while int(getattr(app.state, "active_lookups", 0)) > 0:
        if time.monotonic() >= deadline:
            logger.warning(
                "POST /api/reload: timeout waiting for %s active lookup(s)",
                app.state.active_lookups,
            )
            return False
        await asyncio.sleep(0.05)
    return True


def _reserve_lookup_slot(request: Request) -> None:
    request.app.state.active_lookups = int(getattr(request.app.state, "active_lookups", 0)) + 1


def _release_lookup_slot(request: Request) -> None:
    request.app.state.active_lookups = max(
        0,
        int(getattr(request.app.state, "active_lookups", 0)) - 1,
    )


def _require_lookup_service(request: Request) -> LookupService:
    if getattr(request.app.state, "reload_in_progress", False):
        raise HTTPException(status_code=503, detail=_RELOAD_BUSY_DETAIL)
    service = request.app.state.lookup_service
    if service is None:
        raise HTTPException(status_code=503, detail=_RELOAD_BUSY_DETAIL)
    return service


async def _run_lookup(request: Request, coro):
    _reserve_lookup_slot(request)
    try:
        return await coro
    finally:
        _release_lookup_slot(request)


def _limit_pdf_numbers(
    numbers: list[str],
    max_batch_size: int,
) -> tuple[list[str], dict[str, object]]:
    total_found = len(numbers)
    if total_found <= max_batch_size:
        return numbers, {"truncated": False, "total_found": total_found}
    warning = (
        f"В PDF найдено {total_found} номеров, обработаны первые {max_batch_size}"
    )
    return numbers[:max_batch_size], {
        "truncated": True,
        "total_found": total_found,
        "warning": warning,
    }


def _pdf_limit_fields(meta: dict[str, object]) -> dict[str, object]:
    if not meta.get("truncated"):
        return {}
    return {
        "truncated": True,
        "total_found": meta["total_found"],
        "warning": meta.get("warning"),
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.runtime_generation = 0
    app.state.reload_in_progress = False
    app.state.active_lookups = 0
    await configure_runtime(app)
    try:
        yield
    finally:
        await shutdown_runtime(app)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Парсер сертификатов ЕАЭС",
        version=get_version(),
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.add_api_route("/", index_page, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/api/lookup", lookup_certificates, methods=["POST"])
    app.add_api_route("/api/lookup/stream", lookup_certificates_stream, methods=["POST"])
    app.add_api_route("/api/lookup-pdf", lookup_pdf, methods=["POST"])
    app.add_api_route("/api/extract-pdf", extract_pdf, methods=["POST"])
    app.add_api_route("/api/extract-pdf/stream", extract_pdf_stream, methods=["POST"])
    app.add_api_route("/api/extract-xlsx", extract_xlsx, methods=["POST"])
    app.add_api_route("/api/export-xlsx", export_xlsx, methods=["POST"])
    app.add_api_route("/api/cache/clear", clear_cache, methods=["POST"])
    app.add_api_route("/api/reload", reload_service, methods=["POST"])
    app.add_api_route("/health", health, methods=["GET"])
    return app


async def index_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"version": get_version()},
    )


async def lookup_certificates(request: Request, payload: LookupRequest) -> dict:
    settings: Settings = request.app.state.settings
    numbers = [item for item in payload.numbers if str(item).strip()]
    if not numbers:
        raise HTTPException(status_code=400, detail="Передайте хотя бы один номер сертификата")
    if len(numbers) > settings.max_batch_size:
        raise HTTPException(
            status_code=400,
            detail=f"Слишком много номеров. Максимум {settings.max_batch_size}",
        )
    service = _require_lookup_service(request)
    logger.info("POST /api/lookup: %s номер(ов)", len(numbers))
    results = await _run_lookup(request, service.lookup_many(numbers))
    return {"results": [item.to_api_dict() for item in results]}


async def lookup_certificates_stream(request: Request, payload: LookupRequest) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    numbers = [item for item in payload.numbers if str(item).strip()]
    if not numbers:
        raise HTTPException(status_code=400, detail="Передайте хотя бы один номер сертификата")
    if len(numbers) > 1:
        raise HTTPException(status_code=400, detail="Поток поддерживает один номер за запрос")
    if len(numbers) > settings.max_batch_size:
        raise HTTPException(
            status_code=400,
            detail=f"Слишком много номеров. Максимум {settings.max_batch_size}",
        )
    service = _require_lookup_service(request)
    raw = numbers[0]
    logger.info("POST /api/lookup/stream: %s", raw)
    _reserve_lookup_slot(request)

    async def work() -> dict:
        result = await service.lookup_one(raw)
        return {"type": "done", "result": result.to_api_dict()}

    async def stream_body():
        try:
            async for chunk in stream_async_work(work):
                yield chunk
        finally:
            _release_lookup_slot(request)

    return StreamingResponse(
        stream_body(),
        media_type="application/x-ndjson",
        headers=STREAM_HEADERS,
    )


async def _extract_pdf_payload(
    request: Request,
    file: UploadFile,
    *,
    log_prefix: str,
) -> tuple[list[str], list[str], dict[str, object]]:
    settings: Settings = request.app.state.settings
    payload = await file.read()
    start_steps()
    logger.info("%s: %s, %s байт", log_prefix, file.filename, len(payload))
    try:
        numbers = extract_numbers_from_pdf(payload, settings)
    except PdfReadError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    extract_trace = current_steps()
    numbers, limit_meta = _limit_pdf_numbers(numbers, settings.max_batch_size)
    return numbers, extract_trace, limit_meta


async def extract_pdf(request: Request, file: UploadFile = File(...)) -> dict:
    numbers, extract_trace, limit_meta = await _extract_pdf_payload(
        request,
        file,
        log_prefix="POST /api/extract-pdf",
    )
    if not numbers:
        return {
            "numbers": [],
            "error": "В PDF не найден номер сертификата",
            "error_code": "no_numbers_in_pdf",
            "extract_trace": extract_trace,
        }
    return {
        "numbers": numbers,
        "error": None,
        "error_code": None,
        "extract_trace": extract_trace,
        **_pdf_limit_fields(limit_meta),
    }


async def extract_pdf_stream(request: Request, file: UploadFile = File(...)) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    payload = await file.read()
    logger.info("POST /api/extract-pdf/stream: %s, %s байт", file.filename, len(payload))

    def work() -> dict:
        try:
            numbers = extract_numbers_from_pdf(payload, settings)
        except PdfReadError as exc:
            return {"type": "error", "detail": exc.message}
        numbers, limit_meta = _limit_pdf_numbers(numbers, settings.max_batch_size)
        if not numbers:
            return {
                "type": "done",
                "numbers": [],
                "error": "В PDF не найден номер сертификата",
                "error_code": "no_numbers_in_pdf",
            }
        return {
            "type": "done",
            "numbers": numbers,
            "error": None,
            "error_code": None,
            **_pdf_limit_fields(limit_meta),
        }

    return StreamingResponse(
        stream_sync_work(work),
        media_type="application/x-ndjson",
        headers=STREAM_HEADERS,
    )


async def lookup_pdf(request: Request, file: UploadFile = File(...)) -> dict:
    numbers, extract_trace, limit_meta = await _extract_pdf_payload(
        request,
        file,
        log_prefix="POST /api/lookup-pdf",
    )
    if not numbers:
        return {
            "extracted_numbers": [],
            "results": [],
            "error": "В PDF не найден номер сертификата",
            "error_code": "no_numbers_in_pdf",
            "extract_trace": extract_trace,
        }
    service = _require_lookup_service(request)
    results = await _run_lookup(request, service.lookup_many(numbers))
    return {
        "extracted_numbers": numbers,
        "results": [item.to_api_dict() for item in results],
        "error": None,
        "error_code": None,
        "extract_trace": extract_trace,
        **_pdf_limit_fields(limit_meta),
    }


async def extract_xlsx(request: Request, file: UploadFile = File(...)) -> dict:
    settings: Settings = request.app.state.settings
    payload = await file.read()
    logger.info("POST /api/extract-xlsx: %s, %s байт", file.filename, len(payload))
    if len(payload) > settings.xlsx_max_bytes:
        max_mb = settings.xlsx_max_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"Excel больше {max_mb} МБ")
    try:
        numbers = extract_numbers_from_xlsx(
            payload,
            max_batch_size=settings.max_batch_size,
        )
    except XlsxReadError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    if not numbers:
        return {
            "numbers": [],
            "error": "В Excel не найдены номера в столбце A",
            "error_code": "no_numbers_in_xlsx",
        }
    return {"numbers": numbers, "error": None, "error_code": None}


async def export_xlsx(payload: ExportRequest) -> StreamingResponse:
    rows = [item.model_dump() for item in payload.results]
    content = build_results_xlsx(rows)
    headers = {
        "Content-Disposition": 'attachment; filename="sert-parser-results.xlsx"',
    }
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


async def clear_cache(request: Request) -> dict:
    if getattr(request.app.state, "reload_in_progress", False):
        raise HTTPException(status_code=503, detail=_RELOAD_BUSY_DETAIL)
    cache: SqliteLookupCache = request.app.state.cache
    deleted = cache.clear()
    logger.info("POST /api/cache/clear: removed %s entries", deleted)
    return {
        "deleted": deleted,
        "message": f"Кэш очищен ({deleted} записей)",
    }


async def reload_service(request: Request) -> dict:
    app = request.app
    async with _reload_lock:
        previous = int(getattr(app.state, "runtime_generation", 0))
        logger.info("POST /api/reload: generation %s", previous)
        app.state.reload_in_progress = True
        old_clients: list = []
        old_cache = None
        try:
            if not await _wait_for_active_lookups(app):
                raise HTTPException(status_code=409, detail=_RELOAD_BLOCKED_DETAIL)
            old_clients = list(getattr(app.state, "http_clients", []) or [])
            old_cache = getattr(app.state, "cache", None)
            reset_ocr_engines()
            await configure_runtime(app)
        finally:
            app.state.reload_in_progress = False
        await _close_runtime(old_clients, old_cache)
        generation = int(app.state.runtime_generation)
        logger.info("POST /api/reload: ready, generation %s, version %s", generation, get_version())
    version = get_version()
    return {
        "version": version,
        "generation": generation,
        "message": (
            f"Сервис перезапущен (v{version}, generation {generation}): "
            "HTTP-сессии, провайдеры и OCR сброшены"
        ),
    }


async def health(request: Request) -> dict:
    providers = request.app.state.providers
    statuses = {}
    for name, provider in providers.items():
        statuses[name] = "ok" if await provider.ping() else "unavailable"
    overall = "ok" if all(value == "ok" for value in statuses.values()) else "degraded"
    return {
        "status": overall,
        "version": get_version(),
        "generation": int(getattr(request.app.state, "runtime_generation", 0)),
        **statuses,
    }


app = create_app()
