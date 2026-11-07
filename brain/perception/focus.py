"""How often the observer reports on the screen: slowly by default, faster for a while on a boost.

Looking less often when nothing is happening saves most of the vision cost. A boost raises the
rate for a short hold and then drops back by itself, so nothing has to remember to turn it off.
Boosts come from two places. Rules boost on danger with no model call, and keep boosting while it
lasts. The player-turn tool covers moments rules can't see, such as the player saying "watch this".
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)

Level = Literal["low", "medium", "high"]
LEVELS: tuple[Level, ...] = ("low", "medium", "high")
# How long the talker is told a boost ended. It's told so it doesn't think it's still watching
# closely, and told it's nothing to act on, so it doesn't remark on it.
ENDED_NOTICE_S = 15.0


@dataclass(frozen=True)
class FocusIntervals:
    """Seconds between reports at each level."""

    low_s: float
    medium_s: float
    high_s: float

    def of(self, level: Level) -> float:
        return {"low": self.low_s, "medium": self.medium_s, "high": self.high_s}[level]


class Focus:
    def __init__(
        self,
        intervals: FocusIntervals,
        hold_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.intervals = intervals
        self.hold_s = hold_s
        self._clock = clock
        # One hold per reason, so a fight ending doesn't cut short a boost the player asked for.
        self._holds: dict[str, tuple[Level, float]] = {}
        self._current: Level = "low"
        self._ended_at: float | None = None
        # Set on every boost, so the observer can look sooner instead of finishing a slow wait.
        self.changed = asyncio.Event()

    def boost(self, level: Level, reason: str) -> None:
        """Raises the rate for hold_s from now. Repeating a boost extends it rather than adding."""
        now = self._clock()
        if level == "low":
            self._holds.pop(reason, None)
        else:
            self._holds[reason] = (level, now + self.hold_s)
        self.level(now)
        self.changed.set()

    def level(self, now: float | None = None) -> Level:
        now = self._clock() if now is None else now
        self._holds = {reason: hold for reason, hold in self._holds.items() if hold[1] > now}
        level = max((hold[0] for hold in self._holds.values()), key=LEVELS.index, default="low")
        if level != self._current:
            log.info("Watching the game at %s focus", level)
            if level == "low":
                self._ended_at = now
            self._current = level
        return level

    def interval_s(self, now: float | None = None) -> float:
        return self.intervals.of(self.level(now))

    def live_state(self, now: float | None = None) -> dict[str, str]:
        now = self._clock() if now is None else now
        level = self.level(now)
        if level != "low":
            left = max(until for _, until in self._holds.values()) - now
            reasons = ", ".join(sorted(self._holds))
            return {"watching": f"closely ({level}, {left:.0f} s left, for: {reasons})"}
        if self._ended_at is not None and now - self._ended_at < ENDED_NOTICE_S:
            return {"watching": "back to normal; nothing to say or do about it"}
        return {}
