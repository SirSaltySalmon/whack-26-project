"""Web search behind one interface, used only to locate a wiki when known hosts fail."""

import logging
from typing import Protocol

log = logging.getLogger(__name__)


class WebSearch(Protocol):
    async def urls(self, query: str, limit: int) -> list[str]: ...


class ExaSearch:
    def __init__(self, api_key: str) -> None:
        # Imported lazily so the brain still starts when Exa is cut or not installed.
        from exa_py import AsyncExa

        self._exa = AsyncExa(api_key=api_key)

    async def urls(self, query: str, limit: int) -> list[str]:
        try:
            response = await self._exa.search(query, num_results=limit, contents=False)
        except Exception:
            # Any vendor failure only means "no fallback"; discovery logs and carries on.
            log.exception("Exa search failed for %r", query)
            return []
        return [r.url for r in response.results if getattr(r, "url", None)]
