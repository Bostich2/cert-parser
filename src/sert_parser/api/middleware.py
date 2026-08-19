"""HTTP middleware for security and authentication."""

from __future__ import annotations

from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from sert_parser.api.auth import get_session_user, is_admin, validate_csrf_token
from sert_parser.config import Settings

PUBLIC_PATHS = frozenset({"/login", "/health/live"})
ADMIN_PATHS = frozenset({"/api/cache/clear", "/api/reload", "/health"})
_ADMIN_DISABLED_DETAIL = "Административные операции доступны только при включённой аутентификации"


def _accepts_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "*/*" in accept and "application/json" not in accept


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        settings: Settings = request.app.state.settings
        path = request.url.path

        if not settings.auth_enabled:
            if path in ADMIN_PATHS:
                return JSONResponse({"detail": _ADMIN_DISABLED_DETAIL}, status_code=403)
            return await call_next(request)

        if path in PUBLIC_PATHS or path.startswith("/static/"):
            return await call_next(request)
        if path == "/logout" and request.method == "POST":
            user = get_session_user(request)
            if user is None:
                return JSONResponse({"detail": "Требуется авторизация"}, status_code=401)
            form = await request.form()
            if not validate_csrf_token(request, form.get("csrf_token")):
                return JSONResponse({"detail": "Неверный CSRF-токен"}, status_code=400)
            return await call_next(request)

        user = get_session_user(request)
        if user is None:
            if _accepts_html(request) and request.method == "GET":
                next_url = quote(path, safe="/")
                return RedirectResponse(url=f"/login?next={next_url}", status_code=303)
            return JSONResponse({"detail": "Требуется авторизация"}, status_code=401)

        if path in ADMIN_PATHS and not is_admin(user):
            return JSONResponse({"detail": "Недостаточно прав"}, status_code=403)

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; frame-ancestors 'none'",
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        settings: Settings = request.app.state.settings
        if settings.env == "production":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response
