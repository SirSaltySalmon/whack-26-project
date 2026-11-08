"""WP9: latency measured from the frame that showed something, not from when it was published."""

import logging

import pytest

from brain.director.lines import play_bark
from brain.director.rules import PlayBark
from brain.events import EventBus, GameEvent
from brain.tests.reader_fixtures import health_frame_image
from brain.tests.test_observer import FakeVision, observer, report
from brain.tests.test_reader_engine import Rig
from brain.voice.barks import Bark

BARK = Bark(text="Careful.", pcm=b"\0\0", sample_rate=24000)


class AcceptingVoice:
    async def play(self, _bark: Bark) -> bool:
        return True


async def test_an_observer_event_carries_the_first_frame_that_showed_it() -> None:
    bus = EventBus()
    events = bus.subscribe()
    built, _ = observer(FakeVision(), bus)
    built._apply(report(), 1.0)
    built._apply(report(), 1.8)  # The second agreeing frame confirms it
    published = events.get_nowait()
    assert isinstance(published, GameEvent)
    # The frame from 1.0, not the confirming one, and not when the reply arrived.
    assert published.frame_ts == 1.0
    assert published.ts != published.frame_ts


async def test_a_reader_event_carries_the_frame_it_read() -> None:
    rig = Rig()
    await rig.engine.reload()
    for fraction in (0.9, 0.2, 0.2):
        await rig.show(health_frame_image(fraction))
    (event,) = [e for e in rig.published() if isinstance(e, GameEvent)]
    latest = rig.buffer.latest()
    assert latest is not None and event.frame_ts == latest.ts


async def test_a_bark_logs_noticing_and_speaking_separately(
    caplog: pytest.LogCaptureFixture,
) -> None:
    action = PlayBark("danger", "danger_started", {}, ts=100.0, frame_ts=99.3, source="observer")
    with caplog.at_level(logging.INFO, logger="brain.director.lines"):
        assert await play_bark(AcceptingVoice(), BARK, action)  # type: ignore[arg-type]
    lines = [r.getMessage() for r in caplog.records]
    assert any(line.startswith("Latency: event to bark") for line in lines)
    (frame_line,) = [line for line in lines if line.startswith("Latency: frame to bark")]
    assert "noticed in 700, spoke in" in frame_line and "observer, danger_started" in frame_line


async def test_an_event_without_a_frame_time_logs_only_the_old_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    action = PlayBark("danger", "danger_started", {}, ts=100.0)
    with caplog.at_level(logging.INFO, logger="brain.director.lines"):
        await play_bark(AcceptingVoice(), BARK, action)  # type: ignore[arg-type]
    lines = [r.getMessage() for r in caplog.records]
    assert any(line.startswith("Latency: event to bark") for line in lines)
    assert not any(line.startswith("Latency: frame to bark") for line in lines)


def test_frame_times_never_change_what_was_decided() -> None:
    assert GameEvent("x", ts=5.0, frame_ts=1.0) == GameEvent("x", ts=5.0, frame_ts=2.0)
    assert PlayBark("k", "e", {}, frame_ts=1.0, source="reader") == PlayBark("k", "e", {})
