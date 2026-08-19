from __future__ import annotations

from abc import ABC, abstractmethod

from sert_parser.domain.models import CertificateNumber, RegistryRecord


class RegistryProvider(ABC):
    """National registry adapter. One implementation per country."""

    @abstractmethod
    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        """Return registry card data or raise a domain error."""

    async def ping(self) -> bool:
        return True
