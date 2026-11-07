"""Turns a reader's stream of readings into events, and notices when a reader has stopped working.

Like the observer's tracker, nothing fires on one read: a rule needs `confirm_reads` agreeing reads,
then stays quiet until the value passes `clear_at`, so a value hovering at a threshold can't spam.
"""

from dataclasses import dataclass, field
from typing import Any

from brain.perception.profile_schema import EventRule, ReaderSpec
from brain.perception.readers import FRACTION_TYPES, Reading

# A reader whose rules are all "above" watches something that comes and goes, such as a boss bar.
# Once it's been missing this many reads, it's gone, so its rules may fire again when it returns.
MISSING_RESET_READS = 3


@dataclass
class _RuleState:
    rule: EventRule
    streak: int = 0
    armed: bool = True
    baseline: Any = None  # For "changed": the last confirmed value
    candidate: Any = None  # For "changed": a new value waiting for confirmation


@dataclass(frozen=True)
class Fired:
    event: str
    data: dict[str, Any] = field(default_factory=dict)


def _numeric(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


class ReaderState:
    def __init__(self, spec: ReaderSpec) -> None:
        self.spec = spec
        self._rules = [_RuleState(rule) for rule in spec.rules]
        self.comes_and_goes = bool(spec.rules) and all(r.when == "above" for r in spec.rules)
        self.last: Reading | None = None
        self.last_ok_at: float | None = None
        self._missing = 0
        # Counts only while the game is being played, so menus and death screens don't count.
        self._unreadable_since: float | None = None

    def update(self, reading: Reading, now: float, in_gameplay: bool) -> list[Fired]:
        self.last = reading
        if reading.status == "masked":
            # Our own overlay covers it, which says nothing about the game or the reader.
            return []
        if reading.status == "unreadable":
            self._note_unreadable(now, in_gameplay)
            return []
        self.last_ok_at = now
        self._missing = 0
        self._unreadable_since = None
        fired: list[Fired] = []
        for state in self._rules:
            event = self._check(state, reading)
            if event is not None:
                fired.append(event)
        return fired

    def failing(self, now: float, after_s: float) -> bool:
        since = self._unreadable_since
        return since is not None and now - since >= after_s

    def _note_unreadable(self, now: float, in_gameplay: bool) -> None:
        self._missing += 1
        for state in self._rules:
            state.streak = 0
        if self.comes_and_goes:
            # Absent is its normal state, so it never counts as failing.
            if self._missing >= MISSING_RESET_READS:
                for state in self._rules:
                    state.armed = True
            return
        if not in_gameplay:
            self._unreadable_since = None
        elif self._unreadable_since is None:
            self._unreadable_since = now

    def _event_data(self, reading: Reading) -> dict[str, Any]:
        data: dict[str, Any] = {"value": reading.value, "display": reading.display}
        number = _numeric(reading.value)
        if self.spec.type in FRACTION_TYPES and number is not None:
            data["percent"] = round(number * 100)
        return data

    def _check(self, state: _RuleState, reading: Reading) -> Fired | None:
        rule = state.rule
        if rule.when == "changed":
            return self._check_changed(state, reading)
        number = _numeric(reading.value)
        if number is None or rule.value is None:
            return None
        below = rule.when == "below"
        triggered = number < rule.value if below else number > rule.value
        if not state.armed:
            clear = rule.clear_at if rule.clear_at is not None else rule.value
            # Hysteresis: re-arm only once the value is back past clear_at.
            if (number >= clear) if below else (number <= clear):
                state.armed = True
            state.streak = 0
            return None
        state.streak = state.streak + 1 if triggered else 0
        if state.streak < rule.confirm_reads:
            return None
        state.armed = False
        state.streak = 0
        return Fired(rule.event, self._event_data(reading))

    def _check_changed(self, state: _RuleState, reading: Reading) -> Fired | None:
        value = reading.value
        if state.baseline is None:
            # The first confirmed value is where it starts, not a change.
            state.baseline = value
            return None
        if value == state.baseline:
            state.candidate, state.streak = None, 0
            return None
        if value != state.candidate:
            state.candidate, state.streak = value, 0
        state.streak += 1
        if state.streak < state.rule.confirm_reads:
            return None
        previous, state.baseline = state.baseline, value
        state.candidate, state.streak = None, 0
        return Fired(state.rule.event, {**self._event_data(reading), "from": previous})
