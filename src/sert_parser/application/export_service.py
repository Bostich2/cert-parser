from __future__ import annotations

from sert_parser.infrastructure.xlsx import build_results_xlsx


class ExportService:
    def build_results_xlsx(self, rows: list[dict]) -> bytes:
        return build_results_xlsx(rows)
