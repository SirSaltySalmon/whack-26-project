"""Fixed lines for the current personality, with their pre-generated audio once it's ready.

Kept out of director.py so the director stays about when to speak, not what the lines are.
"""

import logging
import time
from collections.abc import Callable
from typing import cast

from brain.director.personalities import LineKind, PersonalityBook
from brain.director.rules import PlayBark
from brain.voice.barks import Bark, BarkBank
from brain.voice.pipeline import Voice

log = logging.getLogger(__name__)


async def play_bark(voice: Voice, bark: Bark, action: PlayBark) -> bool:
    """Returns whether the voice accepted it, so only accepted lines go into memory."""
    event, ts, frame_ts, source = action.event, action.ts, action.frame_ts, action.source
    if not await voice.play(bark):
        log.debug("Player is talking; bark dropped: %s", bark.text)
        return False
    now = time.monotonic()
    if ts is not None:
        # Measured to queuing, which is the part we control; audio follows within a chunk.
        log.info("Latency: event to bark %.0f ms (%s)", (now - ts) * 1000, event)
    if frame_ts is not None and ts is not None:
        # From when it showed on screen, which is what "reacts as it happens" is judged on.
        log.info(
            "Latency: frame to bark %.0f ms (noticed in %.0f, spoke in %.0f, %s, %s)",
            (now - frame_ts) * 1000,
            (ts - frame_ts) * 1000,
            (now - ts) * 1000,
            source or "unknown",
            event,
        )
    return True


class Lines:
    def __init__(
        self,
        book: PersonalityBook,
        personality: Callable[[], str],
        voice_id: Callable[[], str | None],
        barks: BarkBank | None,
    ) -> None:
        self.book = book
        self._personality = personality
        self.voice_id = voice_id
        self.barks = barks
        # Takes turns through each kind's lines rather than picking at random, so tests stay exact.
        self._said = 0

    def text(self, kind: LineKind) -> str:
        self._said += 1
        return self.book.line(self._personality(), kind, self._said)

    def bark(self, kind: str) -> Bark | None:
        """The audio for the next line of this kind, or None if it isn't ready or doesn't exist."""
        voice = self.voice_id()
        if self.barks is None or not voice:
            return None
        self._said += 1
        # Kinds in PlayBark come from data; the bank returns None for one it doesn't have.
        return self.barks.get(self._personality(), cast(LineKind, kind), self._said, voice)

    async def prepare(self, voice_id: str | None) -> None:
        voice = voice_id or self.voice_id()
        if self.barks is not None and voice:
            await self.barks.prepare(voice)

    def next(self, kind: LineKind) -> tuple[str, Bark | None]:
        """The next line, and its audio when ready, so a fallback says the same words."""
        text = self.text(kind)
        voice = self.voice_id()
        if self.barks is None or not voice:
            return text, None
        return text, self.barks.get(self._personality(), kind, self._said, voice)
