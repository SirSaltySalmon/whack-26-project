"""Notices a bar that has grown past its learned box, such as a row of hearts gaining a heart.

A colour reader only looks inside its box, so a bar that grows keeps reading full while the new
part drains: with twice the hearts, half the health could go before the reader saw any loss, and
a low-health warning would come far too late. The bar's colour turning up just outside the box,
and staying there, means the box is out of date and the HUD should be learned again.
"""

from collections.abc import Sequence

import numpy as np

from brain.perception.profile_schema import Box, ColorFillParams
from brain.perception.readers import colour_share

# A strip beside the box counts as filled when the bar's colour covers this much of it. A new icon
# or a stretch of bar covers far more of its strip; a stray pixel of the same hue far less.
SPILL_SHARE = 0.15
# Spilling this long without a break, so something of the same colour passing by doesn't count.
GROWN_AFTER_S = 3.0

Strip = tuple[int, int, int, int]  # x_min, y_min, x_max, y_max in pixels


def beside(shape: Sequence[int], box: Box) -> list[Strip]:
    """A strip touching each side of the box, as deep as the box is thin: one more icon's room."""
    height, width = shape[0], shape[1]
    left, top = box.x * width, box.y * height
    right, bottom = left + box.w * width, top + box.h * height
    deep = min(right - left, bottom - top)
    strips = [
        (left - deep, top, left, bottom),
        (right, top, right + deep, bottom),
        (left, top - deep, right, top),
        (left, bottom, right, bottom + deep),
    ]
    kept: list[Strip] = []
    for x_min, y_min, x_max, y_max in strips:
        x0, y0 = max(0, round(x_min)), max(0, round(y_min))
        x1, y1 = min(width, round(x_max)), min(height, round(y_max))
        if x1 > x0 and y1 > y0:
            kept.append((x0, y0, x1, y1))
    return kept


def spill(image: np.ndarray, box: Box, colour: ColorFillParams) -> float:
    """The most of any strip beside the box that shows the bar's colour, 0-1."""
    shares = [
        colour_share(image[y0:y1, x0:x1], colour) for x0, y0, x1, y1 in beside(image.shape, box)
    ]
    return max((share for share in shares if share is not None), default=0.0)


class GrowthWatch:
    """Says once per reader when its colour has spilled past the box for GROWN_AFTER_S.

    Only after a clean look first: a box learned beside something of its own colour spills from
    the start, and relearning couldn't fix that, so it would only spend vision calls.
    """

    def __init__(self) -> None:
        self._clean: set[str] = set()
        self._since: dict[str, float] = {}
        self._fired: set[str] = set()

    def update(self, reader: str, share: float, now: float) -> bool:
        if share < SPILL_SHARE:
            self._clean.add(reader)
            self._since.pop(reader, None)
            return False
        if reader not in self._clean or reader in self._fired:
            return False
        started = self._since.setdefault(reader, now)
        if now - started < GROWN_AFTER_S:
            return False
        self._fired.add(reader)
        return True
