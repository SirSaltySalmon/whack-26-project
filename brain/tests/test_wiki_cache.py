import sqlite3
from collections.abc import AsyncIterator, Callable
from typing import TypeVar

import httpx
import pytest

from brain.memory.db import Database, connect
from brain.research.mediawiki import MediaWikiClient, WikiPage
from brain.research.wiki_cache import WikiCache

API_URL = "https://wiki.test/api.php"
T = TypeVar("T")


class FailingDatabase(Database):
    async def run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        raise sqlite3.OperationalError("disk I/O error")


class Wiki:
    """A fake wiki that counts requests, because caching is about what never reaches the network."""

    def __init__(self) -> None:
        self.calls = 0

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            return httpx.Response(
                200, json={"parse": {"title": "Resolved Title", "text": f"<p>{self.calls}</p>"}}
            )

        return httpx.MockTransport(handler)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    db = Database(connect(":memory:"))
    yield db
    db.close()


async def test_get_returns_none_for_unknown_pages(database: Database) -> None:
    assert await WikiCache(database).get(API_URL, "Nope") is None


async def test_put_then_get_and_replace(database: Database) -> None:
    cache = WikiCache(database)
    await cache.put(API_URL, "Eye", WikiPage("Eye", "<p>one</p>"))
    assert await cache.get(API_URL, "Eye") == WikiPage("Eye", "<p>one</p>")
    await cache.put(API_URL, "Eye", WikiPage("Eye", "<p>two</p>"))
    assert await cache.get(API_URL, "Eye") == WikiPage("Eye", "<p>two</p>")


async def test_pages_expire_at_max_age(database: Database) -> None:
    clock = Clock()
    cache = WikiCache(database, clock=clock, max_age_s=60.0)
    await cache.put(API_URL, "Eye", WikiPage("Eye", "<p>old</p>"))
    clock.now += 60.0
    assert await cache.get(API_URL, "Eye") is not None
    clock.now += 1.0
    assert await cache.get(API_URL, "Eye") is None


async def test_cache_hit_survives_a_new_client(database: Database) -> None:
    wiki = Wiki()
    first = MediaWikiClient(API_URL, wiki.transport(), cache=WikiCache(database))
    fetched = await first.parse_page("Eye")
    await first.aclose()

    second = MediaWikiClient(API_URL, wiki.transport(), cache=WikiCache(database))
    assert await second.parse_page("Eye") == fetched
    await second.aclose()
    assert wiki.calls == 1


async def test_ram_answers_before_the_persistent_cache(database: Database) -> None:
    wiki = Wiki()
    client = MediaWikiClient(API_URL, wiki.transport(), cache=WikiCache(database))
    await client.parse_page("Eye")
    await database.run(lambda conn: conn.execute("DELETE FROM wiki_cache"))
    await client.parse_page("Eye")
    await client.aclose()
    assert wiki.calls == 1


async def test_expired_pages_are_fetched_again(database: Database) -> None:
    clock = Clock()
    wiki = Wiki()
    cache = WikiCache(database, clock=clock, max_age_s=60.0)
    first = MediaWikiClient(API_URL, wiki.transport(), cache=cache)
    await first.parse_page("Eye")
    await first.aclose()

    clock.now += 61.0
    second = MediaWikiClient(API_URL, wiki.transport(), cache=cache)
    assert (await second.parse_page("Eye")).html == "<p>2</p>"
    await second.aclose()
    assert wiki.calls == 2
    assert await cache.get(API_URL, "Eye") == WikiPage("Resolved Title", "<p>2</p>")


async def test_key_is_the_requested_page_not_the_redirect_title(database: Database) -> None:
    wiki = Wiki()
    cache = WikiCache(database)
    client = MediaWikiClient(API_URL, wiki.transport(), cache=cache)
    await client.parse_page("Alias")
    await client.aclose()
    assert await cache.get(API_URL, "Alias") == WikiPage("Resolved Title", "<p>1</p>")
    assert await cache.get(API_URL, "Resolved Title") is None


async def test_pages_from_another_wiki_are_not_reused(database: Database) -> None:
    wiki = Wiki()
    cache = WikiCache(database)
    first = MediaWikiClient(API_URL, wiki.transport(), cache=cache)
    await first.parse_page("Eye")
    await first.aclose()

    other = MediaWikiClient("https://other.test/api.php", wiki.transport(), cache=cache)
    await other.parse_page("Eye")
    await other.aclose()
    assert wiki.calls == 2


async def test_failing_cache_still_answers_from_the_network(
    caplog: pytest.LogCaptureFixture,
) -> None:
    database = FailingDatabase(connect(":memory:"))
    wiki = Wiki()
    client = MediaWikiClient(API_URL, wiki.transport(), cache=WikiCache(database))
    page = await client.parse_page("Eye")
    await client.aclose()
    database.close()
    assert page == WikiPage("Resolved Title", "<p>1</p>")
    assert wiki.calls == 1
    assert "read failed" in caplog.text
    assert "write failed" in caplog.text


async def test_wiki_errors_are_not_cached(database: Database) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"error": {"code": "missingtitle"}})

    cache = WikiCache(database)
    client = MediaWikiClient(API_URL, httpx.MockTransport(handler), cache=cache)
    for _ in range(2):
        with pytest.raises(LookupError):
            await client.parse_page("Nope")
    await client.aclose()
    assert calls == 2
    assert await cache.get(API_URL, "Nope") is None
