"""A bar growing past its learned box, such as more hearts, is noticed and the HUD relearned."""

import time
from pathlib import Path

import numpy as np

from brain.events import ReadersFailing
from brain.perception.growth import GROWN_AFTER_S, GrowthWatch, beside, spill
from brain.perception.profile_schema import Box, ColorFillParams
from brain.tests.fakes import FakeVision, drain
from brain.tests.reader_fixtures import RED_RANGE, hearts, place
from brain.tests.test_learner import Rig as LearnerRig
from brain.tests.test_reader_engine import Rig as EngineRig

RED = ColorFillParams(**RED_RANGE)  # type: ignore[arg-type]
# health_profile's box: 200 x 20 pixels at (20, 20), which holds exactly 10 hearts of 20 pixels.
BOX = Box(x=20 / 400, y=20 / 200, w=200 / 400, h=20 / 200)


def heart_row(count: int) -> np.ndarray:
    canvas = np.full((200, 400, 3), 30, dtype=np.uint8)
    return place(canvas, hearts(count, total=count), 20, 22)


def test_the_strips_touch_each_side_and_are_as_deep_as_the_box_is_thin() -> None:
    assert beside((200, 400), BOX) == [
        (0, 20, 20, 40),
        (220, 20, 240, 40),
        (20, 0, 220, 20),
        (20, 40, 220, 60),
    ]


def test_strips_stop_at_the_edge_of_the_image() -> None:
    corner = Box(x=0.0, y=0.0, w=0.5, h=0.1)
    assert beside((200, 400), corner) == [(200, 0, 220, 20), (0, 20, 200, 40)]


def test_a_bar_that_fits_its_box_spills_nothing_and_one_more_heart_does() -> None:
    assert spill(heart_row(10), BOX, RED) == 0.0
    assert spill(heart_row(11), BOX, RED) > 0.5


def test_growth_is_reported_once_after_it_lasts() -> None:
    watch = GrowthWatch()
    assert not watch.update("health", 0.0, 0.0)
    assert not watch.update("health", 0.6, 1.0)
    assert not watch.update("health", 0.6, 1.0 + GROWN_AFTER_S - 0.1)
    assert watch.update("health", 0.6, 1.0 + GROWN_AFTER_S)
    assert not watch.update("health", 0.6, 10.0)


def test_a_moment_of_the_same_colour_beside_the_bar_is_not_growth() -> None:
    watch = GrowthWatch()
    watch.update("health", 0.0, 0.0)
    watch.update("health", 0.6, 1.0)
    watch.update("health", 0.0, 2.0)  # It passed by
    assert not watch.update("health", 0.6, 1.0 + GROWN_AFTER_S)


def test_a_box_learned_beside_its_own_colour_never_calls_for_relearning() -> None:
    # Relearning couldn't fix it, so it would only spend vision calls.
    watch = GrowthWatch()
    assert not any(watch.update("health", 0.6, float(t)) for t in range(20))


async def test_the_engine_asks_for_a_relearn_when_hearts_grow_past_the_box() -> None:
    rig = EngineRig()
    await rig.engine.reload()
    for _ in range(3):
        await rig.show(heart_row(10))
    assert not [e for e in rig.published() if isinstance(e, ReadersFailing)]
    before = rig.engine.live_state()
    for _ in range(int(GROWN_AFTER_S / 0.25) + 2):
        await rig.show(heart_row(13))
    failing = [e for e in rig.published() if isinstance(e, ReadersFailing)]
    # Compared without `ts`: Windows' coarse clock made two events built moments apart equal.
    assert [(e.game, e.readers, e.grown) for e in failing] == [("Some Game", ("health",), True)]
    # The reading doesn't change, since its own box is still full: that's why the growth had to be
    # noticed beside the box rather than in the reading.
    assert rig.engine.live_state() == before


async def test_a_grown_bar_is_relearned_sooner_than_failing_readers(tmp_path: Path) -> None:
    rig = LearnerRig(tmp_path, FakeVision({}))
    rig.learner._last_pass_at = time.monotonic() - 60  # A pass a minute ago
    rig.bus.publish(ReadersFailing("Some Game", ("health",)))
    assert await rig.learner.why_learn(rig.events) is None  # Failing waits the full gap
    rig.bus.publish(ReadersFailing("Some Game", ("health",), grown=True))
    assert await rig.learner.why_learn(rig.events) == "a bar grew past its box"
    drain(rig.events)
