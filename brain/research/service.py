"""Wiki research for the slow loop: look things up, prefetch during downtime, build cards.

Lookups never raise for network or wiki failures. They log and return None, so a dead wiki only
means no card, never a stalled loop. Results are tentative reference data, not memory.
"""

import asyncio
import logging
import re
import uuid
from collections.abc import Iterable

import httpx

from brain.research.discovery import WikiSite, discover_wiki
from brain.research.mediawiki import MediaWikiClient
from brain.research.models import WikiCard
from brain.research.sanitize import clean_text, parse_article, truncate_sentences
from brain.research.websearch import WebSearch
from brain.research.wiki_cache import WikiCache
from shared.protocol.messages import CardShow

log = logging.getLogger(__name__)


def query_key(query: str) -> str:
    return " ".join(query.replace("_", " ").casefold().split())


MAX_STATS = 6
MAX_STAT_CHARS = 80
SUMMARY_SENTENCES = 2
SUMMARY_CHARS = 320
# English question filler only, never game words, so this stays game-agnostic.
_FILLER = frozenset(
    "a an the how what whats where when which who why is are was do does did can could should"
    " would i me my we you your to of for in on at with about get beat find tell show".split()
)


def build_card(title: str, html: str, site: WikiSite) -> WikiCard:
    """CPU-bound HTML parsing, so callers run it in a worker thread."""
    article = parse_article(html, site.info.server + "/")
    summary = truncate_sentences(" ".join(article.paragraphs[:2]), SUMMARY_SENTENCES, SUMMARY_CHARS)
    stats: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, value in article.infobox:
        if label.casefold() in seen:
            continue
        seen.add(label.casefold())
        stats.append((label[:40], truncate_sentences(value, 1, MAX_STAT_CHARS)))
        if len(stats) == MAX_STATS:
            break
    return WikiCard(
        title=clean_text(title),
        summary=summary,
        stats=stats,
        image_url=article.image_url,
        source_url=site.info.page_url(title),
        site_name=clean_text(site.info.name),
    )


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def search_terms(query: str) -> str:
    """Question filler drowns the entity in wiki search: "how to summon skeletron" doesn't
    return Skeletron in the top 5, while "summon skeletron" ranks it first."""
    kept = [w for w in _words(query) if w not in _FILLER]
    return " ".join(kept) if kept else query


def best_title(query: str, titles: list[str]) -> str:
    """Wiki search can rank "Skeletron Prime" above "Skeletron" for "summon skeletron", so
    prefer the longest hit whose whole title appears in the query, else trust the wiki's rank."""
    padded = f" {' '.join(_words(query))} "
    named = [t for t in titles if _words(t) and f" {' '.join(_words(t))} " in padded]
    return max(named, key=len) if named else titles[0]


def card_message(
    card: WikiCard, card_id: str | None = None, *, open_page: bool = False
) -> CardShow:
    """Set open_page only for lookups the player asked for, so a page can't change under them."""
    return CardShow(
        card_id=card_id or f"wiki-{uuid.uuid4().hex[:8]}",
        title=card.title,
        body=card.body_text(),
        source_url=card.source_url,
        page_url=card.source_url if open_page else None,
    )


class WikiResearch:
    def __init__(
        self,
        site: WikiSite,
        cache: WikiCache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.site = site
        # The page cache persists raw pages; cards are cheap to rebuild from them.
        self._client = MediaWikiClient(site.api_url, transport, cache)
        self._memo: dict[str, WikiCard | None] = {}  # Includes misses, so we don't re-ask.

    @classmethod
    async def for_game(
        cls,
        game_title: str,
        cache: WikiCache | None = None,
        *,
        override_api_url: str | None = None,
        web_search: WebSearch | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> "WikiResearch | None":
        site = await discover_wiki(
            game_title,
            override_api_url=override_api_url,
            web_search=web_search,
            transport=transport,
        )
        return cls(site, cache, transport) if site else None

    async def lookup(self, query: str) -> WikiCard | None:
        key = query_key(query)
        if not key:
            return None
        if key in self._memo:
            return self._memo[key]
        try:
            card = await self._fetch(query)
        except (httpx.HTTPError, LookupError, KeyError, TypeError, ValueError):
            # Not memoized, so a transient network failure can be retried later.
            log.exception("Wiki lookup failed for %r on %s", query, self.site.api_url)
            return None
        self._memo[key] = card
        return card

    async def _fetch(self, query: str) -> WikiCard | None:
        try:
            page = await self._client.parse_page(query, intro_only=True)
        except LookupError:
            # Not an exact title (player phrasing, OCR text), so fall back to wiki search.
            titles = await self._client.search(search_terms(query), limit=5)
            if not titles:
                log.info("Wiki has nothing for %r", query)
                return None
            page = await self._client.parse_page(best_title(query, titles), intro_only=True)
        card = await asyncio.to_thread(build_card, page.title, page.html, self.site)
        if not card.summary and not card.stats:
            log.info("Wiki page %r had no readable intro or infobox", page.title)
            return None
        return card

    async def prefetch(self, queries: Iterable[str]) -> int:
        """For downtime (menus, deaths, loading). Sequential on purpose: one request at a time."""
        found = 0
        for query in queries:
            if await self.lookup(query) is not None:
                found += 1
        return found

    async def aclose(self) -> None:
        await self._client.aclose()
