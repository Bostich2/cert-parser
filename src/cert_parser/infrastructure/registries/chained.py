from __future__ import annotations

from cert_parser.domain.errors import CertificateNotFoundError, SourceUnavailableError
from cert_parser.domain.models import CertificateNumber, RegistryRecord
from cert_parser.domain.ports import RegistryProvider
from cert_parser.logging_setup import log_step


class ChainedRegistryProvider(RegistryProvider):
    """Try registry providers in order; fallback on not_found or source_unavailable."""

    def __init__(
        self,
        country_code: str,
        steps: list[tuple[RegistryProvider, str]],
    ) -> None:
        if len(steps) < 1:
            raise ValueError("ChainedRegistryProvider requires at least one step")
        self._country_code = country_code.upper()
        self._steps = steps

    async def lookup(self, number: CertificateNumber) -> RegistryRecord:
        prefix = self._country_code
        for index, (provider, label) in enumerate(self._steps):
            is_last = index == len(self._steps) - 1
            next_label = None if is_last else self._steps[index + 1][1]
            try:
                return await provider.lookup(number)
            except CertificateNotFoundError:
                if is_last:
                    raise
                log_step(f"{prefix}: {label} — не найден, пробуем {next_label}")
            except SourceUnavailableError as exc:
                if is_last:
                    raise
                log_step(f"{prefix}: {label} недоступен ({exc.message}), пробуем {next_label}")
        raise CertificateNotFoundError(number.normalized)

    async def ping(self) -> bool:
        for provider, _label in self._steps:
            if await provider.ping():
                return True
        return False


def build_lookup_chain(
    country_code: str,
    eaeu: RegistryProvider,
    national: RegistryProvider,
    *,
    eaeu_label: str,
    national_label: str,
    eaeu_first: bool,
) -> ChainedRegistryProvider:
    if eaeu_first:
        steps = [(eaeu, eaeu_label), (national, national_label)]
    else:
        steps = [(national, national_label), (eaeu, eaeu_label)]
    return ChainedRegistryProvider(country_code, steps)
