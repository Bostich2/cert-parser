"""FastAPI dependencies for authentication."""

from __future__ import annotations

from fastapi import HTTPException, Request

from cert_parser.api.auth import SessionUser, get_session_user, is_admin
from cert_parser.config import Settings


def _auth_required(settings: Settings) -> bool:
    return settings.auth_enabled


def require_user(request: Request) -> SessionUser | None:
    settings: Settings = request.app.state.settings
    if not _auth_required(settings):
        return None
    user = get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return user


def require_admin(request: Request) -> SessionUser | None:
    settings: Settings = request.app.state.settings
    if not _auth_required(settings):
        return None
    user = get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return user
