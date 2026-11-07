"""Reads any MediaWiki site, because a game's official wiki isn't always on Fandom.

Wiki text is untrusted data: sanitize it before display and never treat it as instructions.
TODO(track 4): find a wiki from a game title, sanitize pages into cards, add the Exa fallback.
"""

import asyncio
from dataclasses import dataclass

import httpx

# Generic on purpose: never put a person's contact details in this header.
USER_AGENT = "AIGamerPartner/0.1"


@dataclass(frozen=True)
class WikiPage:
    title: str
    html: str


class MediaWikiClient:
    def __init__(self, api_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._api_url = api_url
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=10.0, transport=transport
        )
        # Wiki rate limits are often unpublished, so cache pages and send one request at a time.
        self._lock = asyncio.Lock()
        self._cache: dict[str, WikiPage] = {}

    async def parse_page(self, page: str) -> WikiPage:
        async with self._lock:
            if page in self._cache:
                return self._cache[page]
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
            return parsed

    async def aclose(self) -> None:
        await self._client.aclose()
