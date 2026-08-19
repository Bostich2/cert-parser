"""Session-based authentication helpers."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Literal

import bcrypt
from starlette.requests import Request

from cert_parser.config import Settings

Role = Literal["user", "admin"]
SESSION_USER_KEY = "user"
SESSION_CSRF_KEY = "csrf_token"
# Fixed bcrypt hash used for constant-time login when username is unknown.
_DUMMY_PASSWORD_HASH = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"


@dataclass(frozen=True, slots=True)
class UserRecord:
    username: str
    password_hash: str
    role: Role = "user"


@dataclass(frozen=True, slots=True)
class SessionUser:
    username: str
    role: Role


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        return False


def parse_auth_users(raw: str) -> list[UserRecord]:
    if not raw.strip():
        return []
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("AUTH_USERS must be a JSON array")
    users: list[UserRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each AUTH_USERS entry must be an object")
        username = str(item.get("username", "")).strip()
        password_hash = str(item.get("password_hash", "")).strip()
        role = str(item.get("role", "user")).strip().lower()
        if not username or not password_hash:
            raise ValueError("AUTH_USERS entries require username and password_hash")
        if role not in ("user", "admin"):
            raise ValueError(f"Invalid role for user {username!r}: {role!r}")
        users.append(UserRecord(username=username, password_hash=password_hash, role=role))
    if not users:
        raise ValueError("AUTH_USERS must contain at least one user")
    return users


def resolve_auth_users_raw(settings: Settings) -> str:
    if settings.auth_users_file is not None:
        path = settings.auth_users_file
        if not path.is_file():
            raise ValueError(f"AUTH_USERS_FILE not found: {path}")
        return path.read_text(encoding="utf-8")
    return settings.auth_users


def load_user_directory(settings: Settings) -> dict[str, UserRecord]:
    users = parse_auth_users(resolve_auth_users_raw(settings))
    return {user.username: user for user in users}


def authenticate(
    username: str,
    password: str,
    directory: dict[str, UserRecord],
) -> SessionUser | None:
    record = directory.get(username.strip())
    password_hash = record.password_hash if record is not None else _DUMMY_PASSWORD_HASH
    if not verify_password(password, password_hash):
        return None
    if record is None:
        return None
    return SessionUser(username=record.username, role=record.role)


def get_session_user(request: Request) -> SessionUser | None:
    payload = request.session.get(SESSION_USER_KEY)
    if not isinstance(payload, dict):
        return None
    username = str(payload.get("username", "")).strip()
    role = str(payload.get("role", "")).strip().lower()
    if not username or role not in ("user", "admin"):
        return None
    return SessionUser(username=username, role=role)


def set_session_user(request: Request, user: SessionUser) -> None:
    request.session[SESSION_USER_KEY] = {
        "username": user.username,
        "role": user.role,
    }


def login_session_user(request: Request, user: SessionUser) -> None:
    """Clear and recreate the session to prevent session fixation."""
    request.session.clear()
    ensure_csrf_token(request)
    set_session_user(request, user)


def clear_session_user(request: Request) -> None:
    request.session.pop(SESSION_USER_KEY, None)


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get(SESSION_CSRF_KEY)
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        request.session[SESSION_CSRF_KEY] = token
    return token


def validate_csrf_token(request: Request, submitted: str | None) -> bool:
    expected = request.session.get(SESSION_CSRF_KEY)
    if not isinstance(expected, str) or not expected:
        return False
    if not submitted:
        return False
    return secrets.compare_digest(expected, submitted)


def is_admin(user: SessionUser | None) -> bool:
    return user is not None and user.role == "admin"
