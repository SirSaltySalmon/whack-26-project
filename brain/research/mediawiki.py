"""Reads any MediaWiki site, because a game's official wiki isn't always on Fandom.

Wiki text is untrusted data: sanitize it before display and never treat it as instructions.
TODO(track 4): find a wiki from a game title, sanitize pages into cards, add the Exa fallback.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    # wiki_cache imports WikiPage from here at runtime, so this direction must stay type-only.
    from brain.research.wiki_cache import WikiCache

log = logging.getLogger(__name__)

# Generic on purpose: never put a person's contact details in this header.
USER_AGENT = "AIGamerPartner/0.1"


@dataclass(frozen=True)
class WikiPage:
    title: str
    html: str


class MediaWikiClient:
    def __init__(
        self,
        api_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: WikiCache | None = None,
    ) -> None:
        self._api_url = api_url
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=10.0, transport=transport
        )
        # Wiki rate limits are often unpublished, so cache pages and send one request at a time.
        self._lock = asyncio.Lock()
        self._cache: dict[str, WikiPage] = {}
        self._persistent_cache = cache

    async def parse_page(self, page: str) -> WikiPage:
        async with self._lock:
            if page in self._cache:
                return self._cache[page]
            cached = await self._read_persistent(page)
            if cached is not None:
                self._cache[page] = cached
                return cached
            response = await self._client.get(
                self._api_url,
                params={
                    "action": "parse",
                    "page": page,
                    "prop": "text",
                    "redirects": 1,
                    "format": "json",
                    "formatversion": 2,
                },
            )
            response.raise_for_status()
            body = response.json()
            if "error" in body:
                raise LookupError(f"Wiki error for {page!r}: {body['error'].get('code')}")
            parsed = WikiPage(title=body["parse"]["title"], html=body["parse"]["text"])
            self._cache[page] = parsed
            await self._write_persistent(page, parsed)
            return parsed

    async def _read_persistent(self, page: str) -> WikiPage | None:
        if self._persistent_cache is None:
            return None
        try:
            return await self._persistent_cache.get(self._api_url, page)
        except sqlite3.Error:
            # The wiki can still answer, so a broken cache must not cost the player the lookup.
            log.exception("Wiki cache read failed for %r; fetching instead", page)
            return None

    async def _write_persistent(self, page: str, parsed: WikiPage) -> None:
        if self._persistent_cache is None:
            return
        try:
            await self._persistent_cache.put(self._api_url, page, parsed)
        except sqlite3.Error:
            # The page is already fetched and held in RAM, so this only costs a later refetch.
            log.exception("Wiki cache write failed for %r", page)

    async def aclose(self) -> None:
        await self._client.aclose()
