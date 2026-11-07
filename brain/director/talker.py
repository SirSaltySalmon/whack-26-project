"""Turns the player's words into one short spoken reply via the fast LLM."""

import logging
import re

from brain.llm.base import LLMEmptyResponseError, LLMUnavailableError, TextLLM

log = logging.getLogger(__name__)

# The personality name comes from the overlay settings, so swapping one is data, not a branch.
SYSTEM_PROMPT = """You are the player's {personality} co-op partner, watching their game.
Everything you write is spoken aloud over live gameplay, so:
- Reply in {max_words} words or fewer, one sentence, no lists, markdown or emoji.
- If you can't see or don't know something, say so in a few words rather than guessing."""

# Enough for a 12-word sentence with room to spare; the word cap does the real limiting.
MAX_TOKENS = 64


def cap_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return " ".join(words)
    clipped = " ".join(words[:max_words]).rstrip(",;:-")
    return clipped if re.search(r"[.!?]$", clipped) else clipped + "."


async def reply(llm: TextLLM, transcript: str, personality: str, max_words: int) -> str | None:
    """Returns None when there's nothing to say, so the caller can stay quiet."""
    system = SYSTEM_PROMPT.format(personality=personality, max_words=max_words)
    parts: list[str] = []
    try:
        async for chunk in llm.stream_text(system, transcript, MAX_TOKENS):
            parts.append(chunk)
            # Stop paying for tokens we'd cut anyway.
            if len("".join(parts).split()) > max_words:
                break
    except (LLMUnavailableError, LLMEmptyResponseError) as exc:
        log.warning("Talker unavailable, staying quiet: %s", exc)
        return None
    text = cap_words("".join(parts), max_words)
    return text or None
