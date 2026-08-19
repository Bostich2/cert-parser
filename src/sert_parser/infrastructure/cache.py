from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class SqliteLookupCache:
    def __init__(self, path: Path, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lookup_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )
        self._connection.commit()

    def get(self, cache_key: str) -> dict[str, Any] | None:
        now = int(time.time())
        row = self._connection.execute(
            "SELECT payload, expires_at FROM lookup_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        payload, expires_at = row
        if expires_at <= now:
            self._connection.execute("DELETE FROM lookup_cache WHERE cache_key = ?", (cache_key,))
            self._connection.commit()
            return None
        return json.loads(payload)

    def set(self, cache_key: str, payload: dict[str, Any]) -> None:
        expires_at = int(time.time()) + self._ttl_seconds
        self._connection.execute(
            """
            INSERT INTO lookup_cache (cache_key, payload, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload = excluded.payload,
                expires_at = excluded.expires_at
            """,
            (cache_key, json.dumps(payload, ensure_ascii=False), expires_at),
        )
        self._connection.commit()

    def clear(self) -> int:
        count = self._connection.execute("SELECT COUNT(*) FROM lookup_cache").fetchone()[0]
        self._connection.execute("DELETE FROM lookup_cache")
        self._connection.commit()
        return int(count)

    def delete(self, cache_key: str) -> None:
        self._connection.execute("DELETE FROM lookup_cache WHERE cache_key = ?", (cache_key,))
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()
