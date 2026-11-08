"""Asks the vision model about the newest frame on a timer, and publishes what gets confirmed.

The timer runs at the rate Focus sets. Danger boosts it here, by rule, with no extra model call.
While the player has blinded the partner it sends nothing, as if the game weren't in front.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Collection
from typing import Protocol

import cv2

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import EventBus, GameEvent
from brain.llm.base import LLMUnavailableError, VisionLLM
from brain.perception.closeup import encode_jpeg
from brain.perception.focus import Focus
from brain.perception.masking import mask_overlay
from brain.perception.observation import OBSERVATION_PROMPT, Observation
from brain.perception.tracker import ELEVATED, ObservationTracker

log = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 500
REPLY_TIMEOUT_S = 10.0
# A reply takes about 1.6-2.7 s, so at the fastest interval, 0.6 s, a few overlap. Past this, the
# model is falling behind and more requests would only pay for out-of-date answers.
MAX_IN_FLIGHT = 5
# An older frame means capture stopped, usually because the game isn't in front.
MAX_FRAME_AGE_S = 2.0
# What the talker hears instead of an out-of-date picture, so it says it can't see.
BLIND_STATE = {"screen": "not watching: the player turned the partner's vision off"}


def _always() -> bool:
    return True


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
        focus: Focus,
        max_edge_px: int,
        mask_padding_px: int,
        on_observation: Callable[[Observation, float], None] | None = None,
        *,
        suppressed_events: Callable[[], Collection[str]] = frozenset,
        # The player's vision setting, read live so blinding applies from the next tick.
        watching: Callable[[], bool] = _always,
    ) -> None:
        self._buffer = buffer
        self._overlay = overlay
        self._vision = vision
        self._bus = bus
        self._tracker = tracker
        self.focus = focus
        self._max_edge_px = max_edge_px
        self._padding_px = mask_padding_px
        self._on_observation = on_observation
        # Events the faster local readers already cover, so the observer doesn't repeat them.
        # Set after construction, because the readers are built later.
        self.suppressed_events = suppressed_events
        self._watching = watching
        self._was_watching = True
        self._tasks: set[asyncio.Task[None]] = set()
        self._last_sent_ts: float | None = None
        self._last_applied_ts: float | None = None
        self._unavailable = False

    def live_state(self) -> dict[str, str]:
        if not self._watching():
            return dict(BLIND_STATE)
        # Focus keeps its own clock, so tests can move it.
        return {**self._tracker.live_state(time.monotonic()), **self.focus.live_state()}

    async def run(self) -> None:
        intervals = self.focus.intervals
        log.info(
            "Observer reporting every %.1f s, faster on a boost (%.1f s, %.1f s)",
            intervals.low_s,
            intervals.medium_s,
            intervals.high_s,
        )
        last_tick = float("-inf")
        try:
            while True:
                now = time.monotonic()
                due = last_tick + self.focus.interval_s()
                if now >= due:
                    last_tick = now
                    self._tick(now)
                    continue
                # A boost mid-wait shortens the wait, rather than waiting out the slow interval.
                self.focus.changed.clear()
                try:
                    await asyncio.wait_for(self.focus.changed.wait(), due - now)
                except TimeoutError:
                    pass
        finally:
            for task in self._tasks:
                task.cancel()

    def _tick(self, now: float) -> None:
        watching = self._watching()
        if watching != self._was_watching:
            self._was_watching = watching
            log.info("Vision turned %s by the player", "on" if watching else "off")
        if not watching:
            return
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
        if not self._watching():
            # Sent before the player blinded the partner. Acting on it now would mean seeing.
            log.debug("Dropping an observation that arrived after vision was turned off")
            return
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
        changes = self._tracker.update(observation, frame_ts)
        suppressed = self.suppressed_events()
        for change in changes:
            if change.name in suppressed:
                log.debug("Left %s to the readers", change.name)
                continue
            log.info("Confirmed %s: %s", change.name, change.data)
            seen = change.since if change.since is not None else frame_ts
            self._bus.publish(GameEvent(change.name, change.data, frame_ts=seen))
        self._refocus(observation, [change.name for change in changes])

    def _refocus(self, observation: Observation, changes: list[str]) -> None:
        """Keeps watching closely while there's danger, then drops back once the hold runs out."""
        danger = self._tracker.danger
        if danger is not None:
            self.focus.boost("high" if danger == "high" else "medium", "fight")
        elif observation.danger_level in ELEVATED:
            # One frame isn't believed, but looking again sooner confirms or clears it faster.
            self.focus.boost("medium", "possible danger")
        if "health_low" in changes:
            self.focus.boost("high", "low health")
