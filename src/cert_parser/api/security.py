"""Shared security helpers for uploads, rate limiting, and URL validation."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import HTTPException, UploadFile
from slowapi.util import get_remote_address
from starlette.requests import Request

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF-"
_XLSX_MAGIC = b"PK\x03\x04"


def get_client_address(request: Request) -> str:
    """Return client IP, honoring X-Forwarded-For / X-Real-IP from trusted proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return get_remote_address(request)


async def read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Stream-read an upload with a hard byte cap to prevent memory exhaustion."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            max_mb = max_bytes // (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"Файл больше {max_mb} МБ")
        chunks.append(chunk)
    return b"".join(chunks)


def validate_pdf_content(payload: bytes) -> None:
    if not payload.startswith(_PDF_MAGIC):
        raise HTTPException(status_code=400, detail="Файл не является PDF")


def validate_xlsx_content(payload: bytes) -> None:
    if not payload.startswith(_XLSX_MAGIC):
        raise HTTPException(status_code=400, detail="Файл не является Excel (.xlsx)")


def safe_http_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return url
