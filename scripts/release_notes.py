#!/usr/bin/env python3
"""Print the CHANGELOG.md section for a semver tag."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "ai_docs" / "changelog" / "CHANGELOG.md"
HEADING = re.compile(r"^## \[([^\]]+)\]")


def tag_to_version(tag: str) -> str:
    value = tag.strip()
    if value.startswith("v") and re.fullmatch(r"v\d+\.\d+\.\d+", value):
        return value[1:]
    if re.fullmatch(r"\d+\.\d+\.\d+", value):
        return value
    raise SystemExit(f"Unexpected tag format: {tag!r}")


def extract_section(text: str, version: str) -> str:
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        match = HEADING.match(line)
        if match and match.group(1) == version:
            start = index + 1
            break
    if start is None:
        return ""

    end = len(lines)
    for index in range(start, len(lines)):
        if HEADING.match(lines[index]):
            end = index
            break
    body = "\n".join(lines[start:end]).strip()
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract GitHub Release notes from CHANGELOG.md.")
    parser.add_argument("tag", help="Git tag, e.g. v0.2.0")
    parser.add_argument(
        "--changelog",
        type=Path,
        default=CHANGELOG,
        help="Path to CHANGELOG.md",
    )
    args = parser.parse_args()

    version = tag_to_version(args.tag)
    if not args.changelog.is_file():
        print(f"Changelog not found: {args.changelog}", file=sys.stderr)
        return 1

    notes = extract_section(args.changelog.read_text(encoding="utf-8"), version)
    sys.stdout.write(notes)
    if notes:
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
