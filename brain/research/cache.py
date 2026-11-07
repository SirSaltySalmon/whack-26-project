"""SQLite cache of sanitized wiki cards.

This is lookup material, not memory: a cached card never becomes a fact by itself. Persisting it
means prefetched pages survive restarts and still load if the venue network drops.
"""

import sqlite3
import time

from brain.research.models import WikiCard

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_cache (
    api_url TEXT NOT NULL,
    query_key TEXT NOT NULL,
    card TEXT NOT NULL CHECK (json_valid(card)),
    fetched_at REAL NOT NULL,
    PRIMARY KEY (api_url, query_key)
);
"""


def query_key(query: str) -> str:
    return " ".join(query.replace("_", " ").casefold().split())


class WikiCache:
    def __init__(self, conn: sqlite3.Connection, ttl_seconds: float = 7 * 24 * 3600) -> None:
        self._conn = conn
        self._ttl = ttl_seconds
        with conn:
            conn.executescript(_SCHEMA)

    def get(self, api_url: str, query: str) -> WikiCard | None:
        row = self._conn.execute(
            "SELECT card FROM wiki_cache WHERE api_url = ? AND query_key = ? AND fetched_at > ?",
            (api_url, query_key(query), time.time() - self._ttl),
        ).fetchone()
        return WikiCard.model_validate_json(row[0]) if row else None

    def put(self, api_url: str, query: str, card: WikiCard) -> None:
        # Stored under both the asked query and the resolved title, so either finds it later.
        keys = {query_key(query), query_key(card.title)}
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO wiki_cache (api_url, query_key, card, fetched_at)"
                " VALUES (?, ?, ?, ?)",
                [(api_url, k, card.model_dump_json(), time.time()) for k in keys],
            )
