"""Shows the partner's lines as subtitles when the TTS service fails, so it never goes silent.

Subtitles for spoken lines come from the TTS service's word timings, which only arrive with the
audio. A rejected key or used-up credits therefore hid every line, not just its sound: in a live
run the overlay showed nothing but the prerecorded barks.
"""

import logging
from collections import deque
from typing import Protocol

from pipecat.frames.frames import ErrorFrame

log = logging.getLogger(__name__)

# Pipecat stops using a TTS service after three lines in a row come back with no audio.
FAILURES_BEFORE_GIVING_UP = 3
# Failures that won't fix themselves within a session, so there's no point trying again.
LASTING = frozenset({"authentication", "authorization", "quota"})


class Subtitles(Protocol):
    async def say(self, text: str) -> bool: ...


class SpeechFallback:
    """Tracks the lines sent to TTS that haven't played yet, oldest first.

    TTS reports failures one line at a time, in order, so the oldest waiting line is the one
    that failed. A bark ending also counts as a line played, which can drop one waiting line
    from the record. That costs a subtitle at worst, never a wrong one.
    """

    def __init__(self, subtitles: Subtitles) -> None:
        self._subtitles = subtitles
        self._waiting: deque[str] = deque()
        self._failures = 0
        self.given_up = False

    def queued(self, text: str) -> None:
        self._waiting.append(text)

    def played(self) -> None:
        if self._waiting:
            self._waiting.popleft()
        self._failures = 0

    def interrupted(self) -> None:
        # Barge-in drops queued lines, so none of them will play or fail.
        self._waiting.clear()

    async def failed(self, error: ErrorFrame) -> None:
        self._failures += 1
        category = error.category.value if error.category is not None else "unknown"
        if not self.given_up and (
            category in LASTING or self._failures >= FAILURES_BEFORE_GIVING_UP
        ):
            self.given_up = True
            log.warning("Speech failed (%s): replying in subtitles from now on", category)
        if self._waiting:
            await self._subtitles.say(self._waiting.popleft())
