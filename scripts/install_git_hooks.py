#!/usr/bin/env python3
"""Install git hooks that regenerate _version.py after commit, merge, or checkout."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITHOOKS = ROOT / ".githooks"
GIT_HOOKS = ROOT / ".git" / "hooks"
HOOK_NAMES = ("post-commit", "post-merge", "post-checkout")
HELPER_NAME = "run-write-version.sh"


def to_lf_bytes(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _chmod_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_lf(path: Path, data: bytes) -> None:
    path.write_bytes(to_lf_bytes(data))
    _chmod_executable(path)


def direct_hook_script(python_exe: str) -> bytes:
    posix = Path(python_exe).as_posix()
    return f'#!/bin/sh\n"{posix}" scripts/write_version.py || true\n'.encode("utf-8")


def main() -> int:
    if not GIT_HOOKS.parent.is_dir():
        print("Not a git repository (.git missing).", file=sys.stderr)
        return 1

    GIT_HOOKS.mkdir(exist_ok=True)

    helper_source = GITHOOKS / HELPER_NAME
    if not helper_source.is_file():
        print(f"Missing hook template: {helper_source}", file=sys.stderr)
        return 1
    write_lf(GIT_HOOKS / HELPER_NAME, helper_source.read_bytes())

    python_exe = sys.executable
    installed = 1
    for name in HOOK_NAMES:
        source = GITHOOKS / name
        if not source.is_file():
            print(f"Missing hook template: {source}", file=sys.stderr)
            return 1
        write_lf(GIT_HOOKS / name, direct_hook_script(python_exe))
        installed += 1

    print(f"Installed {installed} git hooks into {GIT_HOOKS.relative_to(ROOT)}")
    print(f"Hooks call: {python_exe} scripts/write_version.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
