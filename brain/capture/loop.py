"""Moves frames from a source into the ring buffer at a fixed rate."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.capture.source import FrameSource
from shared.protocol.messages import Rect

log = logging.getLogger(__name__)


class HasRects(Protocol):
    @property
    def rects(self) -> tuple[Rect, ...]: ...


class CaptureLoop:
    def __init__(
        self, source: FrameSource, buffer: RingBuffer, overlay: HasRects, fps: int
    ) -> None:
        self._source = source
        self._buffer = buffer
        self._overlay = overlay
        self._interval = 1.0 / fps
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
                image = await loop.run_in_executor(self._executor, self._source.grab)
                if image is not None:
                    self._buffer.push(Frame(started, image, self._overlay.rects))
                elapsed = time.monotonic() - started
                await asyncio.sleep(max(0.0, self._interval - elapsed))
        finally:
            self._source.stop()
            self._executor.shutdown(wait=False)
