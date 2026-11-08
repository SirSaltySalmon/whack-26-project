"""Follows the player's settings while the voice runs.

Kept out of pipecat_voice.py so it needs no audio devices to test.
"""

import asyncio
import logging
from typing import Protocol

from brain.events import Event, GameEvent, SettingsChanged

log = logging.getLogger(__name__)

# The same events the director's rules use to decide the player is in danger.
_DANGER_RISING = frozenset({"danger_started", "danger_high"})
_DANGER_OVER = frozenset({"danger_ended", "player_died"})


class FollowingVoice(Protocol):
    async def set_style(self, style: str, urgent: bool = False) -> None: ...

    async def interrupt(self) -> None: ...


def silenced(settings: object) -> bool:
    """Paused by the player. Typed loosely, like the director's rules."""
    return bool(getattr(settings, "paused", False))


async def follow_settings(
    events: "asyncio.Queue[Event]", voice: FollowingVoice, style: str = "expressive"
) -> None:
    """Also speeds the voice up a little while the player is in danger."""
    was_silenced = False
    urgent = False
    while True:
        event = await events.get()
        if isinstance(event, GameEvent):
            if event.name in _DANGER_RISING | _DANGER_OVER:
                urgent = event.name in _DANGER_RISING
                await voice.set_style(style, urgent)
            continue
        if not isinstance(event, SettingsChanged):
            continue
        chosen = getattr(event.settings, "voice_style", None)
        style = chosen if isinstance(chosen, str) else style
        # Blind, it can't see a fight end, as the director's rules also say.
        urgent = urgent and bool(getattr(event.settings, "vision_enabled", True))
        await voice.set_style(style, urgent)
        now_silenced = silenced(event.settings)
        if now_silenced and not was_silenced:
            # The player wants quiet now, not once the current line ends.
            log.info("Paused; cutting off speech in progress")
            await voice.interrupt()
        was_silenced = now_silenced
