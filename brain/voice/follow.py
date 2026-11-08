"""Follows the player's settings while the voice runs.

Kept out of pipecat_voice.py so it needs no audio devices to test.
"""

import asyncio
import logging
from typing import Protocol

from brain.events import Event, SettingsChanged

log = logging.getLogger(__name__)


class FollowingVoice(Protocol):
    async def set_style(self, style: str) -> None: ...

    async def interrupt(self) -> None: ...


def silenced(settings: object) -> bool:
    """Paused by the player. Typed loosely, like the director's rules."""
    return bool(getattr(settings, "paused", False))


async def follow_settings(events: "asyncio.Queue[Event]", voice: FollowingVoice) -> None:
    was_silenced = False
    while True:
        event = await events.get()
        if not isinstance(event, SettingsChanged):
            continue
        style = getattr(event.settings, "voice_style", None)
        if isinstance(style, str):
            await voice.set_style(style)
        now_silenced = silenced(event.settings)
        if now_silenced and not was_silenced:
            # The player wants quiet now, not once the current line ends.
            log.info("Paused; cutting off speech in progress")
            await voice.interrupt()
        was_silenced = now_silenced
