import logging

import httpx
import pytest

from brain.memory.db import Database, connect
from brain.research.discovery import WikiSite
from brain.research.mediawiki import MediaWikiClient, SiteInfo
from brain.research.models import WikiCard
from brain.research.service import (
    WikiResearch,
    best_title,
    beyond,
    card_message,
    names_main_page,
    search_terms,
)
from brain.research.wiki_cache import WikiCache

SITE = WikiSite("https://wiki.test/api.php", SiteInfo("Test Wiki", "https://wiki.test", "/wiki/$1"))
MAIN_SITE = WikiSite(
    "https://wiki.test/api.php",
    SiteInfo("Test Wiki", "https://wiki.test", "/wiki/$1", main_page="Test Wiki"),
)
INTRO_HTML = (
    '<div class="infobox"><img src="/img/eye.png">'
    "<table><tr><th>Max Life</th><td>2800</td></tr></table></div>"
    "<p>The <b>Eye</b> is a boss. It flies. It appears at night.</p>"
)
REST_HTML = (
    "<h2>Crafting</h2><h3>Recipes</h3><table><tr><th>Result</th><th>Ingredients</th></tr>"
    "<tr><td>Eye Lure</td><td><ul><li>Lens <span>6</span></li></ul></td></tr></table>"
    "<h2>Tips</h2><ul><li>Beat it with arrows from a high platform.</li></ul>"
)
PAGE_HTML = f'<div class="mw-parser-output">{INTRO_HTML}</div>'
FULL_HTML = f'<div class="mw-parser-output">{INTRO_HTML}{REST_HTML}</div>'


def wiki_handler(calls: list[dict[str, str]]):
    """Section 0 for an intro-only fetch, as MediaWiki does, and the whole page otherwise."""

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append(params)
        if params.get("list") == "search":
            hits = [{"title": "Eye Prime"}, {"title": "Eye"}]
            return httpx.Response(200, json={"query": {"search": hits}})
        if params["page"] in {"Eye", "Eye Prime"}:
            html = PAGE_HTML if params.get("section") == "0" else FULL_HTML
            return httpx.Response(200, json={"parse": {"title": params["page"], "text": html}})
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
    # What's left of the phrasing once search found the page is a question for the whole page.
    assert card.details == ["Tips: Beat it with arrows from a high platform."]
    assert "section" not in calls[-1]

    message = card_message(card, "c1")
    assert message.body == (
        "The Eye is a boss. It flies.\n\n"
        "Tips: Beat it with arrows from a high platform.\n\n"
        "Max Life: 2800"
    )
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


async def test_a_question_reads_the_whole_page_for_the_part_that_answers_it() -> None:
    calls: list[dict[str, str]] = []
    research = WikiResearch(SITE, transport=httpx.MockTransport(wiki_handler(calls)))
    card = await research.lookup("Eye", "how do I craft its lure?")
    assert card is not None
    assert card.details == ["Crafting, Recipes: Eye Lure | Lens 6"]
    assert "section" not in calls[0]
    assert "From the page: Crafting, Recipes: Eye Lure | Lens 6" in card.context_text()

    # Details answer one question, so a plain lookup afterwards comes from memory without them.
    plain = await research.lookup("Eye")
    assert plain is not None and plain.details == [] and len(calls) == 1
    await research.aclose()


async def test_a_question_that_only_names_the_page_needs_only_the_intro() -> None:
    calls: list[dict[str, str]] = []
    research = WikiResearch(SITE, transport=httpx.MockTransport(wiki_handler(calls)))
    card = await research.lookup("Eye", "what is the eye?")
    assert card is not None and card.details == []
    assert calls[0]["section"] == "0"
    await research.aclose()


def offline(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"Expected no request, got {request.url}")


@pytest.mark.parametrize("topic", ["", "wiki", "the Test wiki", "Main Page", "official wiki"])
async def test_asking_for_the_wiki_itself_opens_its_main_page(topic: str) -> None:
    research = WikiResearch(MAIN_SITE, transport=httpx.MockTransport(offline))
    card = await research.lookup(topic)
    assert card is not None and card.title == "Test Wiki"
    assert card_message(card, open_page=True).page_url == "https://wiki.test/wiki/Test_Wiki"
    await research.aclose()


@pytest.mark.parametrize("topic", ["Test", "Eye wiki", "Eye"])
def test_a_page_named_with_or_like_the_wiki_isnt_the_main_page(topic: str) -> None:
    # A bare game name is usually a real article about the game.
    assert not names_main_page(topic, MAIN_SITE.info)


async def test_a_page_that_turns_out_to_be_the_main_page_still_opens() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        # Redirected to the main page, which has no intro or infobox to build a card from.
        html = '<div class="mw-parser-output"><div class="welcome">Welcome</div></div>'
        return httpx.Response(200, json={"parse": {"title": "Test Wiki", "text": html}})

    research = WikiResearch(MAIN_SITE, transport=httpx.MockTransport(handler))
    card = await research.lookup("Portal")
    assert card is not None and card.source_url == "https://wiki.test/wiki/Test_Wiki"
    await research.aclose()


def test_every_card_for_a_page_shares_one_id() -> None:
    eye = WikiCard(title="Eye", summary="", source_url="https://wiki.test/wiki/Eye", site_name="T")
    prime = eye.model_copy(update={"source_url": "https://wiki.test/wiki/Eye_Prime"})
    assert card_message(eye).card_id == card_message(eye, open_page=True).card_id
    assert card_message(eye).card_id != card_message(prime).card_id
    assert card_message(eye, "c1").card_id == "c1"


async def test_site_info_reads_the_main_pages_title() -> None:
    general = {
        "sitename": "Test Wiki",
        "server": "//wiki.test",
        "articlepath": "/wiki/$1",
        "mainpage": "Test Wiki",
    }
    reply = httpx.Response(200, json={"query": {"general": general}})
    client = MediaWikiClient(SITE.api_url, httpx.MockTransport(lambda _: reply))
    info = await client.site_info()
    assert info.main_page == "Test Wiki" and info.server == "https://wiki.test"
    await client.aclose()


def test_details_skip_what_the_summary_already_says() -> None:
    summary = "The Eye is a boss. It flies."
    passages = [
        "The Eye is a boss. It flies. It appears at night.",
        "The Eye is a boss.",
        "Tips: Hide.",
    ]
    assert beyond(summary, passages) == ["It appears at night.", "Tips: Hide."]
    # A summary cut short ends in an ellipsis, which the page itself doesn't have.
    assert beyond("Cut off…", ["Cut off here."]) == ["here."]
