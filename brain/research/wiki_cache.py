"""Keeps fetched wiki pages across restarts. This is lookup material, not memory."""

import sqlite3
import time
from collections.abc import Callable

from brain.memory.db import Database
from brain.research.mediawiki import WikiPage

DEFAULT_MAX_AGE_S = 7 * 24 * 3600.0


class WikiCache:
    def __init__(
        self,
        database: Database,
        clock: Callable[[], float] = time.time,
        max_age_s: float = DEFAULT_MAX_AGE_S,
    ) -> None:
        self._database = database
        self._clock = clock
        self._max_age_s = max_age_s

    async def get(self, api_url: str, page: str) -> WikiPage | None:
        oldest_allowed = self._clock() - self._max_age_s

        def read(conn: sqlite3.Connection) -> sqlite3.Row | None:
            return conn.execute(
                "SELECT title, html FROM wiki_cache"
                " WHERE api_url = ? AND page = ? AND fetched_at >= ?",
                (api_url, page, oldest_allowed),
            ).fetchone()

        row = await self._database.run(read)
        return None if row is None else WikiPage(title=row["title"], html=row["html"])

    async def put(self, api_url: str, page: str, wiki_page: WikiPage) -> None:
        fetched_at = self._clock()

        def write(conn: sqlite3.Connection) -> None:
            with conn:
                conn.execute(
                    "INSERT INTO wiki_cache (api_url, page, title, html, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT (api_url, page) DO UPDATE SET title = excluded.title,"
                    " html = excluded.html, fetched_at = excluded.fetched_at",
                    (api_url, page, wiki_page.title, wiki_page.html, fetched_at),
                )

        await self._database.run(write)
