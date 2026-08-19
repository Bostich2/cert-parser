#!/usr/bin/env python3
"""Install git hooks that regenerate _version.py after commit, merge, or checkout."""

from __future__ import annotations

import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITHOOKS = ROOT / ".githooks"
GIT_HOOKS = ROOT / ".git" / "hooks"
HOOK_NAMES = ("post-commit", "post-merge", "post-checkout")


def main() -> int:
    if not GIT_HOOKS.parent.is_dir():
        print("Not a git repository (.git missing).", file=sys.stderr)
        return 1

    installed = 0
    for name in HOOK_NAMES:
        source = GITHOOKS / name
        if not source.is_file():
            print(f"Missing hook template: {source}", file=sys.stderr)
            return 1
        target = GIT_HOOKS / name
        shutil.copy2(source, target)
        mode = target.stat().st_mode
        target.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        installed += 1

    print(f"Installed {installed} git hooks into {GIT_HOOKS.relative_to(ROOT)}")
    print("After each commit/merge/checkout: python scripts/write_version.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
