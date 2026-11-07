"""Plays a recorded session through the same pipeline as live capture. See WP3 in REMAINING_WORK.md.

ReplayLoop takes CaptureLoop's place: frames go into the ring buffer with their recorded region and
overlay rectangles, so masking and readers run on them as they would live. Recorded events go onto
the bus, and recorded pointer and card messages go to the overlay.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from pydantic import ValidationError

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import EventBus, GameEvent, SettingsChanged
from brain.replay.format import (
    EVENTS,
    FRAMES,
    MESSAGES,
    EventRecord,
    FrameRecord,
    Manifest,
    MessageRecord,
    decode_frame,
    read_jsonl,
    read_manifest,
    replay_event,
)
from shared.protocol import BrainMessage, BrainMessageAdapter
from shared.protocol.messages import Settings

log = logging.getLogger(__name__)

# The brain doesn't regenerate these as it replays, so the overlay only behaves as it did if they
# are sent again. Subtitles, toasts, questions and settings come from the brain itself, so
# re-sending them would show them twice.
RESENT_MESSAGES = frozenset(
    {"pointer.fly", "pointer.hide", "card.show", "card.update", "card.close"}
)

# Ties at equal t: frames first, so an event about a frame finds it in the buffer.
_FRAME_ORDER, _EVENT_ORDER, _MESSAGE_ORDER = 0, 1, 2


class ReplayLink(Protocol):
    """What replay needs from the overlay link. OverlayLink fits it."""

    display_scale: float
    pinned_display_scale: float | None
    settings: Settings

    async def send(self, message: BrainMessage) -> None: ...


@dataclass(frozen=True)
class _Item:
    t: float
    order: int
    record: FrameRecord | EventRecord | MessageRecord
    # Only for frames: when the next frame is due, so a late frame can be dropped undecoded.
    next_frame_t: float | None = None


@dataclass(frozen=True)
class _Session:
    manifest: Manifest
    timeline: list[_Item]


def _load(session: Path) -> _Session:
    """Blocking disk reads, so it runs in a worker thread. Raises OSError or ValueError."""
    manifest = read_manifest(session)
    frames = sorted(read_jsonl(session / FRAMES, FrameRecord), key=lambda record: record.t)
    items = [
        _Item(record.t, _FRAME_ORDER, record, frames[i + 1].t if i + 1 < len(frames) else None)
        for i, record in enumerate(frames)
    ]
    items += [_Item(r.t, _EVENT_ORDER, r) for r in read_jsonl(session / EVENTS, EventRecord)]
    items += [_Item(r.t, _MESSAGE_ORDER, r) for r in read_jsonl(session / MESSAGES, MessageRecord)]
    # sort() is stable, so items of one kind at the same t keep their recorded order.
    items.sort(key=lambda item: (item.t, item.order))
    return _Session(manifest, items)


def _read_image(path: Path) -> np.ndarray:
    """Blocking, so it runs in a worker thread. Raises OSError or ValueError."""
    return decode_frame(path.read_bytes())


class ReplayLoop:
    """Stands in for CaptureLoop: same async run(), so app.py only swaps which it builds."""

    def __init__(
        self,
        session: Path,
        buffer: RingBuffer,
        bus: EventBus,
        link: ReplayLink,
        speed: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        suppressed_events: Callable[[], Collection[str]] = frozenset,
    ) -> None:
        """`suppressed_events` names game events that readers now cover, so the recorded ones are
        left out, the same way the live observer leaves them to readers."""
        # Written this way round so NaN is refused too.
        if not speed > 0:
            raise ValueError(f"Replay speed must be positive, not {speed}")
        self._session = session
        self._buffer = buffer
        self._bus = bus
        self._link = link
        self._speed = speed
        self._clock = clock
        self._sleep = sleep
        self._suppressed_events = suppressed_events
        self.finished = asyncio.Event()
        self._pushed = 0
        self._late = 0
        self._unreadable = 0
        self._published = 0
        self._sent = 0

    async def run(self) -> None:
        """Returns once the session has played, with `finished` set. A bad session is logged, not
        raised, so the overlay and voice keep working as they do when live capture fails."""
        try:
            session = await asyncio.to_thread(_load, self._session)
        except (OSError, ValueError) as exc:  # pydantic's ValidationError is a ValueError
            log.error("Can't replay %s (%s); continuing without frames", self._session, exc)
            self.finished.set()
            return

        self._apply_manifest(session.manifest)
        start = self._clock()
        for item in session.timeline:
            due = start + item.t / self._speed
            await self._sleep(max(0.0, due - self._clock()))
            try:
                await self._play(item, start)
            except Exception:
                # One bad item mustn't end the replay: the rest of the session is still worth it.
                log.exception("Replay skipped the item at t=%.2f s", item.t)

        log.info(
            "Replay finished: %d frames pushed, %d dropped to keep up, %d unreadable, "
            "%d events published, %d messages sent, in %.1f s",
            self._pushed,
            self._late,
            self._unreadable,
            self._published,
            self._sent,
            self._clock() - start,
        )
        self.finished.set()

    def _apply_manifest(self, manifest: Manifest) -> None:
        if not manifest.complete:
            log.warning("Replay session %s was never closed, maybe by a crash", self._session)
        log.info(
            "Replaying %s: %s, %.1f s at %gx speed",
            self._session,
            manifest.game,
            manifest.duration_s,
            self._speed,
        )
        # The recorded rects are DIPs at the recorded scale. The pin stops an overlay connecting
        # mid-replay from changing how they're masked.
        self._link.display_scale = manifest.display_scale
        self._link.pinned_display_scale = manifest.display_scale
        if manifest.settings is not None:
            # The director reads personality and hints from the link, so the replay talks as the
            # recording did.
            try:
                self._link.settings = Settings.model_validate(manifest.settings)
            except ValidationError:
                log.warning("Recorded settings don't fit; keeping the current ones")

    async def _play(self, item: _Item, start: float) -> None:
        match item.record:
            case FrameRecord():
                await self._push_frame(item.record, item.next_frame_t, start)
            case EventRecord():
                self._publish(item.record)
            case MessageRecord():
                await self._send(item.record)

    async def _push_frame(self, record: FrameRecord, next_t: float | None, start: float) -> None:
        # Falling behind is worse than dropping: decoding a frame that's already stale only
        # delays every item after it.
        if next_t is not None and self._clock() >= start + next_t / self._speed:
            self._late += 1
            return
        try:
            image = await asyncio.to_thread(_read_image, self._session / record.file)
        except (OSError, ValueError) as exc:
            if self._unreadable == 0:
                log.warning(
                    "Skipping unreadable frame %s (%s); later ones are only counted",
                    record.file,
                    exc,
                )
            self._unreadable += 1
            return
        region = record.region.to_region() if record.region else None
        self._buffer.push(Frame(self._clock(), image, tuple(record.overlay_rects), region))
        self._pushed += 1

    def _publish(self, record: EventRecord) -> None:
        event = replay_event(record)
        if event is None:
            return
        # Checked when due rather than up front, because readers can start covering a name mid-run.
        if isinstance(event, GameEvent) and event.name in self._suppressed_events():
            log.debug("Readers cover %s; skipped the recorded one", event.name)
            return
        if isinstance(event, SettingsChanged) and isinstance(event.settings, Settings):
            # Before publishing, so anything reacting to the event already sees the new settings.
            self._link.settings = event.settings
        self._bus.publish(event)
        self._published += 1

    async def _send(self, record: MessageRecord) -> None:
        kind = record.message.get("type")
        if kind not in RESENT_MESSAGES:
            return
        try:
            message = BrainMessageAdapter.validate_python(record.message)
        except ValidationError:
            log.warning("Skipping a recorded %s that doesn't fit: %.200s", kind, record.message)
            return
        await self._link.send(message)
        self._sent += 1
