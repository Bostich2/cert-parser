#!/bin/sh
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$ROOT" || exit 0
python scripts/write_version.py >/dev/null 2>&1 || true
