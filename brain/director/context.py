"""What a reply gets to know, fetched so a failure costs the context and never the reply.

Every spoken reply gets the same TalkerContext from memory: player turns, game-event reactions,
tips and think_hard all see one conversation. The director adds to LIVE what only it knows.
"""

import logging
from collections.abc import Callable

from brain.director.partner_state import YOU_LABEL, PartnerState
from brain.memory.layers import ContextSource, TalkerContext

log = logging.getLogger(__name__)

# The page excerpt's header runs to the first ": ", and the rest is the page.
_PAGE_LABEL = "OPEN PAGE"


def open_page_excerpt(excerpt: Callable[[str], str | None] | None, transcript: str) -> str | None:
    if excerpt is None:
        return None
    try:
        return excerpt(transcript)
    except Exception:
        # The wiki page is a bonus; the turn goes ahead without it.
        log.exception("Couldn't match the open page")
        return None


async def gather_context(
    context: ContextSource | None, query: str, current: str | None = None
) -> TalkerContext:
    """`current` is the words being answered, which only a player turn has."""
    if context is None:
        return TalkerContext()
    try:
        return await context(query, current)
    except Exception:
        # A reply without memory beats no reply at all.
        log.exception("Couldn't build the talker's context")
        return TalkerContext()


def with_partner(context: ContextSource | None, partner: PartnerState) -> ContextSource:
    """Every reply's context, with YOU added to LIVE: what the partner itself said lately.

    Wrapping the source reaches player turns, game-event reactions and tips alike. YOU comes from
    the director's own record, not memory, so it's still there when memory fails.
    """

    async def source(query: str, current: str | None) -> TalkerContext:
        gathered = await gather_context(context, query, current)
        you = partner.render()
        return gathered.with_live(YOU_LABEL, you) if you else gathered

    return source


async def player_context(
    context: ContextSource | None,
    excerpt: Callable[[str], str | None] | None,
    transcript: str,
) -> TalkerContext:
    """For player turns only, so page text can never reach a game-event reaction or a tip."""
    gathered = await gather_context(context, transcript, transcript)
    page = open_page_excerpt(excerpt, transcript)
    if not page:
        return gathered
    label, found, body = page.partition(": ")
    if found and "\n" not in label:
        return gathered.with_live(label, body)
    return gathered.with_live(_PAGE_LABEL, page)
