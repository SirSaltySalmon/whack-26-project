import httpx

from brain.research.discovery import discover_wiki, title_slugs


def siteinfo(name: str, server: str) -> httpx.Response:
    general = {"sitename": name, "server": server, "articlepath": "/wiki/$1"}
    return httpx.Response(200, json={"query": {"general": general}})


class FakeSearch:
    def __init__(self, urls: list[str]) -> None:
        self._urls = urls
        self.queries: list[str] = []

    async def urls(self, query: str, limit: int) -> list[str]:
        self.queries.append(query)
        return self._urls[:limit]


def test_title_slugs() -> None:
    assert title_slugs("The Binding of Isaac") == ["bindingofisaac", "binding-of-isaac"]
    assert title_slugs("Terraria") == ["terraria"]


async def test_prefers_wiki_gg_and_rejects_html_401() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.host == "terraria.wiki.gg":
            return siteinfo("Terraria Wiki", "https://terraria.wiki.gg")
        return httpx.Response(401, text="<html>no wiki</html>")

    site = await discover_wiki("Terraria", transport=httpx.MockTransport(handler))
    assert site is not None and site.api_url == "https://terraria.wiki.gg/api.php"
    assert seen == ["terraria.wiki.gg"]


async def test_skips_wiki_named_for_another_game() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.endswith("fandom.com"):
            return siteinfo("Some Other Game Wiki", "https://other.fandom.com")
        return httpx.Response(404, text="")

    assert await discover_wiki("Celeste", transport=httpx.MockTransport(handler)) is None


async def test_web_search_finds_official_wiki_before_fandom() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "official.test" and path == "/Main_Page":
            link = '<link rel="EditURI" href="//official.test/mw/api.php?action=rsd">'
            return httpx.Response(200, text=f"<html><head>{link}</head></html>")
        if host == "official.test" and path == "/mw/api.php":
            return siteinfo("Stardew Valley Wiki", "//official.test")
        if host.endswith("fandom.com"):
            return siteinfo("Stardew Valley Wiki", "https://stardewvalley.fandom.com")
        return httpx.Response(404, text="")

    search = FakeSearch(["https://official.test/Main_Page"])
    site = await discover_wiki(
        "Stardew Valley", web_search=search, transport=httpx.MockTransport(handler)
    )
    assert site is not None and site.api_url == "https://official.test/mw/api.php"
    assert site.info.page_url("Parsnip Seeds") == "https://official.test/wiki/Parsnip_Seeds"
    assert search.queries == ["Stardew Valley official wiki"]


async def test_override_skips_discovery_and_name_check() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "mywiki.test"
        return siteinfo("Anything", "https://mywiki.test")

    site = await discover_wiki(
        "Terraria",
        override_api_url="https://mywiki.test/api.php",
        transport=httpx.MockTransport(handler),
    )
    assert site is not None and site.info.name == "Anything"
