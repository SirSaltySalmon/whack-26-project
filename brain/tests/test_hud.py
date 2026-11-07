"""How readers join the observer: context order, and leaving covered events to the readers."""

import asyncio

import pytest

from brain import hud
from brain.events import EventBus, GameEvent
from brain.hud import live_state, send_debug_regions
from brain.perception.focus import Focus, FocusIntervals
from brain.perception.observer import Observer
from brain.perception.reader_engine import RegionView
from brain.perception.tracker import ObservationTracker
from brain.tests.fakes import FakeOverlay, drain, make_buffer
from brain.tests.test_observer import FakeVision, report
from shared.protocol.messages import DebugRegions, Rect


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


class FakeReaders:
    def __init__(self) -> None:
        self.views = [RegionView("health", Rect(x=1, y=2, width=3, height=4), "ok", "72%")]

    def debug_view(self) -> list[RegionView]:
        return self.views


async def test_the_debug_view_is_sent_and_cleared_when_readers_go_away(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hud, "DEBUG_INTERVAL_S", 0.01)
    overlay = FakeOverlay()
    readers = FakeReaders()
    task = asyncio.create_task(send_debug_regions(readers, overlay.send))  # type: ignore[arg-type]
    await asyncio.sleep(0.05)
    readers.views = []
    await asyncio.sleep(0.05)
    task.cancel()
    sent = [m for m in overlay.sent if isinstance(m, DebugRegions)]
    assert sent[0].regions[0].name == "health" and sent[0].regions[0].display == "72%"
    assert sent[-1].regions == []
    assert sum(1 for m in sent if not m.regions) == 1  # Cleared once, then quiet
