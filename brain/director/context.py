"""What a reply gets to know, fetched so a failure costs the context and never the reply."""

import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)


def open_page_excerpt(excerpt: Callable[[str], str | None] | None, transcript: str) -> str | None:
    if excerpt is None:
        return None
    try:
        return excerpt(transcript)
    except Exception:
        # The wiki page is a bonus; the turn goes ahead without it.
        log.exception("Couldn't match the open page")
        return None


async def gather_context(context: Callable[[str], Awaitable[str]] | None, query: str) -> str:
    if context is None:
        return ""
    try:
        return await context(query)
    except Exception:
        # A reply without memory beats no reply at all.
        log.exception("Couldn't build the talker's context")
        return ""


async def player_context(
    context: Callable[[str], Awaitable[str]] | None,
    excerpt: Callable[[str], str | None] | None,
    transcript: str,
) -> str:
    """For player turns only, so page text can never reach a game-event reaction or a tip."""
    gathered = await gather_context(context, transcript)
    page = open_page_excerpt(excerpt, transcript)
    if not page:
        return gathered
    return f"{gathered}\n\n{page}" if gathered else page
