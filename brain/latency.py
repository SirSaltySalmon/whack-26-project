"""Measures reactions from the frame that showed something, which is what "as it happens" means.

An event's own `ts` is when perception published it, seconds after the frame for the vision
observer. Timing from there would hide the slowest part, so reactions carry an `Origin` holding
the frame's capture time, and the log splits the total into noticing and speaking.

`scripts/latency_report.py` and the Control Center's Latency tab parse these lines, so change the
formats there too.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from brain.events import GameEvent

log = logging.getLogger(__name__)

# Audio that starts this long after it was queued belongs to something else: the line was dropped
# without an interruption, say a TTS failure, so timing it would report a made-up number.
STALE_AFTER_S = 10.0


@dataclass(frozen=True)
class Origin:
    """A game event, and when the frame that first showed it was captured (monotonic)."""

    event: str
    source: str
    frame_ts: float
    event_ts: float

    @classmethod
    def of(cls, event: GameEvent) -> "Origin | None":
        if event.frame_ts is None:
            return None
        return cls(event.name, event.source, event.frame_ts, event.ts)


def log_frame_latency(kind: str, origin: Origin, now: float) -> None:
    """`kind` is what was reached: "bark" once its audio is queued, "first audio" once it plays."""
    log.info(
        "Latency: frame to %s %.0f ms (%s from %s: noticed in %.0f, spoke in %.0f)",
        kind,
        (now - origin.frame_ts) * 1000,
        origin.event,
        origin.source,
        (origin.event_ts - origin.frame_ts) * 1000,
        (now - origin.event_ts) * 1000,
    )


class FirstAudio:
    """Times how long until the partner's audio starts, from a player's turn or a seen frame.

    The voice calls this, because only it knows when audio really starts playing.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._turn_ended_at: float | None = None
        self._origin: Origin | None = None
        self._queued_at = 0.0

    def turn_started(self) -> None:
        # The player's new turn interrupts whatever was queued, so its audio will never start.
        self._turn_ended_at = None
        self._origin = None

    def turn_ended(self) -> None:
        self._turn_ended_at = self._clock()

    def queued(self, origin: Origin | None, speaking: bool) -> None:
        """Call when a reaction's line is queued. `speaking` is whether audio is already playing."""
        if origin is None:
            return
        if speaking:
            # It plays after the current line, perhaps with no new start, so a later start could
            # be credited to it. Better no number than a wrong one.
            log.debug("Not timing %s: queued behind speech", origin.event)
            return
        self._origin = origin
        self._queued_at = self._clock()

    def started(self) -> None:
        now = self._clock()
        if self._turn_ended_at is not None:
            ms = (now - self._turn_ended_at) * 1000
            log.info("Latency: end of turn to first audio %.0f ms", ms)
            self._turn_ended_at = None
        origin, self._origin = self._origin, None
        if origin is None:
            return
        if now - self._queued_at > STALE_AFTER_S:
            log.debug("Not timing %s: its audio never started", origin.event)
            return
        log_frame_latency("first audio", origin, now)
