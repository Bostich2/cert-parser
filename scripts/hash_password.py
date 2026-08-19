#!/usr/bin/env python3
"""Generate a bcrypt password hash for AUTH_USERS."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cert_parser.api.auth import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate bcrypt hash for AUTH_USERS")
    parser.add_argument("password", help="Plain-text password to hash")
    parser.add_argument("--username", help="Username for a ready AUTH_USERS JSON entry")
    parser.add_argument(
        "--role",
        choices=("user", "admin"),
        default="user",
        help="Role when --username is set (default: user)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write AUTH_USERS JSON to a file (recommended for Docker/Coolify deploy)",
    )
    parser.add_argument(
        "--for-docker",
        action="store_true",
        help="Print a single AUTH_USERS= line with $ escaped for Docker Compose",
    )
    args = parser.parse_args()

    password_hash = hash_password(args.password)
    if args.username:
        entry = {
            "username": args.username,
            "password_hash": password_hash,
            "role": args.role,
        }
        payload = json.dumps([entry], ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(payload + "\n", encoding="utf-8")
            print(f"Wrote {args.output}", file=sys.stderr)
        elif args.for_docker:
            line = json.dumps([entry], ensure_ascii=False, separators=(",", ":"))
            print("AUTH_USERS=" + line.replace("$", "$$"))
        else:
            print(payload)
    else:
        print(password_hash.replace("$", "$$") if args.for_docker else password_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
