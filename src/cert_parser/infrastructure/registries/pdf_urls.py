from __future__ import annotations

from urllib.parse import quote, urljoin


def build_certificate_pdf_proxy_url(source: str, registry_id: str) -> str:
    encoded_id = quote(registry_id, safe="")
    return f"/api/certificate-pdf?source={quote(source, safe='')}&registry_id={encoded_id}"


def absolutize_url(url: str | None, base_url: str) -> str | None:
    if not url:
        return None
    if url.startswith("/"):
        return urljoin(base_url.rstrip("/") + "/", url.lstrip("/"))
    return url
