#!/usr/bin/env python3
"""Regenerate src/cert_parser/_version.py from git tags and commit count."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "cert_parser" / "_version.py"


def read_version() -> str:
    if not VERSION_FILE.is_file():
        return ""
    for line in VERSION_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__ = version ="):
            return line.rsplit("=", 1)[-1].strip().strip("'\"")
    return ""


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "setuptools_scm", "--force-write-version-files"],
        cwd=ROOT,
        check=False,
    )
    if proc.returncode != 0:
        print(
            "Could not regenerate _version.py. Install dev deps: pip install -e \".[dev]\"",
            file=sys.stderr,
        )
        return proc.returncode

    version = read_version()
    if version:
        rel = VERSION_FILE.relative_to(ROOT)
        print(f"Wrote {rel} -> {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
