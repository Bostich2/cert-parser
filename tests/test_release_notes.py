from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_release_notes():
    path = ROOT / "scripts" / "release_notes.py"
    spec = importlib.util.spec_from_file_location("release_notes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tag_to_version_strips_v() -> None:
    release_notes = _load_release_notes()
    assert release_notes.tag_to_version("v0.2.0") == "0.2.0"
    assert release_notes.tag_to_version("1.4.2") == "1.4.2"


def test_extract_section_reads_changelog_heading() -> None:
    release_notes = _load_release_notes()
    text = (ROOT / "ai_docs" / "changelog" / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = release_notes.extract_section(text, "0.2.0")
    assert "FastAPI-приложение" in notes
    assert "[Unreleased]" not in notes
