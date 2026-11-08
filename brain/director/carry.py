"""Starts the player's next turn with the words of one whose reply they never heard.

Speech-to-text sometimes ends a turn mid-thought: "I like building a lot, but I'm not doing that",
then "today." The second part cancels the first one's reply before it's said, and on its own it
means nothing, so the partner asked its question again. Starting the next turn with the cut-off
words gives the model everything the player said. Typed turns sent in quick succession merge the
same way.
"""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace

from brain.director.rules import AskTalker

log = logging.getLogger(__name__)

# Past this, the cut-off words belong to an older thought, such as a start of speech that never
# became a turn.
CARRY_S = 30.0


class Carry:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        # The turn being answered, until anything is said for it.
        self._open: AskTalker | None = None
        self._cut: tuple[str, float] | None = None

    @contextmanager
    def answering(self, turn: AskTalker) -> Iterator[None]:
        self._open = turn
        try:
            yield
        finally:
            # Identity, because a cancelled turn can finish after the next one has started.
            if self._open is turn:
                self._open = None

    def spoke(self) -> None:
        """A reply or a "looking" line was said, so the player heard back and nothing carries."""
        self._open = None

    def cut_off(self) -> None:
        """The slot is being cancelled. Keeps the open turn's words, since it was never answered."""
        if self._open is not None:
            self._cut = (self._open.transcript, self._clock())
            self._open = None

    def into(self, turn: AskTalker) -> AskTalker:
        """The next turn, starting with any words cut off just before it."""
        cut, self._cut = self._cut, None
        if cut is None:
            return turn
        words, at = cut
        if self._clock() - at > CARRY_S:
            log.debug("Not carrying words cut off %.0f s ago: %r", self._clock() - at, words)
            return turn
        log.info("Carrying a cut-off turn into the next: %r + %r", words, turn.transcript)
        return replace(turn, transcript=f"{words} {turn.transcript}")
