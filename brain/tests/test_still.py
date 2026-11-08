import time

import numpy as np

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import EventBus
from brain.llm.base import SchemaT
from brain.perception.observer import Observer
from brain.perception.still import MAX_SKIP_S, StillFrames, thumbnail
from brain.perception.tracker import ObservationTracker
from brain.tests.test_observer import Overlay, focus, settle
from brain.tests.test_tracker import frame as calm_report

CANT_SEE = {"screen": "can't see the game right now"}


def grey(value: int) -> np.ndarray:
    return np.full((72, 128, 3), value, dtype=np.uint8)


def test_the_same_screen_is_skipped_until_it_has_been_too_long() -> None:
    still = StillFrames()
    assert not still.should_skip(thumbnail(grey(100)), 0.0)  # Nothing sent yet
    assert still.should_skip(thumbnail(grey(100)), 1.0)
    assert still.should_skip(thumbnail(grey(101)), 2.0)  # A flicker isn't a change
    assert not still.should_skip(thumbnail(grey(100)), MAX_SKIP_S + 0.1)


def test_a_changed_screen_is_sent_and_becomes_the_one_compared_with() -> None:
    still = StillFrames()
    still.should_skip(thumbnail(grey(100)), 0.0)
    assert not still.should_skip(thumbnail(grey(160)), 1.0)
    assert still.should_skip(thumbnail(grey(160)), 2.0)


def test_a_slow_drift_cannot_creep_past_one_skip_at_a_time() -> None:
    # Each step is under the threshold, but the comparison is always with the frame last sent.
    still = StillFrames()
    still.should_skip(thumbnail(grey(100)), 0.0)
    skipped = [still.should_skip(thumbnail(grey(100 + step)), step * 0.1) for step in range(1, 8)]
    assert not all(skipped)


def test_a_still_frame_keeps_the_last_report_fresh_without_confirming_anything() -> None:
    tracker = ObservationTracker()
    tracker.update(calm_report(), 0.0)
    tracker.still(4.0)
    assert tracker.live_state(8.0) != CANT_SEE
    assert tracker.live_state(9.5) == CANT_SEE


class CalmVision:
    def __init__(self) -> None:
        self.calls = 0

    async def vision_json(
        self, prompt: str, image: bytes, media_type: str, schema: type[SchemaT], max_tokens: int
    ) -> SchemaT:
        self.calls += 1
        return calm_report()  # type: ignore[return-value]


async def test_the_observer_pays_once_for_a_screen_that_does_not_change() -> None:
    vision = CalmVision()
    buffer = RingBuffer(5)
    watcher = Observer(
        buffer,
        Overlay(),
        vision,
        EventBus(),
        ObservationTracker(),
        focus(),
        1280,
        0,
        still=StillFrames(),
    )
    start = time.monotonic()
    for index in range(3):
        # Apart in time: Windows' clock ticks every ~15 ms, so back-to-back frames could share a
        # time and be taken for the same frame.
        ts = start + index * 0.1
        buffer.push(Frame(ts, np.full((720, 1280, 3), 200, dtype=np.uint8)))
        watcher._tick(ts)
        await settle(watcher)
    assert vision.calls == 1 and watcher.skipped == 2
    assert "danger" in watcher.live_state()


async def test_watching_closely_sends_every_frame_even_when_nothing_changes() -> None:
    vision = CalmVision()
    buffer = RingBuffer(5)
    closely = focus()
    closely.boost("high", "fight")
    watcher = Observer(
        buffer, Overlay(), vision, EventBus(), ObservationTracker(), closely, 1280, 0,
        still=StillFrames(),
    )  # fmt: skip
    start = time.monotonic()
    for index in range(3):
        # Apart in time: Windows' clock ticks every ~15 ms, so back-to-back frames could share a
        # time and be taken for the same frame.
        ts = start + index * 0.1
        buffer.push(Frame(ts, np.full((720, 1280, 3), 200, dtype=np.uint8)))
        watcher._tick(ts)
        await settle(watcher)
    assert vision.calls == 3 and watcher.skipped == 0
