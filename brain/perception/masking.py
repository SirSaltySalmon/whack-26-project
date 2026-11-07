"""Blanks overlay elements out of captured frames so the AI can't read its own UI."""

import math
from collections.abc import Iterable

import numpy as np

from brain.perception.coords import CropRegion, dip_to_physical
from shared.protocol.messages import Rect


def mask_overlay(
    image: np.ndarray,
    rects_dip: Iterable[Rect],
    display_scale: float,
    padding_px: int,
    region: CropRegion | None = None,
) -> np.ndarray:
    """Returns a masked copy. The ring buffer's frame is left untouched.

    Overlay rectangles are relative to the screen, so a cropped frame must pass its region.
    """
    masked = image.copy()
    height, width = image.shape[:2]
    offset_x, offset_y = (region.x, region.y) if region else (0, 0)
    for rect_dip in rects_dip:
        rect = dip_to_physical(rect_dip, display_scale)
        # Round outward: a partly covered edge pixel can still leak UI text.
        left = max(0, math.floor(rect.x) - offset_x - padding_px)
        top = max(0, math.floor(rect.y) - offset_y - padding_px)
        right = min(width, math.ceil(rect.x + rect.width) - offset_x + padding_px)
        bottom = min(height, math.ceil(rect.y + rect.height) - offset_y + padding_px)
        if left < right and top < bottom:
            masked[top:bottom, left:right] = 0
    return masked
