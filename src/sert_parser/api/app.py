from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from sert_parser.api.auth import (
    authenticate,
    ensure_csrf_token,
    get_session_user,
    is_admin,
    login_session_user,
    validate_csrf_token,
)
from sert_parser.api.middleware import AuthMiddleware, SecurityHeadersMiddleware
from sert_parser.api.security import (
    get_client_address,
    read_upload_limited,
    validate_pdf_content,
    validate_xlsx_content,
)

from sert_parser.api.mappers import lookup_result_to_api_dict
from sert_parser.api.ndjson import STREAM_HEADERS, stream_async_work
from sert_parser.application.export_service import ExportService
from sert_parser.application.extract_service import ExtractService
from sert_parser.application.lookup_service import LookupService
from sert_parser.bootstrap import (
    close_runtime,
    configure_runtime,
    reset_runtime_ocr_engines,
    shutdown_runtime,
)
from sert_parser.config import Settings, get_settings
from sert_parser.domain.errors import PdfReadError, XlsxReadError
from sert_parser.domain.ports import LookupCache
from sert_parser.logging_setup import current_steps, logger, start_steps
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


def _require_extract_service(request: Request) -> ExtractService:
    if getattr(request.app.state, "reload_in_progress", False):
        raise HTTPException(status_code=503, detail=_RELOAD_BUSY_DETAIL)
    service = request.app.state.extract_service
    if service is None:
        raise HTTPException(status_code=503, detail=_RELOAD_BUSY_DETAIL)
    return service


def _require_export_service(request: Request) -> ExportService:
    service = request.app.state.export_service
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


def _safe_next_url(next_url: str | None) -> str:
    if not next_url:
        return "/"
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    return next_url


def create_app() -> FastAPI:
    settings = get_settings()
    limiter = Limiter(key_func=get_client_address)
    session_secret = settings.auth_secret_key.strip() if settings.auth_enabled else secrets.token_hex(32)
    app = FastAPI(
        title="Парсер сертификатов ЕАЭС",
        version=get_version(),
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(AuthMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        max_age=settings.auth_session_max_age,
        https_only=settings.auth_secure_cookies,
        same_site="lax",
    )
    app.add_middleware(SecurityHeadersMiddleware)
    if settings.allowed_host_list != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.add_api_route("/", index_page, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route(
        "/login",
        limiter.limit(lambda: get_settings().rate_limit_login)(login_page),
        methods=["GET", "POST"],
        response_class=HTMLResponse,
        response_model=None,
    )
    app.add_api_route("/logout", logout, methods=["POST"])
    app.add_api_route("/api/lookup", limiter.limit(_lookup_rate_limit)(lookup_certificates), methods=["POST"])
    app.add_api_route("/api/lookup/stream", limiter.limit(_lookup_rate_limit)(lookup_certificates_stream), methods=["POST"])
    app.add_api_route("/api/lookup-pdf", limiter.limit(_upload_rate_limit)(lookup_pdf), methods=["POST"])
    app.add_api_route("/api/extract-pdf", limiter.limit(_upload_rate_limit)(extract_pdf), methods=["POST"])
    app.add_api_route("/api/extract-pdf/stream", limiter.limit(_upload_rate_limit)(extract_pdf_stream), methods=["POST"])
    app.add_api_route("/api/extract-xlsx", limiter.limit(_upload_rate_limit)(extract_xlsx), methods=["POST"])
    app.add_api_route("/api/export-xlsx", limiter.limit(_lookup_rate_limit)(export_xlsx), methods=["POST"])
    app.add_api_route("/api/cache/clear", clear_cache, methods=["POST"])
    app.add_api_route("/api/reload", reload_service, methods=["POST"])
    app.add_api_route("/health/live", health_live, methods=["GET"])
    app.add_api_route("/health", health, methods=["GET"])
    return app


async def index_page(request: Request) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    user = get_session_user(request)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "version": get_version(),
            "auth_enabled": settings.auth_enabled,
            "username": user.username if user else None,
            "is_admin": is_admin(user) if settings.auth_enabled else False,
            "csrf_token": ensure_csrf_token(request) if settings.auth_enabled and user else "",
        },
    )


async def login_page(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(default=""),
    csrf_token: str = Form(default=""),
    next_url: str = Form(default="/"),
) -> Response:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return RedirectResponse(url="/", status_code=303)

    query_next = request.query_params.get("next", "/")
    if request.method == "GET":
        existing = get_session_user(request)
        if existing is not None:
            return RedirectResponse(url=_safe_next_url(query_next), status_code=303)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "version": get_version(),
                "csrf_token": ensure_csrf_token(request),
                "next_url": _safe_next_url(query_next),
                "error": None,
            },
        )

    if not validate_csrf_token(request, csrf_token):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "version": get_version(),
                "csrf_token": ensure_csrf_token(request),
                "next_url": _safe_next_url(next_url),
                "error": "Неверный CSRF-токен. Обновите страницу и попробуйте снова.",
            },
            status_code=400,
        )

    directory = getattr(request.app.state, "auth_users", {})
    user = authenticate(username, password, directory)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "version": get_version(),
                "csrf_token": ensure_csrf_token(request),
                "next_url": _safe_next_url(next_url),
                "error": "Неверный логин или пароль",
            },
            status_code=401,
        )

    login_session_user(request, user)
    return RedirectResponse(url=_safe_next_url(next_url), status_code=303)


async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


def _lookup_rate_limit() -> str:
    return get_settings().rate_limit_lookup


def _upload_rate_limit() -> str:
    return get_settings().rate_limit_upload


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
    return {"results": [lookup_result_to_api_dict(item) for item in results]}


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
        return {"type": "done", "result": lookup_result_to_api_dict(result)}

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
    extract_service = _require_extract_service(request)
    payload = await read_upload_limited(file, settings.pdf_max_bytes)
    validate_pdf_content(payload)
    start_steps()
    logger.info("%s: %s, %s байт", log_prefix, file.filename, len(payload))
    try:
        numbers = await asyncio.wait_for(
            asyncio.to_thread(extract_service.extract_from_pdf, payload),
            timeout=settings.pdf_processing_timeout_seconds,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail="Превышено время обработки PDF") from exc
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
    extract_service = _require_extract_service(request)
    payload = await read_upload_limited(file, settings.pdf_max_bytes)
    validate_pdf_content(payload)
    logger.info("POST /api/extract-pdf/stream: %s, %s байт", file.filename, len(payload))
    timeout = settings.pdf_processing_timeout_seconds

    async def work() -> dict:
        try:
            numbers = await asyncio.wait_for(
                asyncio.to_thread(extract_service.extract_from_pdf, payload),
                timeout=timeout,
            )
        except TimeoutError:
            return {"type": "error", "detail": "Превышено время обработки PDF"}
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
        stream_async_work(work),
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
        "results": [lookup_result_to_api_dict(item) for item in results],
        "error": None,
        "error_code": None,
        "extract_trace": extract_trace,
        **_pdf_limit_fields(limit_meta),
    }


async def extract_xlsx(request: Request, file: UploadFile = File(...)) -> dict:
    settings: Settings = request.app.state.settings
    extract_service = _require_extract_service(request)
    payload = await read_upload_limited(file, settings.xlsx_max_bytes)
    validate_xlsx_content(payload)
    logger.info("POST /api/extract-xlsx: %s, %s байт", file.filename, len(payload))
    try:
        numbers = extract_service.extract_from_xlsx(payload)
    except XlsxReadError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    if not numbers:
        return {
            "numbers": [],
            "error": "В Excel не найдены номера в столбце A",
            "error_code": "no_numbers_in_xlsx",
        }
    return {"numbers": numbers, "error": None, "error_code": None}


async def export_xlsx(request: Request, payload: ExportRequest) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    if len(payload.results) > settings.max_batch_size:
        raise HTTPException(
            status_code=413,
            detail=f"Слишком много строк для экспорта. Максимум {settings.max_batch_size}",
        )
    export_service = _require_export_service(request)
    rows = [item.model_dump() for item in payload.results]
    content = export_service.build_results_xlsx(rows)
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
    cache: LookupCache = request.app.state.cache
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
            reset_runtime_ocr_engines()
            await configure_runtime(app)
        finally:
            app.state.reload_in_progress = False
        await close_runtime(old_clients, old_cache)
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


async def health_live(request: Request) -> dict:
    return {"status": "ok"}


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
