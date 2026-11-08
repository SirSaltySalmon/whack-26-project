"""Asks memory's next question aloud, and puts it back if it was never heard.

Only ever spoken: showing questions as a card pulled the player's eyes off the game. Taking one
marks it asked, so one the voice never said, or a barge-in cut off before it began, goes back to
the queue rather than being lost or timing out unanswered.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from shared.protocol.messages import QuestionAsk

log = logging.getLogger(__name__)


class Questions:
    def __init__(
        self,
        take: Callable[[], Awaitable[QuestionAsk | None]] | None,
        release: Callable[[str], Awaitable[None]] | None,
    ) -> None:
        self._take = take
        self._release = release
        self._background: set[asyncio.Task[None]] = set()

    async def ask(self, speak: Callable[[str], Awaitable[bool]]) -> None:
        """`speak` returns whether the voice accepted the line."""
        if self._take is None:
            return
        question = await self._take()
        if question is None:
            return
        said = False
        try:
            said = await speak(question.text)
        finally:
            # Also on a barge-in, which cancels this before the question was ever heard.
            if not said:
                self._put_back(question)

    def _put_back(self, question: QuestionAsk) -> None:
        release = self._release
        if release is None:
            log.warning("Question never said and can't go back in the queue: %s", question.text)
            return
        log.info("Question never said; back in the queue: %s", question.text)
        # Its own task, because the one asking may be the one being cancelled.
        task = asyncio.create_task(self._release_safely(release, question.question_id))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _release_safely(
        self, release: Callable[[str], Awaitable[None]], question_id: str
    ) -> None:
        try:
            await release(question_id)
        except Exception:
            log.exception("Couldn't put question %s back in the queue", question_id)
