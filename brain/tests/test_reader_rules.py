"""Reader rules: confirmation, hysteresis, things that come and go, and noticing a broken reader."""

from typing import Any

from brain.perception.profile_schema import ReaderSpec
from brain.perception.reader_rules import MISSING_RESET_READS, ReaderState
from brain.perception.readers import Reading
from brain.tests.reader_fixtures import RED_RANGE


def state(*rules: dict[str, Any]) -> ReaderState:
    spec = ReaderSpec(
        name="health",
        region="health",
        type="color_fill",
        color=RED_RANGE,  # type: ignore[arg-type]
        rules=list(rules),  # type: ignore[arg-type]
    )
    return ReaderState(spec)


LOW = {"when": "below", "value": 0.25, "clear_at": 0.4, "event": "health_low"}
BOSS = {"when": "above", "value": 0.0, "clear_at": 0.0, "event": "boss_visible"}


def ok(value: float | str) -> Reading:
    return Reading("health", "ok", value, str(value))


def feed(reader: ReaderState, *readings: Reading) -> list[str]:
    fired: list[str] = []
    for index, reading in enumerate(readings):
        fired += [event.event for event in reader.update(reading, float(index), True)]
    return fired


def test_a_rule_needs_agreeing_reads_then_fires_once() -> None:
    assert feed(state(LOW), ok(0.2)) == []
    assert feed(state(LOW), ok(0.2), ok(0.2), ok(0.1), ok(0.1)) == ["health_low"]


def test_it_fires_again_only_after_passing_clear_at() -> None:
    reader = state(LOW)
    readings = [ok(0.2), ok(0.2), ok(0.3), ok(0.2), ok(0.2), ok(0.5), ok(0.2), ok(0.2)]
    assert feed(reader, *readings) == ["health_low", "health_low"]


def test_event_data_carries_value_display_and_percent() -> None:
    reader = state(LOW)
    reader.update(ok(0.2), 0.0, True)
    (event,) = reader.update(ok(0.2), 1.0, True)
    assert event.data == {"value": 0.2, "display": "0.2", "percent": 20}


def test_masked_and_unreadable_reads_fire_nothing() -> None:
    masked = Reading("health", "masked")
    unreadable = Reading("health", "unreadable")
    assert feed(state(LOW), ok(0.2), masked, unreadable, ok(0.2)) == []


def test_something_that_comes_and_goes_fires_again_after_it_has_gone() -> None:
    gone = [Reading("health", "unreadable")] * MISSING_RESET_READS
    fired = feed(state(BOSS), ok(0.9), ok(0.9), *gone, ok(0.8), ok(0.8))
    assert fired == ["boss_visible", "boss_visible"]


def test_a_changed_rule_fires_on_a_confirmed_new_value_only() -> None:
    reader = state({"when": "changed", "event": "objective_changed"})
    fired = feed(
        reader, ok("Find wood"), ok("Find wood"), ok("Fnd"), ok("Kill boss"), ok("Kill boss")
    )
    assert fired == ["objective_changed"]


def test_unreadable_in_gameplay_for_long_enough_is_failing() -> None:
    reader = state(LOW)
    reader.update(Reading("health", "unreadable"), 0.0, True)
    assert not reader.failing(30.0, 60.0)
    assert reader.failing(61.0, 60.0)
    reader.update(ok(0.9), 62.0, True)
    assert not reader.failing(200.0, 60.0)


def test_menus_and_masks_do_not_count_toward_failing() -> None:
    reader = state(LOW)
    reader.update(Reading("health", "unreadable"), 0.0, False)
    reader.update(Reading("health", "masked"), 50.0, True)
    assert not reader.failing(100.0, 60.0)


def test_something_that_comes_and_goes_never_counts_as_failing() -> None:
    reader = state(BOSS)
    reader.update(Reading("health", "unreadable"), 0.0, True)
    assert not reader.failing(1000.0, 60.0)
