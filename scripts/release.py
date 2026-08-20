#!/usr/bin/env python3
"""Create a semver git tag for the next release."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TAG_PATTERN = re.compile(r"^v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
ROOT = Path(__file__).resolve().parents[1]
BASELINE_VERSION = (0, 2, 0)


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def git(*args: str, check: bool = True) -> str:
    result = run("git", *args, check=check)
    return result.stdout.strip()


def latest_tag() -> str | None:
    result = run("git", "tag", "--list", "v*.*.*", "--sort=-v:refname", check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.splitlines()[0].strip()


def parse_version(tag: str) -> tuple[int, int, int]:
    match = TAG_PATTERN.match(tag)
    if not match:
        raise SystemExit(f"Unexpected tag format: {tag!r}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def bump_version(current: tuple[int, int, int], part: str) -> tuple[int, int, int]:
    major, minor, patch = current
    if part == "major":
        return major + 1, 0, 0
    if part == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def format_version(version: tuple[int, int, int]) -> str:
    return f"v{version[0]}.{version[1]}.{version[2]}"


def next_version(current_tag: str | None, part: str) -> tuple[int, int, int]:
    if current_tag:
        return bump_version(parse_version(current_tag), part)
    return BASELINE_VERSION


def ensure_clean_worktree() -> None:
    status = git("status", "--porcelain")
    if status:
        raise SystemExit(
            "Working tree is not clean. Commit or stash changes before releasing.\n"
            f"{status}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the next semver git tag.")
    parser.add_argument(
        "part",
        choices=("patch", "minor", "major"),
        help="Which semver segment to increment",
    )
    parser.add_argument(
        "--message",
        "-m",
        help="Annotated tag message (default: cert-parser vX.Y.Z)",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push the new tag to origin after creation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the next tag without creating it",
    )
    args = parser.parse_args()

    git("rev-parse", "--is-inside-work-tree")

    tag = latest_tag()
    if not tag:
        print("No semver tags found; creating baseline v0.2.0.")

    upcoming = next_version(tag, args.part)
    next_tag = format_version(upcoming)
    message = args.message or f"cert-parser {next_tag}"

    print(f"Current tag: {tag or '(none)'}")
    print(f"Next tag:    {next_tag}")

    if args.dry_run:
        print("Dry run: tag not created.")
        return 0

    ensure_clean_worktree()

    git("tag", "-a", next_tag, "-m", message)
    print(f"Created tag {next_tag}")

    try:
        sys.path.insert(0, str(ROOT / "src"))
        from cert_parser.version import compute_scm_version

        print(f"Resolved version: {compute_scm_version(write_files=False)}")
    except Exception as exc:  # noqa: BLE001 - release helper
        print(f"Could not resolve version via setuptools-scm: {exc}")

    print("Next steps:")
    print(f"  1. Commit ai_docs/changelog/CHANGELOG.md section ## [{next_tag[1:]}] before tagging")
    print(
        f"  2. git push origin {next_tag}  (GitHub Action publishes the Release)"
        if not args.push
        else "  2. Tag pushed; GitHub Action will publish the Release."
    )

    if args.push:
        git("push", "origin", next_tag)
        print(f"Pushed {next_tag} to origin.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        print(detail, file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
