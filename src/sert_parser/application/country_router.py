from __future__ import annotations

from sert_parser.domain.errors import UnsupportedCountryError
from sert_parser.domain.ports import RegistryProvider


class CountryRouter:
    def __init__(self, providers: dict[str, RegistryProvider]) -> None:
        self._providers = {code.upper(): provider for code, provider in providers.items()}

    def get(self, country_code: str) -> RegistryProvider:
        provider = self._providers.get(country_code.upper())
        if provider is None:
            raise UnsupportedCountryError(country_code.upper())
        return provider

    def supported_countries(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
