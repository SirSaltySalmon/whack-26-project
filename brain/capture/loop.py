"""Moves frames from a source into the ring buffer at a fixed rate."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.capture.source import FrameSource
from brain.capture.window import crop_to_region
from brain.perception.coords import CropRegion
from shared.protocol.messages import Rect

log = logging.getLogger(__name__)


class HasRects(Protocol):
    @property
    def rects(self) -> tuple[Rect, ...]: ...


class VisibleRegion(Protocol):
    def visible_region(self) -> CropRegion | None: ...


class CaptureLoop:
    def __init__(
        self,
        source: FrameSource,
        buffer: RingBuffer,
        overlay: HasRects,
        fps: int,
        window: VisibleRegion | None = None,
    ) -> None:
        """Without a window, frames are kept whole. Only replay should do that: its frames were
        already cropped when recorded, whereas a live frame could show the whole desktop."""
        self._source = source
        self._buffer = buffer
        self._overlay = overlay
        self._window = window
        self._interval = 1.0 / fps
        self._failing = False
        # One dedicated thread: capture handles can be tied to the thread that created them.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture")

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._executor, self._source.start)
        except Exception:
            # The overlay and voice should keep working even when capture can't start.
            log.exception("Capture unavailable; continuing without frames")
            return

        log.info("Capture running at %.1f fps", 1.0 / self._interval)
        try:
            while True:
                started = time.monotonic()
                rects = self._overlay.rects
                frame = await loop.run_in_executor(self._executor, self._capture_safely, rects)
                if frame is not None:
                    # _capture already copied it on the capture thread.
                    self._buffer.push_owned(frame)
                elapsed = time.monotonic() - started
                await asyncio.sleep(max(0.0, self._interval - elapsed))
        finally:
            # Queued, not called here, so the source is released on the thread that owns it.
            self._executor.submit(self._source.stop)
            self._executor.shutdown(wait=False)

    def _capture_safely(self, rects: tuple[Rect, ...]) -> Frame | None:
        """A capture error, such as the display changing mode, must not take the brain down."""
        try:
            frame = self._capture(rects)
        except Exception:
            if not self._failing:
                log.exception("Capture failed; will keep retrying")
            self._failing = True
            return None
        if self._failing:
            log.info("Capture recovered")
        self._failing = False
        return frame

    def _capture(self, rects: tuple[Rect, ...]) -> Frame | None:
        started = time.monotonic()
        if self._window is None:
            image = self._source.grab()
            return None if image is None else Frame(started, image.copy(), rects)

        # Checked on both sides of the grab, so an alt-tab during it can't leak another app.
        region = self._window.visible_region()
        if region is None:
            return None
        image = self._source.grab()
        if image is None or self._window.visible_region() != region:
            return None
        cropped = crop_to_region(image, region)
        if cropped is None:
            return None
        # Copied here, on the capture thread: the crop is a view of a buffer the source may reuse.
        return Frame(started, cropped[0].copy(), rects, cropped[1])
