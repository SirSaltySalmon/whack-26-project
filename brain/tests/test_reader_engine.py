"""The reader engine on synthetic frames: events, masking, staleness, size changes and reloads."""

import asyncio
from typing import Any

import numpy as np

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import EventBus, GameEvent, ProfileUpdated, ReadersFailing
from brain.memory.models import GameProfile
from brain.perception.coords import CropRegion
from brain.perception.ocr import OcrLine
from brain.perception.reader_engine import ReaderEngine
from brain.tests.fakes import FakeOverlay, drain
from brain.tests.reader_fixtures import health_frame_image, health_profile
from shared.protocol.messages import Rect


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeOcr:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def read(self, image: np.ndarray, detect: bool) -> list[OcrLine]:
        self.calls += 1
        return [(self.text, 0.99)]


class Rig:
    def __init__(self, data: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self.clock = Clock()
        self.buffer = RingBuffer(4)
        self.bus = EventBus()
        self.events = self.bus.subscribe()
        self.overlay = FakeOverlay()
        self.data = health_profile() if data is None else data
        self.loads = 0

        async def load() -> GameProfile:
            self.loads += 1
            return GameProfile(game="Some Game", data=self.data)

        self.engine = ReaderEngine(
            self.buffer, self.overlay, self.bus, load, 0, 0.2, 60.0, clock=self.clock, **kwargs
        )

    async def show(self, image: np.ndarray, rects: tuple[Rect, ...] = (), **frame: Any) -> None:
        """A new frame arrives and the engine ticks a reader interval later."""
        self.clock.now += 0.25
        self.buffer.push(Frame(self.clock.now, image, rects, frame.get("region")))
        await self.engine.tick()

    def published(self) -> list[Any]:
        return drain(self.events)


async def test_a_dropping_bar_raises_an_event_from_the_reader() -> None:
    rig = Rig()
    await rig.engine.reload()
    for fraction in (0.9, 0.2, 0.2):
        await rig.show(health_frame_image(fraction))
    (event,) = [e for e in rig.published() if isinstance(e, GameEvent)]
    assert event.name == "health_low" and event.source == "reader"
    assert event.data["percent"] == 20
    assert rig.engine.live_state() == {"health": "20%"}
    assert rig.engine.provides() == frozenset({"health_low"})


async def test_a_masked_bar_reads_nothing_and_hides_its_value() -> None:
    rig = Rig()
    await rig.engine.reload()
    await rig.show(health_frame_image(0.9))
    over_the_bar = (Rect(x=30, y=25, width=40, height=10),)
    for _ in range(3):
        # Masks are black, which would read as an empty bar if the engine looked.
        await rig.show(health_frame_image(0.0), over_the_bar)
    assert not [e for e in rig.published() if isinstance(e, GameEvent)]
    assert rig.engine.live_state() == {}
    assert rig.engine.debug_view()[0].status == "masked"


async def test_stale_frames_mean_no_values_and_no_reads() -> None:
    rig = Rig()
    await rig.engine.reload()
    await rig.show(health_frame_image(0.9))
    assert rig.engine.live_state() == {"health": "90%"}
    rig.clock.now += 5.0
    assert rig.engine.live_state() == {}


async def test_a_different_game_size_pauses_readers_and_asks_to_relearn() -> None:
    rig = Rig()
    await rig.engine.reload()
    await rig.show(health_frame_image(0.2, width=800, height=400))
    await rig.show(health_frame_image(0.2, width=800, height=400))
    published = rig.published()
    assert [type(e) for e in published] == [ReadersFailing]
    assert rig.engine.live_state() == {}


async def test_no_profile_means_the_engine_sits_idle() -> None:
    rig = Rig(data={})
    await rig.engine.reload()
    await rig.show(health_frame_image(0.1))
    assert rig.published() == [] and rig.engine.live_state() == {}


async def test_ocr_readers_run_in_the_worker_and_parse_the_result() -> None:
    ocr = FakeOcr("18/100")
    rig = Rig(health_profile(reader_type="ocr_fraction"), ocr=ocr)
    await rig.engine.reload()
    for _ in range(2):
        await rig.show(health_frame_image(0.5))
        assert rig.engine._ocr_task is not None
        await rig.engine._ocr_task
    (event,) = [e for e in rig.published() if isinstance(e, GameEvent)]
    assert event.name == "health_low" and event.data["display"] == "18/100"
    assert rig.engine.live_state() == {"health": "18/100 (18%)"}


async def test_profile_updates_reload_the_readers() -> None:
    rig = Rig(data={})
    task = asyncio.create_task(rig.engine.run())
    await asyncio.sleep(0.05)
    rig.data = health_profile()
    rig.bus.publish(ProfileUpdated("Some Game"))
    await asyncio.sleep(0.3)
    task.cancel()
    assert rig.loads == 2
    assert [p.spec.name for p in rig.engine.readers] == ["health"]


async def test_the_debug_view_places_boxes_in_overlay_coordinates() -> None:
    rig = Rig()
    rig.overlay.display_scale = 2.0
    await rig.engine.reload()
    await rig.show(health_frame_image(0.5), region=CropRegion(100, 40, 400, 200))
    (view,) = rig.engine.debug_view()
    assert (view.rect.x, view.rect.y, view.rect.width, view.rect.height) == (60, 30, 100, 10)
    assert (view.status, view.display) == ("ok", "50%")


async def test_a_reader_event_carries_the_frame_it_read_for_latency() -> None:
    rig = Rig()
    await rig.engine.reload()
    for fraction in (0.9, 0.2, 0.2):
        await rig.show(health_frame_image(fraction))
    (event,) = [e for e in rig.published() if isinstance(e, GameEvent)]
    latest = rig.buffer.latest()
    assert latest is not None and event.frame_ts == latest.ts
