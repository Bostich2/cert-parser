from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from sert_parser.domain.models import CertificateNumber, RegistryRecord


class LookupCache(Protocol):
    def get(self, cache_key: str) -> dict[str, Any] | None: ...

    def set(self, cache_key: str, payload: dict[str, Any]) -> None: ...

    def clear(self) -> int: ...

    def delete(self, cache_key: str) -> None: ...

    def close(self) -> None: ...


class RegistryProvider(ABC):
    """National registry adapter. One implementation per country."""

    @abstractmethod
    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        """Return registry card data or raise a domain error."""

    async def ping(self) -> bool:
        return True
