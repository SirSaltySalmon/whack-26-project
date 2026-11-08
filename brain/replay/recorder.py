"""Records a live session to disk, for replay. See WP3 in docs/REMAINING_WORK.md.

Only runs with --record, because it stores screen and mic data. The event loop only queues work:
one writer thread does every encode and write, so recording can't slow capture or the loop.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, NoReturn

from pydantic import BaseModel

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import Event, EventBus, OverlayConnected
from brain.replay.format import (
    AUDIO,
    EVENTS,
    FRAMES,
    FRAMES_DIR,
    MESSAGES,
    FrameRecord,
    Manifest,
    MessageRecord,
    RegionRecord,
    encode_frame,
    event_record,
    frame_file,
    jsonl_line,
    partner_said_record,
    session_dir_name,
    write_manifest,
)
from brain.replay.writer import LineFiles, MessageLog, WavAppender, WriterThread, rounded
from shared.protocol import BrainMessage

log = logging.getLogger(__name__)

# MessageLog lives with the writer, and is re-exported so both recording parts import from here.
__all__ = ["MAX_QUEUED_FRAMES", "MessageLog", "SessionRecorder"]

# About 6 s of frames at 5 fps. Past this the oldest waiting frame is dropped, so a slow disk
# costs frames, never capture speed or memory.
MAX_QUEUED_FRAMES = 32


class SessionRecorder:
    """Saves new ring buffer frames, its own bus subscription and three hooks to a session folder.

    The hooks are cheap and never raise: they queue the work and return, even before run() starts.
    """

    def __init__(
        self,
        root: Path,
        game: str,
        buffer: RingBuffer,
        bus: EventBus,
        display_scale: Callable[[], float],
        record_fps: int,
        max_gb: float,
        settings: Callable[[], BaseModel] | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        if record_fps <= 0:
            raise ValueError(f"record_fps must be positive, not {record_fps}")
        self._root = root
        self._game = game
        self._buffer = buffer
        self._display_scale = display_scale
        self._record_fps = record_fps
        self._max_bytes = max_gb * 1e9
        self._settings = settings
        self._clock = clock
        self._now = now
        self._t0 = clock()
        # Subscribed now, so events published before run() starts are kept.
        self._events = bus.subscribe()
        self._writer = WriterThread("Recorder", MAX_QUEUED_FRAMES)
        self._files = LineFiles()
        self._audio: WavAppender | None = None
        self._manifest: Manifest | None = None
        self._last_ts = float("-inf")
        self._disabled = False
        # Written only by the writer thread, and read by the loop once it has joined.
        self._saved = 0
        self._frame_bytes = 0
        self._capped = False
        self.session_dir: Path | None = None

    def on_partner_said(self, text: str) -> None:
        try:
            if self.session_dir is not None:
                # Bus events still waiting go first, so events.jsonl stays in time order.
                self._drain_events()
            self._queue_line(EVENTS, partner_said_record(text, self._since_start()))
        except Exception:
            log.exception("Could not record a partner line")

    def on_message(self, message: BrainMessage) -> None:
        try:
            record = MessageRecord(t=self._since_start(), message=message.model_dump(mode="json"))
            self._queue_line(MESSAGES, record)
        except Exception:
            log.exception("Could not record a %s message", type(message).__name__)

    def on_mic_audio(self, pcm: bytes) -> None:
        if not self._disabled and pcm:
            self._writer.submit("write audio", partial(self._append_audio, pcm))

    async def run(self) -> None:
        """Runs until cancelled, then finishes the session, so even a cancelled run is complete."""
        try:
            self.session_dir = await self._start()
        except Exception:
            log.exception("Could not start recording under %s; carrying on without it", self._root)
            await self._discard_events()
        self._writer.start()
        log.info("Recording to %s at %d fps", self.session_dir, self._record_fps)
        try:
            while True:
                self._poll()
                await asyncio.sleep(1.0 / self._record_fps)
        finally:
            await self._finish()

    async def _start(self) -> Path:
        now = self._now()
        settings = self._settings() if self._settings else None
        manifest = Manifest(
            game=self._game,
            created_at=now.replace(microsecond=0).isoformat(),
            display_scale=self._display_scale(),
            record_fps=self._record_fps,
            settings=settings.model_dump(mode="json") if settings is not None else None,
        )
        base = self._root / session_dir_name(self._game, now)
        directory = await asyncio.to_thread(_create_session, base, manifest)
        self._manifest = manifest
        self._audio = WavAppender(directory / AUDIO, manifest.audio_sample_rate)
        return directory

    async def _discard_events(self) -> NoReturn:
        """The bus can't unsubscribe, so the queue is kept empty rather than left to warn about
        every event it drops."""
        self._disabled = True
        while True:
            await self._events.get()

    def _poll(self) -> None:
        frame = self._buffer.latest()
        if frame is not None and frame.ts > self._last_ts:
            self._last_ts = frame.ts
            if frame.ts >= self._t0 and not self._capped:
                kept = self._writer.submit_frame(partial(self._save_frame, frame))
                if not kept and self._writer.dropped == 1:
                    log.warning("Recording can't keep up; dropping the oldest waiting frames")
        self._drain_events()

    def _drain_events(self) -> None:
        while True:
            try:
                event = self._events.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                self._record_event(event)
            except Exception:
                log.exception("Could not record a %s event", type(event).__name__)

    def _record_event(self, event: Event) -> None:
        if isinstance(event, OverlayConnected):
            # Rewritten now, so a session from a crash still has the scale its rects were sent at.
            self._update_manifest(display_scale=event.display_scale)
            return
        record = event_record(event, rounded(event.ts - self._t0))
        if record is not None:
            self._queue_line(EVENTS, record)

    async def _finish(self) -> None:
        self._drain_events()
        duration = self._since_start()
        manifest = self._require_manifest().model_copy(
            update={
                "complete": True,
                "duration_s": duration,
                "dropped_frames": self._writer.dropped,
                "display_scale": self._display_scale(),
            }
        )
        if not await self._writer.stop(partial(self._close_session, manifest)):
            return
        megabytes = self._frame_bytes / 1e6
        log.info(
            "Recorded %s: %d frames, %.1f MB in %.1f s (%.2f MB/s), %d dropped",
            self.session_dir,
            self._saved,
            megabytes,
            duration,
            megabytes / duration if duration > 0 else 0.0,
            self._writer.dropped,
        )

    def _queue_line(self, name: str, record: BaseModel) -> None:
        if not self._disabled:
            self._writer.submit(f"write {name}", partial(self._append_line, name, record))

    def _update_manifest(self, **changes: Any) -> None:
        self._manifest = self._require_manifest().model_copy(update=changes)
        job = partial(write_manifest, self._dir(), self._manifest)
        self._writer.submit("rewrite the manifest", job)

    def _since_start(self) -> float:
        return rounded(self._clock() - self._t0)

    def _require_manifest(self) -> Manifest:
        if self._manifest is None:
            raise RuntimeError("The recorder hasn't started")
        return self._manifest

    def _dir(self) -> Path:
        if self.session_dir is None:
            raise RuntimeError("The recorder hasn't started")
        return self.session_dir

    def _path(self, name: str) -> Path:
        return self._dir() / name

    # --- Writer thread only ---

    def _append_line(self, name: str, record: BaseModel) -> None:
        self._files.append(self._path(name), jsonl_line(record))

    def _append_audio(self, pcm: bytes) -> None:
        if self._audio is not None:
            self._audio.append(pcm)

    def _save_frame(self, frame: Frame) -> None:
        if self._capped:
            return
        data = encode_frame(frame.image, self._require_manifest().jpeg_quality)
        seq = self._saved + 1
        name = frame_file(seq)
        self._path(name).write_bytes(data)
        record = FrameRecord(
            seq=seq,
            t=rounded(frame.ts - self._t0),
            file=name,
            region=RegionRecord.of(frame.region),
            overlay_rects=list(frame.overlay_rects),
        )
        self._append_line(FRAMES, record)
        self._saved = seq
        self._frame_bytes += len(data)
        if self._frame_bytes > self._max_bytes:
            self._capped = True
            log.warning(
                "Recording passed its %.2f GB limit, so it stopped saving frames. Events and "
                "messages are still saved",
                self._max_bytes / 1e9,
            )

    def _close_session(self, manifest: Manifest) -> None:
        has_audio = self._audio is not None and self._audio.opened
        try:
            self._files.close()
            if self._audio is not None:
                self._audio.close()
        finally:
            write_manifest(self._dir(), manifest.model_copy(update={"has_audio": has_audio}))


def _create_session(base: Path, manifest: Manifest) -> Path:
    """Adds -2, -3... to the name if a session started in the same second."""
    base.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 100):
        directory = base if attempt == 1 else base.parent / f"{base.name}-{attempt}"
        try:
            directory.mkdir()
        except FileExistsError:
            continue
        (directory / FRAMES_DIR).mkdir()
        write_manifest(directory, manifest)
        return directory
    raise FileExistsError(f"Too many sessions named {base.name}")
