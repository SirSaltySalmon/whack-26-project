"""Finds a game's wiki from its title, with no per-game code.

Order: an explicit override, then wiki.gg (home of many official wikis) and self-hosted
`<game>.wiki`, then a web search if configured, then Fandom last. Search results are only used
to find the wiki's `api.php` through MediaWiki's standard EditURI link; they are never shown.
"""

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from brain.research.mediawiki import MediaWikiClient, SiteInfo, make_client
from brain.research.websearch import WebSearch

log = logging.getLogger(__name__)

_EDIT_URI = re.compile(r"""<link[^>]+rel=["']EditURI["'][^>]*href=["']([^"']+)["']""", re.I)
_PREFERRED_HOSTS = ("https://{slug}.wiki.gg/api.php", "https://{slug}.wiki/api.php")
_FALLBACK_HOSTS = ("https://{slug}.fandom.com/api.php",)
_COMMON_API_PATHS = ("/api.php", "/w/api.php", "/mediawiki/api.php")
_MAX_PAGE_BYTES = 512_000


@dataclass(frozen=True)
class WikiSite:
    api_url: str
    info: SiteInfo


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def title_slugs(game_title: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", game_title.casefold())
    if words and words[0] == "the" and len(words) > 1:
        words = words[1:]
    slugs = ["".join(words), "-".join(words)]
    return [s for i, s in enumerate(slugs) if s and s not in slugs[:i]]


def _matches_game(info: SiteInfo, game_title: str) -> bool:
    """Stops a generic Fandom subdomain for a different game from being accepted."""
    wanted = title_slugs(game_title)[0] if title_slugs(game_title) else ""
    haystack = _compact(info.name) + _compact(urlparse(info.server).netloc)
    return bool(wanted) and wanted in haystack


async def probe(
    api_url: str, game_title: str | None, transport: httpx.AsyncBaseTransport | None = None
) -> WikiSite | None:
    """Accepts a URL only if it serves real MediaWiki siteinfo JSON. Unknown wiki.gg subdomains
    answer with a 401 HTML page, so a status check alone isn't enough."""
    client = MediaWikiClient(api_url, transport)
    try:
        info = await client.site_info()
    except (httpx.HTTPError, LookupError, KeyError, TypeError, ValueError) as exc:
        log.debug("No wiki at %s: %s", api_url, exc)
        return None
    finally:
        await client.aclose()
    if game_title is not None and not _matches_game(info, game_title):
        log.info("Wiki %s (%s) doesn't look like %r; skipping", api_url, info.name, game_title)
        return None
    return WikiSite(api_url, info)


async def _api_from_page(page_url: str, transport: httpx.AsyncBaseTransport | None) -> list[str]:
    candidates: list[str] = []
    async with make_client(transport) as client:
        try:
            response = await client.get(page_url)
            # Only the <head> matters, so don't parse more of an untrusted page than needed.
            match = _EDIT_URI.search(response.text[:_MAX_PAGE_BYTES])
            if match:
                href = match.group(1).replace("&amp;", "&")
                candidates.append(urljoin(str(response.url), href.split("?")[0]))
        except httpx.HTTPError as exc:
            log.info("Couldn't fetch search result %s: %s", page_url, exc)
    parsed = urlparse(page_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    candidates.extend(root + path for path in _COMMON_API_PATHS)
    return list(dict.fromkeys(candidates))


async def discover_wiki(
    game_title: str,
    *,
    override_api_url: str | None = None,
    web_search: WebSearch | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> WikiSite | None:
    if override_api_url:
        # The player or config named the wiki, so don't second-guess its name.
        site = await probe(override_api_url, None, transport)
        if site is None:
            log.warning("Configured wiki %s didn't answer as MediaWiki", override_api_url)
        return site

    site = await _probe_hosts(game_title, _PREFERRED_HOSTS, transport)
    # Fandom often hosts an unofficial fork, so let search find an official wiki first.
    if site is None and web_search is not None:
        site = await _search_for_wiki(game_title, web_search, transport)
    if site is None:
        site = await _probe_hosts(game_title, _FALLBACK_HOSTS, transport)
    if site is None:
        log.warning("No wiki found for %r", game_title)
    return site


async def _probe_hosts(
    game_title: str, templates: tuple[str, ...], transport: httpx.AsyncBaseTransport | None
) -> WikiSite | None:
    for slug in title_slugs(game_title):
        for template in templates:
            site = await probe(template.format(slug=slug), game_title, transport)
            if site:
                log.info("Found wiki for %r: %s (%s)", game_title, site.info.name, site.api_url)
                return site
    return None


async def _search_for_wiki(
    game_title: str, web_search: WebSearch, transport: httpx.AsyncBaseTransport | None
) -> WikiSite | None:
    for url in await web_search.urls(f"{game_title} official wiki", limit=5):
        if urlparse(url).scheme not in {"http", "https"}:
            continue
        for api_url in await _api_from_page(url, transport):
            site = await probe(api_url, game_title, transport)
            if site:
                log.info("Found wiki for %r via web search: %s", game_title, site.api_url)
                return site
    return None
