"""Wiki research for the slow loop: look things up, prefetch during downtime, build cards.

Lookups never raise for network or wiki failures. They log and return None, so a dead wiki only
means no card, never a stalled loop. Results are tentative reference data, not memory.
"""

import asyncio
import hashlib
import logging
import re
from collections.abc import Iterable

import httpx

from brain.memory.fts import query_terms
from brain.research.discovery import WikiSite, discover_wiki
from brain.research.mediawiki import MediaWikiClient, SiteInfo
from brain.research.models import WikiCard
from brain.research.page_match import match_passages
from brain.research.passages import page_passages
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
# A topic made only of these and the wiki's own name means the wiki itself, not a page on it.
# English only, like the filler.
_WIKI_WORDS = frozenset("wiki main home homepage".split())
_MAIN_PAGE_WORDS = _WIKI_WORDS | frozenset("page front official open site website".split())
# Room for a recipe row or a few drop rows, without crowding the talker's prompt.
DETAIL_CHARS = 700


def build_card(title: str, html: str, site: WikiSite, question: str = "") -> WikiCard:
    """CPU-bound HTML parsing, so callers run it in a worker thread. With a question, html must
    be the whole page, and the passages that answer it become the card's details."""
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
    details = (
        match_passages(question, beyond(summary, page_passages(html)), (), DETAIL_CHARS)
        if question
        else []
    )
    return WikiCard(
        title=clean_text(title),
        summary=summary,
        stats=stats,
        details=details,
        image_url=article.image_url,
        source_url=site.info.page_url(title),
        site_name=clean_text(site.info.name),
    )


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def beyond(summary: str, passages: list[str]) -> list[str]:
    """Passages less what the card's summary already says, so details don't repeat the intro."""
    lead = summary.removesuffix("…")
    kept: list[str] = []
    for passage in passages:
        if lead and passage.startswith(lead):
            passage = passage[len(lead) :].strip()
        elif lead.startswith(passage):
            passage = ""
        if passage:
            kept.append(passage)
    return kept


def focus(question: str, title: str) -> str:
    """What's left of a question once the page's own name is gone, since nearly every passage
    on a page mentions it. Empty when nothing worth matching is left."""
    named = set(_words(title))
    left = " ".join(w for w in _words(question) if w not in named)
    return left if query_terms(left) else ""


def names_main_page(query: str, info: SiteInfo) -> bool:
    """True for an empty topic or one naming the wiki itself, such as "<game> wiki". A bare game
    name isn't enough, because that's usually a real article."""
    words = set(_words(query)) - _FILLER
    own = set(_words(info.name)) | set(_words(info.main_page))
    return not words or (words <= own | _MAIN_PAGE_WORDS and bool(words & _WIKI_WORDS))


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
    """Set open_page only for lookups the player asked for, so a page can't change under them.

    The default id is the same for every lookup of a page, so asking again replaces its card
    instead of stacking a copy on the game."""
    page_id = hashlib.blake2s(card.source_url.encode(), digest_size=4).hexdigest()
    return CardShow(
        card_id=card_id or f"wiki-{page_id}",
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

    def main_page_card(self) -> WikiCard:
        """The main page has no intro or infobox to show, but the player can still open it."""
        name = clean_text(self.site.info.name)
        return WikiCard(
            title=name,
            summary=f"The main page of {name}.",
            source_url=self.site.info.page_url(self.site.info.main_page),
            site_name=name,
        )

    async def lookup(self, query: str, question: str = "") -> WikiCard | None:
        """A question, such as "how to craft it", reads the whole page for the passages that
        answer it, because recipes and drops sit below the intro. Cards are memoized without
        them, since they depend on the question."""
        if names_main_page(query, self.site.info):
            return self.main_page_card()
        key = query_key(query)
        if key in self._memo and (self._memo[key] is None or not question.strip()):
            return self._memo[key]
        try:
            card = await self._fetch(query, question)
        except (httpx.HTTPError, LookupError, KeyError, TypeError, ValueError):
            # Not memoized, so a transient network failure can be retried later.
            log.exception("Wiki lookup failed for %r on %s", query, self.site.api_url)
            return None
        self._memo[key] = card.model_copy(update={"details": []}) if card else None
        return card

    async def _fetch(self, query: str, question: str) -> WikiCard | None:
        # The whole page only when there's something to find in it: the intro is far smaller.
        wanted = focus(question, query)
        try:
            page = await self._client.parse_page(query, intro_only=not wanted)
        except LookupError:
            # Not an exact title (player phrasing, OCR text), so fall back to wiki search.
            titles = await self._client.search(search_terms(query), limit=5)
            if not titles:
                log.info("Wiki has nothing for %r", query)
                return None
            title = best_title(query, titles)
            # A topic like "<boss> drops" carries its own question once the name is found.
            wanted = focus(f"{question} {query}", title)
            page = await self._client.parse_page(title, intro_only=not wanted)
        if page.title == self.site.info.main_page:
            # Reached by another name, such as a redirect, it still opens rather than vanishing.
            return self.main_page_card()
        card = await asyncio.to_thread(build_card, page.title, page.html, self.site, wanted)
        if not card.summary and not card.stats and not card.details:
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
