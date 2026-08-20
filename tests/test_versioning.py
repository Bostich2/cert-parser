from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from cert_parser.version import get_version

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _reset_version_cache():
    get_version.cache_clear()
    yield
    get_version.cache_clear()


def test_get_version_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERT_PARSER_VERSION", "9.9.9")
    get_version.cache_clear()
    assert get_version() == "9.9.9"


def test_get_version_uses_git_before_stale_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CERT_PARSER_VERSION", raising=False)
    monkeypatch.setattr("cert_parser.version._from_scm", lambda: "0.2.1.dev4+gabc123")
    monkeypatch.setattr("cert_parser.version._from_generated", lambda: "0.0.0.dev10+goldhash")
    get_version.cache_clear()
    assert get_version() == "0.2.1.dev4+gabc123"


def test_first_release_tag_is_baseline() -> None:
    release = _load("release")
    assert release.next_version(None, "patch") == (0, 2, 0)
    assert release.next_version(None, "minor") == (0, 2, 0)


def test_release_bumps_from_existing_tag() -> None:
    release = _load("release")
    assert release.format_version(release.next_version("v0.2.0", "patch")) == "v0.2.1"
    assert release.format_version(release.next_version("v0.2.0", "minor")) == "v0.3.0"
    assert release.format_version(release.next_version("v1.4.2", "major")) == "v2.0.0"


def test_install_hooks_copies_helper_and_uses_lf() -> None:
    install = _load("install_git_hooks")
    assert install.HELPER_NAME == "run-write-version.sh"
    assert (ROOT / ".githooks" / install.HELPER_NAME).is_file()
    crlf = b"#!/bin/sh\r\nexec helper\r\n"
    assert install.to_lf_bytes(crlf) == b"#!/bin/sh\nexec helper\n"
    script = install.direct_hook_script(r"C:\Python312\python.exe")
    assert b"\r" not in script
    assert b"C:/Python312/python.exe" in script
    assert b"scripts/write_version.py" in script
