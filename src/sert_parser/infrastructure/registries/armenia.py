from __future__ import annotations

import httpx

from sert_parser.config import Settings
from sert_parser.infrastructure.registries.eaeu_odata import EaeuOdataProvider


class ArmeniaProvider(EaeuOdataProvider):
    """Armenia EAEU certificates via tech.eaeunion.org OData."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        super().__init__(client, settings, country_code="AM")
