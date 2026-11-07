"""Reads any MediaWiki site, because a game's official wiki isn't always on Fandom.

Wiki text is untrusted data: sanitize it before display and never treat it as instructions.
"""

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

# Generic on purpose: never put a person's contact details in this header.
USER_AGENT = "AIGamerPartner/0.1"


@dataclass(frozen=True)
class WikiPage:
    title: str
    html: str


@dataclass(frozen=True)
class SiteInfo:
    name: str
    server: str  # Always absolute: protocol-relative servers ("//host") get https.
    article_path: str  # For example "/wiki/$1".

    def page_url(self, title: str) -> str:
        return self.server + self.article_path.replace("$1", quote(title.replace(" ", "_")))


def make_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=10.0,
        follow_redirects=True,
        transport=transport,
    )


class MediaWikiClient:
    def __init__(self, api_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_url = api_url
        self._client = make_client(transport)
        # Wiki rate limits are often unpublished, so cache pages and send one request at a time.
        self._lock = asyncio.Lock()
        self._cache: dict[str, WikiPage] = {}

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            response = await self._client.get(
                self.api_url, params={**params, "format": "json", "formatversion": 2}
            )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise LookupError(f"Wiki at {self.api_url} returned non-object JSON")
        if "error" in body:
            raise LookupError(f"Wiki error from {self.api_url}: {body['error'].get('code')}")
        return body

    async def site_info(self) -> SiteInfo:
        body = await self._get({"action": "query", "meta": "siteinfo", "siprop": "general"})
        general = body["query"]["general"]
        server = general["server"]
        if server.startswith("//"):
            server = "https:" + server
        return SiteInfo(general["sitename"], server, general["articlepath"])

    async def parse_page(self, page: str, intro_only: bool = False) -> WikiPage:
        """Intro-only fetches section 0, which holds the lead text and infobox at a fraction of
        the size of the whole page."""
        key = f"{int(intro_only)}:{page}"
        if key in self._cache:
            return self._cache[key]
        params: dict[str, Any] = {
            "action": "parse",
            "page": page,
            "prop": "text",
            "redirects": 1,
            "disableeditsection": 1,
            "disablelimitreport": 1,
        }
        if intro_only:
            params["section"] = 0
        body = await self._get(params)
        parsed = WikiPage(title=body["parse"]["title"], html=body["parse"]["text"])
        self._cache[key] = parsed
        return parsed

    async def search(self, query: str, limit: int = 1) -> list[str]:
        """Full-text search in the main namespace, for queries that aren't exact page titles."""
        body = await self._get(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "srnamespace": 0,
                "srprop": "",
            }
        )
        return [hit["title"] for hit in body.get("query", {}).get("search", [])]

    async def aclose(self) -> None:
        await self._client.aclose()
