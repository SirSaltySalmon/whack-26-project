"""Runs the learned readers on the newest frame, a few times a second, with no model calls.

Colour readers take about a millisecond and run every tick in a worker thread. OCR readers go to
their own single thread and are skipped while it's busy, so a slow read can't delay the colour
readers or build a queue. With no learned profile the engine sits idle, which is normal before the
learner has run.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import numpy as np

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import Event, EventBus, GameEvent, ProfileUpdated, ReadersFailing
from brain.memory.models import GameProfile
from brain.perception.coords import fraction_box_to_dip_rect
from brain.perception.masking import box_is_masked
from brain.perception.observer import OverlayScale
from brain.perception.ocr import OcrWorker
from brain.perception.profile_schema import LearnedFor
from brain.perception.reader_rules import ReaderState
from brain.perception.readers import (
    FRACTION_TYPES,
    ColorFillReader,
    OcrReader,
    PlacedReader,
    Reading,
    Status,
    compile_profile,
    crop_box,
    learned_size,
)
from shared.protocol.messages import Rect

log = logging.getLogger(__name__)

# An older frame means capture stopped, usually because the game isn't in front.
MAX_FRAME_AGE_S = 2.0
# A reader read this recently is trusted to cover its events, so the observer can leave them.
PROVIDES_FRESH_S = 5.0


@dataclass(frozen=True)
class RegionView:
    """Where a reader looks and what it last read, for drawing it over the game."""

    name: str
    rect: Rect  # Overlay DIPs
    status: Status
    display: str | None


def _read_colours(image: np.ndarray, readers: list[PlacedReader]) -> list[Reading]:
    return [
        placed.reader.read(crop_box(image, placed.box))
        for placed in readers
        if isinstance(placed.reader, ColorFillReader)
    ]


class ReaderEngine:
    def __init__(
        self,
        buffer: RingBuffer,
        overlay: OverlayScale,
        bus: EventBus,
        load_profile: Callable[[], Awaitable[GameProfile]],
        padding_px: int,
        tick_s: float,
        failing_after_s: float,
        *,
        ocr: OcrWorker | None = None,
        in_gameplay: Callable[[], bool] = lambda: True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._buffer = buffer
        self._overlay = overlay
        self._bus = bus
        self._load_profile = load_profile
        self._padding = padding_px
        self._tick_s = tick_s
        self._failing_after_s = failing_after_s
        self._ocr = ocr
        self._in_gameplay = in_gameplay
        self._clock = clock

        self._game = ""
        self._placed: list[PlacedReader] = []
        self._states: dict[str, ReaderState] = {}
        self._next_due: dict[str, float] = {}
        self._learned: LearnedFor | None = None
        self._last_frame: Frame | None = None
        self._wrong_size_reported = False
        self._failing_reported: frozenset[str] = frozenset()
        self._ocr_task: asyncio.Task[None] | None = None

    @property
    def readers(self) -> list[PlacedReader]:
        return list(self._placed)

    async def reload(self) -> None:
        profile = await self._load_profile()
        self._game = profile.game
        self._placed = compile_profile(profile.data)
        self._learned = learned_size(profile.data)
        self._states = {placed.spec.name: ReaderState(placed.spec) for placed in self._placed}
        self._next_due = {}
        self._wrong_size_reported = False
        self._failing_reported = frozenset()
        if self._placed:
            log.info("Readers loaded: %s", ", ".join(self._states))

    async def run(self) -> None:
        events = self._bus.subscribe()
        await self._reload_safely()
        try:
            while True:
                if self._profile_updated(events):
                    await self._reload_safely()
                await self.tick()
                await asyncio.sleep(self._tick_s)
        finally:
            if self._ocr_task is not None:
                self._ocr_task.cancel()

    async def tick(self) -> None:
        if not self._placed:
            return
        frame = self._buffer.latest()
        now = self._clock()
        if frame is None or now - frame.ts > MAX_FRAME_AGE_S:
            return
        if self._last_frame is not None and frame.ts == self._last_frame.ts:
            return
        if self._wrong_size(frame):
            return
        self._last_frame = frame
        started = time.perf_counter()

        colour: list[PlacedReader] = []
        ocr: list[PlacedReader] = []
        scale = self._overlay.display_scale
        for placed in self._placed:
            name = placed.spec.name
            if now < self._next_due.get(name, 0.0):
                continue
            self._next_due[name] = now + placed.spec.interval_s
            if box_is_masked(placed.box, frame, scale, self._padding):
                # Masks are black, which would read as an empty bar.
                self._apply(Reading(name, "masked"), now)
            elif placed.reader.uses_ocr:
                ocr.append(placed)
            else:
                colour.append(placed)

        if colour:
            for reading in await asyncio.to_thread(_read_colours, frame.image, colour):
                self._apply(reading, now)
        ocr_idle = self._ocr_task is None or self._ocr_task.done()
        if ocr and self._ocr is not None and ocr_idle:
            self._ocr_task = asyncio.create_task(self._read_ocr(self._ocr, frame.image, ocr))
        self._check_failing(now)
        log.debug("Reader tick: %.1f ms", (time.perf_counter() - started) * 1000)

    def live_state(self) -> dict[str, str]:
        """Only values read in a recent frame. Masked and unreadable readers stay out."""
        frame = self._last_frame
        if frame is None or self._clock() - frame.ts > MAX_FRAME_AGE_S:
            return {}
        state: dict[str, str] = {}
        for placed in self._placed:
            reading = self._states[placed.spec.name].last
            if reading is None or reading.status != "ok" or not reading.display:
                continue
            text = reading.display
            if isinstance(reading.value, float) and placed.spec.type in FRACTION_TYPES:
                if "/" in text:
                    text = f"{text} ({round(reading.value * 100)}%)"
            state[placed.spec.live_key or placed.spec.name] = text
        return state

    def provides(self) -> frozenset[str]:
        """Event names working readers cover, so the observer can leave them to the faster path."""
        now = self._clock()
        events: set[str] = set()
        for placed in self._placed:
            last_ok = self._states[placed.spec.name].last_ok_at
            if last_ok is not None and now - last_ok <= PROVIDES_FRESH_S:
                events.update(rule.event for rule in placed.spec.rules)
        return frozenset(events)

    def debug_view(self) -> list[RegionView]:
        frame = self._last_frame
        if frame is None:
            return []
        height, width = frame.image.shape[:2]
        scale = self._overlay.display_scale
        views = []
        for placed in self._placed:
            reading = self._states[placed.spec.name].last
            rect = fraction_box_to_dip_rect(placed.box, width, height, frame.region, scale)
            status: Status = reading.status if reading else "unreadable"
            display = reading.display if reading and reading.status == "ok" else None
            views.append(RegionView(placed.spec.name, rect, status, display))
        return views

    async def _reload_safely(self) -> None:
        try:
            await self.reload()
        except Exception:
            # Without readers the observer still covers everything, just more slowly.
            log.exception("Couldn't load the learned readers")

    def _profile_updated(self, events: asyncio.Queue[Event]) -> bool:
        updated = False
        while not events.empty():
            event = events.get_nowait()
            if isinstance(event, ProfileUpdated) and event.game == self._game:
                updated = True
        return updated

    def _wrong_size(self, frame: Frame) -> bool:
        """Regions are fractions, but many games pin their HUD in pixels, so a resize moves it."""
        if self._learned is None:
            return False
        height, width = frame.image.shape[:2]
        if (width, height) == (self._learned.width, self._learned.height):
            self._wrong_size_reported = False
            return False
        if not self._wrong_size_reported:
            self._wrong_size_reported = True
            log.warning(
                "Readers paused: the game is %dx%d but they were learned at %dx%d",
                width,
                height,
                self._learned.width,
                self._learned.height,
            )
            self._bus.publish(ReadersFailing(self._game, tuple(self._states)))
        return True

    async def _read_ocr(
        self, ocr: OcrWorker, image: np.ndarray, readers: list[PlacedReader]
    ) -> None:
        for placed in readers:
            reader = placed.reader
            if not isinstance(reader, OcrReader):
                continue
            try:
                lines = await ocr.read(reader.prepare(crop_box(image, placed.box)), reader.detect)
            except Exception:
                log.exception("OCR failed for reader %s", placed.spec.name)
                continue
            self._apply(reader.parse(lines), self._clock())

    def _apply(self, reading: Reading, now: float) -> None:
        state = self._states.get(reading.reader)
        if state is None:
            return  # The profile was reloaded while this was being read
        for fired in state.update(reading, now, self._in_gameplay()):
            log.info("Reader %s: %s %s", reading.reader, fired.event, reading.display)
            self._bus.publish(GameEvent(fired.event, fired.data, source="reader"))

    def _check_failing(self, now: float) -> None:
        after_s = self._failing_after_s
        failing = frozenset(
            name for name, state in self._states.items() if state.failing(now, after_s)
        )
        if failing - self._failing_reported:
            log.warning("Readers keep failing: %s", ", ".join(sorted(failing)))
            self._bus.publish(ReadersFailing(self._game, tuple(sorted(failing))))
        self._failing_reported = failing
