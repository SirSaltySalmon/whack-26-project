"""Full-resolution frames from the last few seconds, held in RAM."""

import threading
from collections import deque
from dataclasses import dataclass, replace

import numpy as np

from brain.perception.coords import CropRegion
from shared.protocol.messages import Rect


@dataclass(frozen=True)
class Frame:
    ts: float
    image: np.ndarray
    # Overlay rectangles (DIPs) at capture time, so masking matches this exact frame.
    overlay_rects: tuple[Rect, ...] = ()
    # Where the image sits on screen, in physical pixels. None means it starts at the corner.
    region: CropRegion | None = None


class RingBuffer:
    """Thread-safe: the capture thread writes while the event loop reads."""

    def __init__(self, capacity: int) -> None:
        self._frames: deque[Frame] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def push(self, frame: Frame) -> None:
        # dxcam can hand out zero-copy views that later captures overwrite.
        self.push_owned(replace(frame, image=frame.image.copy()))

    def push_owned(self, frame: Frame) -> None:
        """For an image nothing else holds, already copied off the event loop: a full-frame copy
        here would block it for milliseconds at every frame."""
        with self._lock:
            self._frames.append(frame)

    def latest(self) -> Frame | None:
        with self._lock:
            return self._frames[-1] if self._frames else None

    def nearest(self, ts: float) -> Frame | None:
        with self._lock:
            return min(self._frames, key=lambda f: abs(f.ts - ts), default=None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)
