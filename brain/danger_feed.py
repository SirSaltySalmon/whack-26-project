"""Tells the overlay how much danger the player is in, so it can show it without words.

The tracker already decides when danger starts, rises and ends. This only forwards those events,
so the overlay's alert and the director's spoken line come from the same rule.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from brain.events import EventBus, GameEvent, OverlayConnected, SettingsChanged
from shared.protocol.messages import BrainMessage, DangerState

log = logging.getLogger(__name__)

Level = Literal["none", "medium", "high"]


def level_after(current: Level, event: GameEvent) -> Level:
    """The danger level once `event` has happened. Unrelated events leave it as it was."""
    if event.name == "danger_started":
        return "high" if event.data.get("level") == "high" else "medium"
    if event.name == "danger_high":
        return "high"
    if event.name in ("danger_ended", "player_died"):
        return "none"
    return current


async def forward_danger(bus: EventBus, send: Callable[[BrainMessage], Awaitable[None]]) -> None:
    queue = bus.subscribe()
    level: Level = "none"
    while True:
        event = await queue.get()
        if isinstance(event, OverlayConnected):
            # A reconnecting overlay has forgotten, and would otherwise miss a fight in progress.
            if level != "none":
                await send(DangerState(level=level))
            continue
        if isinstance(event, SettingsChanged):
            if level != "none" and not getattr(event.settings, "vision_enabled", True):
                # Blinded, the partner can't see the fight, so it stops showing one.
                level = "none"
                log.debug("Danger cleared: vision turned off")
                await send(DangerState(level=level))
            continue
        if not isinstance(event, GameEvent):
            continue
        new = level_after(level, event)
        if new != level:
            level = new
            log.debug("Danger is now %s", level)
            await send(DangerState(level=level))
