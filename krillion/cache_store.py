"""A persistent store for ai-api-unified's response cache.

The library's default cache lives in process memory and is lost on restart.
This SQLite store keeps it on disk and shares it between the server's threads
and the pipeline, so an identical request (the same category's answer list,
the same judged answer, the same embedding) is paid for once.

The library calls get/set/delete and treats any failure here as a miss, so a
broken cache never breaks a game.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "cache" / "ai-responses.sqlite"


class SQLiteCacheStore:
    def __init__(self, path: Path = DEFAULT_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value BLOB NOT NULL, expires REAL)")
        self._lock = threading.Lock()

    def get(self, key: str) -> bytes | None:
        with self._lock:
            row = self._db.execute("SELECT value, expires FROM cache WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            value, expires = row
            if expires is not None and expires < time.time():
                self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
                return None
            return bytes(value)

    def set(self, key: str, value: bytes, ttl_seconds: float | None = None) -> None:
        expires = time.time() + ttl_seconds if ttl_seconds else None
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires) VALUES (?, ?, ?)", (key, value, expires))

    def delete(self, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM cache WHERE key = ?", (key,))

    def __len__(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM cache").fetchone()[0]


_installed = False


def install(path: Path = DEFAULT_PATH) -> None:
    """Point ai-api-unified's response cache at the persistent store (once)."""
    global _installed
    if _installed:
        return
    from ai_api_unified import AIFactory

    AIFactory.set_cache_store(SQLiteCacheStore(path))
    _installed = True
