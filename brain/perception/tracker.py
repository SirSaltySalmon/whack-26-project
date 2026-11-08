"""Decides which per-frame reports to believe, and which changes are worth telling anyone about.

The vision model sometimes hallucinates, so nothing counts until it appears in consecutive frames.
Testing showed what that does and doesn't do. Real fights stayed medium or high on 20 of 20 reads,
and passed 80 of 80 two-frame checks, while calm scenes passed 2 of 160, so it filters flicker
without missing fights. It doesn't catch a stubborn mistake: the same frame can give the same wrong
answer every time. So "confirmed" means stable, not true. Treat it as an observation, not a fact.
"""

from dataclasses import dataclass, field
from typing import Any

from brain.perception.observation import Observation

ELEVATED = ("medium", "high")


@dataclass(frozen=True)
class Change:
    """A confirmed change, published as a GameEvent. Names are generic so any game can use them."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)


def _same_name(first: str, second: str) -> bool:
    """Names vary between frames, such as "Blue Slime" and "the blue slime near the player"."""
    a, b = first.strip().lower(), second.strip().lower()
    return bool(a and b) and (a in b or b in a)


class ObservationTracker:
    def __init__(
        self,
        confirm_frames: int = 2,
        # Slower to clear than to raise, so a brief lull doesn't end the fight and restart it.
        clear_frames: int = 3,
        low_health: float = 0.25,
        health_recovered: float = 0.4,
        health_tolerance: float = 0.1,
        max_gap_s: float = 4.0,
        stale_after_s: float = 5.0,
    ) -> None:
        self._confirm = confirm_frames
        self._clear = clear_frames
        self._low_health = low_health
        self._health_recovered = health_recovered
        self._health_tolerance = health_tolerance
        self._max_gap_s = max_gap_s
        self._stale_after_s = stale_after_s

        self._last_ts: float | None = None
        self._previous: Observation | None = None
        self._elevated_streak = 0
        self._high_streak = 0
        self._calm_streak = 0
        self._screen_streak = 0
        self._no_health_streak = 0

        self._screen: str | None = None
        self._danger: str | None = None
        self._threats: list[str] = []
        self._health: tuple[float, str] | None = None
        self._health_low_reported = False
        self._item: str | None = None
        self._summary: str | None = None
        self._notable: str | None = None
        self._location: str | None = None

    @property
    def danger(self) -> str | None:
        return self._danger

    @property
    def last_frame_ts(self) -> float | None:
        """The frame time of the last report taken, before the next one is."""
        return self._last_ts

    def update(self, observation: Observation, ts: float) -> list[Change]:
        """Takes reports in frame order and returns whatever just became confirmed."""
        if self._last_ts is not None and ts - self._last_ts > self._max_gap_s:
            # Frames this far apart, say after an alt-tab, say nothing about each other.
            self._forget_streaks()
        self._last_ts = ts

        changes = self._update_danger(observation)
        changes += self._update_screen(observation)
        changes += self._update_health(observation)
        self._update_item(observation)
        self._update_description(observation)
        self._previous = observation
        return changes

    def live_state(self, now: float) -> dict[str, str]:
        """What the talker may rely on right now. Only confirmed values, and nothing stale.

        Most important first, because memory cuts this to a fixed length.
        """
        if self._last_ts is None or now - self._last_ts > self._stale_after_s:
            return {"screen": "can't see the game right now"}
        state: dict[str, str] = {}
        state["danger"] = self._danger or "none"
        if self._threats:
            state["threats"] = ", ".join(self._threats)
        if self._health:
            state["health"] = f"{self._health[1]} ({round(self._health[0] * 100)}%)"
        if self._screen:
            state["screen"] = self._screen
        if self._notable:
            state["notable"] = self._notable
        if self._summary:
            state["seen"] = self._summary
        if self._item:
            state["held item"] = self._item
        if self._location:
            state["location"] = self._location
        return state

    def _forget_streaks(self) -> None:
        self._previous = None
        self._elevated_streak = self._high_streak = self._calm_streak = 0
        self._screen_streak = self._no_health_streak = 0

    def _agreed_threats(self, observation: Observation) -> list[str]:
        if self._previous is None:
            return []
        return [
            threat
            for threat in observation.threats
            if any(_same_name(threat, earlier) for earlier in self._previous.threats)
        ]

    def _update_danger(self, observation: Observation) -> list[Change]:
        level = observation.danger_level
        if level in ELEVATED:
            self._elevated_streak += 1
            self._calm_streak = 0
        else:
            self._elevated_streak = 0
            self._calm_streak += 1
        self._high_streak = self._high_streak + 1 if level == "high" else 0

        agreed = self._agreed_threats(observation)
        if self._danger is None:
            if self._elevated_streak < self._confirm:
                return []
            self._danger = "high" if self._high_streak >= self._confirm else "medium"
            self._threats = agreed
            return [Change("danger_started", {"level": self._danger, "threats": agreed})]

        if self._calm_streak >= self._clear:
            self._danger = None
            self._threats = []
            return [Change("danger_ended")]
        if agreed:
            self._threats = agreed
        if self._danger == "medium" and self._high_streak >= self._confirm:
            self._danger = "high"
            return [Change("danger_high", {"threats": self._threats})]
        return []

    def _update_screen(self, observation: Observation) -> list[Change]:
        same = self._previous and self._previous.screen_type == observation.screen_type
        self._screen_streak = self._screen_streak + 1 if same else 1
        if self._screen_streak < self._confirm or self._screen == observation.screen_type:
            return []
        self._screen = observation.screen_type
        return [Change("player_died")] if self._screen == "death" else []

    def _update_health(self, observation: Observation) -> list[Change]:
        if not observation.health_visible:
            self._no_health_streak += 1
            if self._no_health_streak >= self._confirm:
                self._health = None
            return []
        self._no_health_streak = 0

        previous = self._previous
        fraction = observation.health_fraction
        before = previous.health_fraction if previous else None
        if fraction is None or before is None or "health_raw" in observation.unsure:
            return []
        if abs(fraction - before) > self._health_tolerance:
            return []

        self._health = (fraction, observation.health_raw or "")
        if fraction >= self._health_recovered:
            self._health_low_reported = False
        if fraction <= self._low_health and not self._health_low_reported:
            self._health_low_reported = True
            return [Change("health_low", {"percent": round(fraction * 100)})]
        return []

    def _update_item(self, observation: Observation) -> None:
        item = observation.selected_item
        previous = self._previous.selected_item if self._previous else None
        if item is None and previous is None:
            self._item = None
        elif item and previous and _same_name(item, previous):
            self._item = item

    def _update_description(self, observation: Observation) -> None:
        """Text from a frame claiming danger nothing has confirmed could repeat a hallucination."""
        unconfirmed_danger = observation.danger_level in ELEVATED and self._danger is None
        if unconfirmed_danger:
            return
        self._summary = observation.summary
        self._location = observation.location
        self._notable = (
            None if observation.threats and self._danger is None else observation.notable
        )
