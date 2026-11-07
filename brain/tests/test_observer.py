import asyncio
import time

import cv2
import numpy as np

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import EventBus, GameEvent
from brain.llm.base import LLMUnavailableError, SchemaT
from brain.perception.coords import CropRegion
from brain.perception.observation import Observation
from brain.perception.observer import MAX_FRAME_AGE_S, MAX_IN_FLIGHT, Observer, prepare_image
from brain.perception.tracker import ObservationTracker
from shared.protocol.messages import Rect


def report(level: str = "medium") -> Observation:
    return Observation(
        screen_type="gameplay",
        summary="A fight.",
        player_action=None,
        health_visible=False,
        health_raw=None,
        health_percent=None,
        danger_level=level,  # type: ignore[arg-type]
        threats=["Skeleton"],
        selected_item=None,
        menu_title=None,
        location=None,
        on_screen_text=[],
        notable=None,
        unsure=[],
    )


class FakeVision:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def vision_json(
        self, prompt: str, image: bytes, media_type: str, schema: type[SchemaT], max_tokens: int
    ) -> SchemaT:
        self.calls += 1
        if self.error:
            raise self.error
        assert media_type == "image/jpeg" and image
        return report()  # type: ignore[return-value]


class Overlay:
    display_scale = 1.0


def make_frame(ts: float | None = None) -> Frame:
    now = time.monotonic() if ts is None else ts
    return Frame(now, np.full((720, 1280, 3), 200, dtype=np.uint8))


def observer(vision: FakeVision, bus: EventBus | None = None) -> tuple[Observer, RingBuffer]:
    buffer = RingBuffer(5)
    built = Observer(
        buffer, Overlay(), vision, bus or EventBus(), ObservationTracker(), 0.8, 1280, 0
    )
    return built, buffer


async def settle(built: Observer) -> None:
    await asyncio.gather(*built._tasks)


def test_prepare_shrinks_and_masks_where_the_overlay_really_is() -> None:
    frame = Frame(
        0.0,
        np.full((1000, 2000, 3), 255, dtype=np.uint8),
        (Rect(x=110, y=60, width=40, height=40),),
        CropRegion(100, 50, 2000, 1000),
    )
    decoded = cv2.imdecode(
        np.frombuffer(prepare_image(frame, 1.0, 0, 1000), dtype=np.uint8), cv2.IMREAD_COLOR
    )
    assert decoded.shape[:2] == (500, 1000)
    assert decoded[15, 15].max() < 40  # Inside the overlay's area, at half scale.
    assert decoded[200, 200].min() > 200


async def test_each_frame_is_only_sent_once() -> None:
    vision = FakeVision()
    built, buffer = observer(vision)
    buffer.push(make_frame())
    built._tick(time.monotonic())
    built._tick(time.monotonic())
    await settle(built)
    assert vision.calls == 1


async def test_old_frames_mean_the_game_is_not_in_front_so_nothing_is_sent() -> None:
    vision = FakeVision()
    built, buffer = observer(vision)
    buffer.push(make_frame(time.monotonic() - MAX_FRAME_AGE_S - 1))
    built._tick(time.monotonic())
    await settle(built)
    assert vision.calls == 0


async def test_requests_are_capped_when_the_model_falls_behind() -> None:
    vision = FakeVision()
    built, buffer = observer(vision)
    for _ in range(MAX_IN_FLIGHT + 2):
        buffer.push(make_frame())
        built._tick(time.monotonic())
        await asyncio.sleep(0)
    assert len(built._tasks) <= MAX_IN_FLIGHT
    await settle(built)


async def test_confirmed_changes_reach_the_bus() -> None:
    bus = EventBus()
    events = bus.subscribe()
    built, _ = observer(FakeVision(), bus)
    built._apply(report(), 1.0)
    assert events.empty()
    built._apply(report(), 1.8)
    published = events.get_nowait()
    assert isinstance(published, GameEvent) and published.name == "danger_started"


async def test_late_replies_are_dropped() -> None:
    seen: list[float] = []
    built = Observer(
        RingBuffer(1),
        Overlay(),
        FakeVision(),
        EventBus(),
        ObservationTracker(),
        0.8,
        1280,
        0,
        on_observation=lambda _, ts: seen.append(ts),
    )
    built._apply(report(), 2.0)
    built._apply(report(), 1.0)
    assert seen == [2.0]


async def test_vision_failures_do_not_escape() -> None:
    for error in (LLMUnavailableError("over quota"), RuntimeError("boom")):
        built, buffer = observer(FakeVision(error))
        buffer.push(make_frame())
        built._tick(time.monotonic())
        await settle(built)
        assert built.live_state() == {"screen": "can't see the game right now"}
