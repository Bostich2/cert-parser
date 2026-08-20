"""Resolve application version from git tags, install metadata, or env override."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FALLBACK_VERSION = "0.0.0.dev0"


def _from_env() -> str | None:
    override = os.environ.get("CERT_PARSER_VERSION", "").strip()
    return override or None


def compute_scm_version(*, write_files: bool = False) -> str:
    """Read (and optionally write) the setuptools-scm version from pyproject.toml."""
    from setuptools_scm import _get_version
    from vcs_versioning import VcsEnvironment

    env = VcsEnvironment.from_env("SETUPTOOLS_SCM")
    config = env.build_config(name=PROJECT_ROOT / "pyproject.toml")
    version = _get_version(config, force_write_version_files=write_files)
    if not version:
        raise LookupError("setuptools-scm returned no version")
    return version


def _from_scm() -> str | None:
    if not (PROJECT_ROOT / ".git").exists():
        return None
    try:
        return compute_scm_version(write_files=False)
    except Exception:  # noqa: BLE001 - version lookup has several fallbacks
        return None


def _from_generated() -> str | None:
    try:
        from cert_parser._version import __version__ as generated
    except ImportError:
        return None
    return generated or None


def _from_package_metadata() -> str | None:
    try:
        from importlib.metadata import PackageNotFoundError, version as pkg_version
    except ImportError:
        return None
    try:
        return pkg_version("cert-parser")
    except PackageNotFoundError:
        return None


@lru_cache(maxsize=1)
def get_version() -> str:
    """Return semver from CERT_PARSER_VERSION, git tags, or package metadata."""
    return (
        _from_env()
        or _from_scm()
        or _from_generated()
        or _from_package_metadata()
        or _FALLBACK_VERSION
    )


def __getattr__(name: str) -> str:
    if name == "__version__":
        return get_version()
    raise AttributeError(f"module {__name__!r} has no attribute {name}")
