#!/usr/bin/env python3
"""Regenerate src/cert_parser/_version.py from git tags and commit count."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VERSION_FILE = ROOT / "src" / "cert_parser" / "_version.py"


def read_version() -> str:
    if not VERSION_FILE.is_file():
        return ""
    for line in VERSION_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__ = version ="):
            return line.rsplit("=", 1)[-1].strip().strip("'\"")
    return ""


def main() -> int:
    sys.path.insert(0, str(SRC))
    try:
        from cert_parser.version import compute_scm_version
    except ImportError:
        print(
            'Could not regenerate _version.py. Install dev deps: pip install -e ".[dev]"',
            file=sys.stderr,
        )
        return 1

    try:
        written = compute_scm_version(write_files=True)
    except Exception as exc:  # noqa: BLE001 - release helper
        print(f"Could not regenerate _version.py: {exc}", file=sys.stderr)
        return 1

    version = read_version() or written
    rel = VERSION_FILE.relative_to(ROOT)
    print(f"Wrote {rel} -> {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
