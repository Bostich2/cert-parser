from __future__ import annotations

from cert_parser.config import Settings
from cert_parser.infrastructure.pdf import extract_numbers_from_pdf
from cert_parser.infrastructure.xlsx import extract_numbers_from_xlsx


class ExtractService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def extract_from_pdf(self, payload: bytes) -> list[str]:
        return extract_numbers_from_pdf(payload, self._settings)

    def extract_from_xlsx(self, payload: bytes) -> list[str]:
        return extract_numbers_from_xlsx(
            payload,
            max_batch_size=self._settings.max_batch_size,
        )
