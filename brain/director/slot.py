"""The director's one speech slot: the task allowed to speak right now.

Starting or cancelling never waits, so the director's decisions stay instant.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger(__name__)

Work = Coroutine[Any, Any, None]


async def _after(previous: asyncio.Task[None], work: Work) -> None:
    try:
        # wait() rather than await, so a failed or cancelled check doesn't stop this turn.
        await asyncio.wait({previous})
    except asyncio.CancelledError:
        # Only pausing or shutting down cancels a turn queued behind a check, and both mean the
        # check should stop too.
        previous.cancel()
        work.close()
        raise
    await work


class SpeechSlot:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, work: Work) -> None:
        """Replaces whatever is in the slot."""
        self.cancel()
        self._task = asyncio.create_task(work)

    def queue(self, work: Work) -> None:
        """Runs `work` once what's in the slot finishes, however it ends."""
        if self._task is None:
            self._task = asyncio.create_task(work)
            return
        self._task = asyncio.create_task(_after(self._task, work))

    def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            log.debug("Cancelling speech in progress")
            self._task.cancel()
