"""Spots a screen that hasn't changed since the last report, so the observer can skip paying for
the same answer again: a menu, the inventory, or the player standing still.

Runs on the masked image, so the partner's own subtitles changing never counts as a change.
"""

import cv2
import numpy as np

# Small enough to ignore a torch flickering, big enough to see anything move or appear.
THUMB_SIZE = (32, 18)
# Mean change per thumbnail pixel, out of 255, below which two frames count as the same.
SAME_BELOW = 2.0
# The longest a still screen goes without a report. Under the tracker's 4 s gap, which would
# otherwise reset its streaks, and its 5 s staleness, which would tell the talker it can't see.
MAX_SKIP_S = 3.0


def thumbnail(image: np.ndarray) -> np.ndarray:
    """A tiny greyscale copy. Run in a worker thread with the rest of the frame preparation."""
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    small = cv2.resize(grey, THUMB_SIZE, interpolation=cv2.INTER_AREA)
    return small.astype(np.float32)


class StillFrames:
    """Remembers the last frame actually sent. Only a frame that was sent resets the clock, so a
    slow drift can't creep past one skip at a time."""

    def __init__(self, same_below: float = SAME_BELOW, max_skip_s: float = MAX_SKIP_S) -> None:
        self._same_below = same_below
        self._max_skip_s = max_skip_s
        self._last: np.ndarray | None = None
        self._last_ts = float("-inf")

    def should_skip(self, thumb: np.ndarray, ts: float) -> bool:
        """True when this frame looks like the last one sent, recently enough to rely on it.
        Otherwise records it as sent."""
        last = self._last
        if (
            last is not None
            and last.shape == thumb.shape
            and ts - self._last_ts < self._max_skip_s
            and float(np.abs(thumb - last).mean()) < self._same_below
        ):
            return True
        self._last, self._last_ts = thumb, ts
        return False

    def forget(self) -> None:
        self._last, self._last_ts = None, float("-inf")
