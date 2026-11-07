import httpx
import pytest

from brain.research.mediawiki import MediaWikiClient


async def test_parses_and_caches_pages() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["action"] == "parse"
        return httpx.Response(200, json={"parse": {"title": "Eye", "text": "<p>Boss</p>"}})

    client = MediaWikiClient("https://wiki.test/api.php", httpx.MockTransport(handler))
    assert (await client.parse_page("Eye")).html == "<p>Boss</p>"
    await client.parse_page("Eye")
    assert calls == 1
    await client.aclose()


async def test_wiki_errors_raise() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"error": {"code": "missingtitle"}})
    )
    client = MediaWikiClient("https://wiki.test/api.php", transport)
    with pytest.raises(LookupError):
        await client.parse_page("Nope")
    await client.aclose()
