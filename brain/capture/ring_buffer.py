"""Full-resolution frames from the last few seconds, held in RAM."""

import threading
from collections import deque
from dataclasses import dataclass

import numpy as np

from shared.protocol.messages import Rect


@dataclass(frozen=True)
class Frame:
    ts: float
    image: np.ndarray
    # Overlay rectangles (DIPs) at capture time, so masking matches this exact frame.
    overlay_rects: tuple[Rect, ...] = ()


class RingBuffer:
    """Thread-safe: the capture thread writes while the event loop reads."""

    def __init__(self, capacity: int) -> None:
        self._frames: deque[Frame] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def push(self, frame: Frame) -> None:
        # dxcam can hand out zero-copy views that later captures overwrite.
        owned = Frame(frame.ts, frame.image.copy(), frame.overlay_rects)
        with self._lock:
            self._frames.append(owned)

    def latest(self) -> Frame | None:
        with self._lock:
            return self._frames[-1] if self._frames else None

    def nearest(self, ts: float) -> Frame | None:
        with self._lock:
            return min(self._frames, key=lambda f: abs(f.ts - ts), default=None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)
