"""Resolve application version from git tags, install metadata, or env override."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FALLBACK_VERSION = "0.0.0.dev0"


@lru_cache(maxsize=1)
def get_version() -> str:
    """Return semver from SERT_PARSER_VERSION, setuptools-scm, or package metadata."""
    override = os.environ.get("SERT_PARSER_VERSION", "").strip()
    if override:
        return override

    try:
        from sert_parser._version import __version__ as generated

        if generated:
            return generated
    except ImportError:
        pass

    try:
        from importlib.metadata import PackageNotFoundError, version as pkg_version

        try:
            return pkg_version("sert-parser")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass

    try:
        import setuptools_scm

        return setuptools_scm.get_version(
            root=str(PROJECT_ROOT),
            relative_to=__file__,
        )
    except (ImportError, LookupError):
        pass

    return _FALLBACK_VERSION


def __getattr__(name: str) -> str:
    if name == "__version__":
        return get_version()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
