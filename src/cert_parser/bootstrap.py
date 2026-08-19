from __future__ import annotations

from fastapi import FastAPI

from cert_parser.api.auth import load_user_directory
from cert_parser.application.country_router import CountryRouter
from cert_parser.application.export_service import ExportService
from cert_parser.application.extract_service import ExtractService
from cert_parser.application.lookup_service import LookupService
from cert_parser.config import get_settings
from cert_parser.domain.ports import LookupCache
from cert_parser.infrastructure.cache import SqliteLookupCache
from cert_parser.infrastructure.http import build_http_client
from cert_parser.infrastructure.pdf import reset_ocr_engines
from cert_parser.infrastructure.registries.armenia import ArmeniaProvider
from cert_parser.infrastructure.registries.belarus import BelgissProvider
from cert_parser.infrastructure.registries.eaeu_odata import EaeuOdataProvider
from cert_parser.infrastructure.registries.kazakhstan import EoknoProvider, KazakhstanProvider
from cert_parser.infrastructure.registries.kyrgyzstan import SwisProvider
from cert_parser.infrastructure.registries.russia import FsaProvider
from cert_parser.logging_setup import configure_logging


async def configure_runtime(app: FastAPI) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(settings.log_level)
    cache = SqliteLookupCache(settings.cache_path, settings.cache_ttl_seconds)
    belgiss_client = build_http_client(settings)
    fsa_client = build_http_client(
        settings,
        extra_headers={
            "Origin": settings.fsa_base_url.rstrip("/"),
            "Referer": f"{settings.fsa_base_url.rstrip('/')}/rss/certificate",
        },
    )
    eokno_client = build_http_client(
        settings,
        extra_headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": settings.eokno_register_url,
        },
    )
    swis_client = build_http_client(
        settings,
        extra_headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{settings.swis_base_url.rstrip('/')}/Registry/CertificateOfConformity",
        },
    )
    eaeu_client = build_http_client(
        settings,
        extra_headers={
            "Accept": "application/json",
            "Referer": "https://tech.eaeunion.org/tech/registers/35-1/ru/registryList/conformityDocs",
        },
    )
    belgiss = BelgissProvider(belgiss_client, settings)
    fsa = FsaProvider(fsa_client, settings)
    eokno = EoknoProvider(eokno_client, settings)
    eaeu_kz = EaeuOdataProvider(eaeu_client, settings, country_code="KZ")
    kazakhstan = KazakhstanProvider(eokno, eaeu_kz)
    swis = SwisProvider(swis_client, settings)
    armenia = ArmeniaProvider(eaeu_client, settings)
    router = CountryRouter({"BY": belgiss, "RU": fsa, "KZ": kazakhstan, "KG": swis, "AM": armenia})
    extract_service = ExtractService(settings)
    export_service = ExportService()
    app.state.settings = settings
    app.state.cache = cache
    app.state.http_clients = [belgiss_client, fsa_client, eokno_client, swis_client, eaeu_client]
    app.state.providers = {
        "belgiss": belgiss,
        "fsa": fsa,
        "eokno": eokno,
        "eaeu_kz": eaeu_kz,
        "kazakhstan": kazakhstan,
        "swis": swis,
        "eaeu": armenia,
    }
    app.state.lookup_service = LookupService(router, cache, settings)
    app.state.extract_service = extract_service
    app.state.export_service = export_service
    app.state.runtime_generation = int(getattr(app.state, "runtime_generation", 0)) + 1
    if settings.auth_enabled:
        app.state.auth_users = load_user_directory(settings)
    else:
        app.state.auth_users = {}


async def shutdown_runtime(app: FastAPI) -> None:
    await close_runtime(
        getattr(app.state, "http_clients", []) or [],
        getattr(app.state, "cache", None),
    )
    app.state.http_clients = []
    app.state.providers = {}
    app.state.lookup_service = None
    app.state.extract_service = None
    app.state.export_service = None
    app.state.cache = None
    app.state.auth_users = {}


async def close_runtime(
    http_clients: list,
    cache: LookupCache | None,
) -> None:
    for client in http_clients:
        await client.aclose()
    if cache is not None:
        cache.close()


def reset_runtime_ocr_engines() -> None:
    reset_ocr_engines()
