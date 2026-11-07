"""Asks the vision model about the newest frame on a timer, and publishes what gets confirmed."""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Protocol

import cv2

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import EventBus, GameEvent
from brain.llm.base import LLMUnavailableError, VisionLLM
from brain.perception.closeup import encode_jpeg
from brain.perception.masking import mask_overlay
from brain.perception.observation import OBSERVATION_PROMPT, Observation
from brain.perception.tracker import ObservationTracker

log = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 500
REPLY_TIMEOUT_S = 10.0
# A reply takes about 1.6 s, so at 0.8 s intervals a few overlap. Past this, the model is falling
# behind and more requests would only pay for out-of-date answers.
MAX_IN_FLIGHT = 4
# An older frame means capture stopped, usually because the game isn't in front.
MAX_FRAME_AGE_S = 2.0


class OverlayScale(Protocol):
    @property
    def display_scale(self) -> float: ...


def prepare_image(frame: Frame, display_scale: float, padding_px: int, max_edge_px: int) -> bytes:
    """Hides the overlay so the model can't read its own subtitles, then shrinks and encodes."""
    masked = mask_overlay(frame.image, frame.overlay_rects, display_scale, padding_px, frame.region)
    height, width = masked.shape[:2]
    scale = min(1.0, max_edge_px / max(height, width))
    if scale < 1.0:
        masked = cv2.resize(masked, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return encode_jpeg(masked)


class Observer:
    def __init__(
        self,
        buffer: RingBuffer,
        overlay: OverlayScale,
        vision: VisionLLM,
        bus: EventBus,
        tracker: ObservationTracker,
        interval_s: float,
        max_edge_px: int,
        mask_padding_px: int,
        on_observation: Callable[[Observation, float], None] | None = None,
    ) -> None:
        self._buffer = buffer
        self._overlay = overlay
        self._vision = vision
        self._bus = bus
        self._tracker = tracker
        self._interval_s = interval_s
        self._max_edge_px = max_edge_px
        self._padding_px = mask_padding_px
        self._on_observation = on_observation
        self._tasks: set[asyncio.Task[None]] = set()
        self._last_sent_ts: float | None = None
        self._last_applied_ts: float | None = None
        self._unavailable = False

    def live_state(self) -> dict[str, str]:
        return self._tracker.live_state(time.monotonic())

    async def run(self) -> None:
        log.info("Observer reporting on a frame every %.1f s", self._interval_s)
        try:
            while True:
                started = time.monotonic()
                self._tick(started)
                await asyncio.sleep(max(0.0, self._interval_s - (time.monotonic() - started)))
        finally:
            for task in self._tasks:
                task.cancel()

    def _tick(self, now: float) -> None:
        frame = self._buffer.latest()
        if frame is None or frame.ts == self._last_sent_ts or now - frame.ts > MAX_FRAME_AGE_S:
            return
        if len(self._tasks) >= MAX_IN_FLIGHT:
            log.debug("Skipping a frame: %d requests already in flight", len(self._tasks))
            return
        self._last_sent_ts = frame.ts
        task = asyncio.create_task(self._observe(frame))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _observe(self, frame: Frame) -> None:
        started = time.monotonic()
        try:
            image = await asyncio.to_thread(
                prepare_image,
                frame,
                self._overlay.display_scale,
                self._padding_px,
                self._max_edge_px,
            )
            observation = await asyncio.wait_for(
                self._vision.vision_json(
                    OBSERVATION_PROMPT, image, "image/jpeg", Observation, MAX_OUTPUT_TOKENS
                ),
                REPLY_TIMEOUT_S,
            )
        except LLMUnavailableError as exc:
            # This repeats every frame while it lasts, so it's only worth logging once.
            if not self._unavailable:
                log.warning("Observer paused: %s", exc)
            self._unavailable = True
            return
        except Exception:
            # One bad frame must not stop the partner from watching the next one.
            log.exception("Observer failed on a frame")
            return
        if self._unavailable:
            log.info("Observer resumed")
        self._unavailable = False
        log.debug("Observation in %.2f s", time.monotonic() - started)
        self._apply(observation, frame.ts)

    def _apply(self, observation: Observation, frame_ts: float) -> None:
        # Replies can overlap and arrive out of order. The tracker compares consecutive frames, so
        # a late reply would make it compare the wrong ones.
        if self._last_applied_ts is not None and frame_ts <= self._last_applied_ts:
            log.debug("Dropping an out-of-order observation")
            return
        self._last_applied_ts = frame_ts
        if self._on_observation:
            self._on_observation(observation, frame_ts)
        for change in self._tracker.update(observation, frame_ts):
            log.info("Confirmed %s: %s", change.name, change.data)
            self._bus.publish(GameEvent(change.name, change.data))
