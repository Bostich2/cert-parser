from __future__ import annotations

from fastapi import FastAPI

from cert_parser.api.auth import load_user_directory
from cert_parser.application.country_router import CountryRouter
from cert_parser.application.export_service import ExportService
from cert_parser.application.extract_service import ExtractService
from cert_parser.application.lookup_service import LookupService
from cert_parser.application.product_search_service import ProductSearchService
from cert_parser.config import get_settings
from cert_parser.domain.ports import LookupCache
from cert_parser.infrastructure.cache import SqliteLookupCache
from cert_parser.infrastructure.http import build_http_client
from cert_parser.infrastructure.pdf import reset_ocr_engines
from cert_parser.infrastructure.registries.armenia import ArmeniaProvider
from cert_parser.infrastructure.registries.belarus import BelgissProvider
from cert_parser.infrastructure.registries.chained import build_lookup_chain
from cert_parser.infrastructure.registries.eaeu_odata import EaeuOdataProvider, EaeuProductSearchProvider
from cert_parser.infrastructure.registries.fsa_declarations import FsaDeclarationsProvider
from cert_parser.infrastructure.registries.fsa_session import FsaSession
from cert_parser.infrastructure.registries.kazakhstan import EoknoProvider
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
    fsa_session = FsaSession(fsa_client, settings)
    fsa = FsaProvider(fsa_client, settings, session=fsa_session)
    fsa_decl = FsaDeclarationsProvider(fsa_client, settings, session=fsa_session)
    eaeu_product_ru = EaeuProductSearchProvider(eaeu_client, settings, russia_only=True)
    eaeu_product_other = EaeuProductSearchProvider(eaeu_client, settings, russia_only=False)
    eokno = EoknoProvider(eokno_client, settings)
    swis = SwisProvider(swis_client, settings)
    eaeu_by = EaeuOdataProvider(eaeu_client, settings, country_code="BY")
    eaeu_kz = EaeuOdataProvider(eaeu_client, settings, country_code="KZ")
    eaeu_ru = EaeuOdataProvider(eaeu_client, settings, country_code="RU")
    eaeu_kg = EaeuOdataProvider(eaeu_client, settings, country_code="KG")
    eaeu_first = settings.lookup_eaeu_first
    belarus = build_lookup_chain(
        "BY",
        eaeu_by,
        belgiss,
        eaeu_label="tech.eaeunion.org",
        national_label="api.belgiss.by",
        eaeu_first=eaeu_first,
    )
    kazakhstan = build_lookup_chain(
        "KZ",
        eaeu_kz,
        eokno,
        eaeu_label="tech.eaeunion.org",
        national_label="eokno.gov.kz",
        eaeu_first=eaeu_first,
    )
    russia = build_lookup_chain(
        "RU",
        eaeu_ru,
        fsa,
        eaeu_label="tech.eaeunion.org",
        national_label="pub.fsa.gov.ru",
        eaeu_first=eaeu_first,
    )
    kyrgyzstan = build_lookup_chain(
        "KG",
        eaeu_kg,
        swis,
        eaeu_label="tech.eaeunion.org",
        national_label="swis.trade.kg",
        eaeu_first=eaeu_first,
    )
    armenia = ArmeniaProvider(eaeu_client, settings)
    router = CountryRouter(
        {"BY": belarus, "RU": russia, "KZ": kazakhstan, "KG": kyrgyzstan, "AM": armenia}
    )
    extract_service = ExtractService(settings)
    export_service = ExportService()
    app.state.settings = settings
    app.state.cache = cache
    app.state.http_clients = [belgiss_client, fsa_client, eokno_client, swis_client, eaeu_client]
    app.state.registry_clients = {
        "eaeu": eaeu_client,
        "fsa": fsa_client,
    }
    app.state.providers = {
        "belgiss": belgiss,
        "eaeu_by": eaeu_by,
        "belarus": belarus,
        "fsa": fsa,
        "eaeu_ru": eaeu_ru,
        "russia": russia,
        "eokno": eokno,
        "eaeu_kz": eaeu_kz,
        "kazakhstan": kazakhstan,
        "swis": swis,
        "eaeu_kg": eaeu_kg,
        "kyrgyzstan": kyrgyzstan,
        "eaeu": armenia,
    }
    app.state.lookup_service = LookupService(router, cache, settings)
    app.state.product_search_service = ProductSearchService(
        [fsa, fsa_decl, eaeu_product_ru, eaeu_product_other],
        settings,
    )
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
    app.state.registry_clients = {}
    app.state.providers = {}
    app.state.lookup_service = None
    app.state.product_search_service = None
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
