"""How readers join the observer: context order, and leaving covered events to the readers."""

from brain.events import EventBus, GameEvent
from brain.hud import live_state
from brain.perception.focus import Focus, FocusIntervals
from brain.perception.observer import Observer
from brain.perception.tracker import ObservationTracker
from brain.tests.fakes import FakeOverlay, drain, make_buffer
from brain.tests.test_observer import FakeVision, report


def test_reader_values_go_after_mood_and_replace_the_observers() -> None:
    merged = live_state(
        {"player mood": "tense"},
        {"health": "20/100 (20%)"},
        {"danger": "high", "health": "about half (50%)", "seen": "a long description"},
    )
    assert list(merged) == ["player mood", "health", "danger", "seen"]
    assert merged["health"] == "20/100 (20%)"


def test_the_observer_leaves_events_the_readers_cover_but_still_boosts_focus() -> None:
    bus = EventBus()
    events = bus.subscribe()
    focus = Focus(FocusIntervals(1.3, 0.8, 0.6), 5.0)
    observer = Observer(
        make_buffer(), FakeOverlay(), FakeVision(), bus, ObservationTracker(), focus, 1280, 0
    )
    observer.suppressed_events = lambda: frozenset({"danger_started"})
    observer._apply(report("high"), 1.0)
    observer._apply(report("high"), 1.6)
    assert not [e for e in drain(events) if isinstance(e, GameEvent)]
    assert focus.level() == "high"
