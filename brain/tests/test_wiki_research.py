import logging

import httpx
import pytest

from brain.memory.db import Database, connect
from brain.research.discovery import WikiSite
from brain.research.mediawiki import SiteInfo
from brain.research.service import WikiResearch, best_title, card_message, search_terms
from brain.research.wiki_cache import WikiCache

SITE = WikiSite("https://wiki.test/api.php", SiteInfo("Test Wiki", "https://wiki.test", "/wiki/$1"))
PAGE_HTML = (
    '<div class="mw-parser-output"><div class="infobox"><img src="/img/eye.png">'
    "<table><tr><th>Max Life</th><td>2800</td></tr></table></div>"
    "<p>The <b>Eye</b> is a boss. It flies. It appears at night.</p></div>"
)


def wiki_handler(calls: list[dict[str, str]]):
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append(params)
        if params.get("list") == "search":
            hits = [{"title": "Eye Prime"}, {"title": "Eye"}]
            return httpx.Response(200, json={"query": {"search": hits}})
        if params["page"] in {"Eye", "Eye Prime"}:
            assert params["section"] == "0"
            return httpx.Response(200, json={"parse": {"title": params["page"], "text": PAGE_HTML}})
        return httpx.Response(200, json={"error": {"code": "missingtitle"}})

    return handler


async def test_lookup_builds_card_and_falls_back_to_search() -> None:
    calls: list[dict[str, str]] = []
    research = WikiResearch(SITE, transport=httpx.MockTransport(wiki_handler(calls)))
    card = await research.lookup("how do I beat the eye?")
    assert card is not None
    assert card.title == "Eye"
    assert card.summary == "The Eye is a boss. It flies."
    assert card.stats == [("Max Life", "2800")]
    assert card.image_url == "https://wiki.test/img/eye.png"
    assert card.source_url == "https://wiki.test/wiki/Eye"

    message = card_message(card, "c1")
    assert message.body == "The Eye is a boss. It flies.\n\nMax Life: 2800"
    assert message.source_url == "https://wiki.test/wiki/Eye"
    await research.aclose()


async def test_page_cache_survives_restart() -> None:
    database = Database(connect(":memory:"))
    calls: list[dict[str, str]] = []
    first = WikiResearch(SITE, WikiCache(database), httpx.MockTransport(wiki_handler(calls)))
    assert await first.lookup("Eye") is not None
    await first.aclose()
    made = len(calls)

    second = WikiResearch(SITE, WikiCache(database), httpx.MockTransport(wiki_handler(calls)))
    card = await second.lookup("Eye")
    assert card is not None and card.stats == [("Max Life", "2800")]
    assert len(calls) == made
    await second.aclose()
    database.close()


async def test_misses_are_remembered_and_failures_degrade(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("list") == "search":
            return httpx.Response(200, json={"query": {"search": []}})
        return httpx.Response(200, json={"error": {"code": "missingtitle"}})

    calls = 0

    def counting(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return handler(request)

    research = WikiResearch(SITE, transport=httpx.MockTransport(counting))
    assert await research.lookup("Nothing") is None
    assert await research.lookup("nothing") is None
    assert calls == 2  # One parse, one search, then remembered.
    await research.aclose()

    broken = WikiResearch(SITE, transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    with caplog.at_level(logging.ERROR):
        assert await broken.lookup("Eye") is None
    assert "Wiki lookup failed" in caplog.text
    await broken.aclose()


async def test_prefetch_counts_found_pages() -> None:
    research = WikiResearch(SITE, transport=httpx.MockTransport(wiki_handler([])))
    assert await research.prefetch(["Eye", "Eye Prime"]) == 2
    await research.aclose()


def test_search_terms_drop_question_filler() -> None:
    assert search_terms("How do I summon Skeletron?") == "summon skeletron"
    assert search_terms("what is the") == "what is the"


def test_best_title_prefers_name_in_query() -> None:
    hits = ["Skeletron Prime", "Skeletron", "Dungeon Guardian"]
    assert best_title("how to summon skeletron?", hits) == "Skeletron"
    assert best_title("skeletron prime drops", hits) == "Skeletron Prime"
    assert best_title("mechanical bosses", hits) == "Skeletron Prime"
