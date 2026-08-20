#!/bin/sh
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$ROOT" || exit 0

if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif command -v py >/dev/null 2>&1; then
  PY="py"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  exit 0
fi

if [ "$PY" = "py" ]; then
  py -3 scripts/write_version.py || true
else
  "$PY" scripts/write_version.py || true
fi
