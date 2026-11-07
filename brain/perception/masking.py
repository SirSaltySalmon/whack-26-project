"""Blanks overlay elements out of captured frames so the AI can't read its own UI."""

import math
from collections.abc import Iterable

import numpy as np

from brain.capture.ring_buffer import Frame
from brain.perception.coords import CropRegion, dip_to_physical
from brain.perception.profile_schema import Box
from shared.protocol.messages import Rect


def _frame_pixels(
    rect_dip: Rect, display_scale: float, padding_px: int, region: CropRegion | None
) -> tuple[int, int, int, int]:
    """Left, top, right and bottom in frame pixels. Not clipped to the frame."""
    rect = dip_to_physical(rect_dip, display_scale)
    offset_x, offset_y = (region.x, region.y) if region else (0, 0)
    # Round outward: a partly covered edge pixel can still leak UI text.
    return (
        math.floor(rect.x) - offset_x - padding_px,
        math.floor(rect.y) - offset_y - padding_px,
        math.ceil(rect.x + rect.width) - offset_x + padding_px,
        math.ceil(rect.y + rect.height) - offset_y + padding_px,
    )


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
    for rect_dip in rects_dip:
        left, top, right, bottom = _frame_pixels(rect_dip, display_scale, padding_px, region)
        left, top = max(0, left), max(0, top)
        right, bottom = min(width, right), min(height, bottom)
        if left < right and top < bottom:
            masked[top:bottom, left:right] = 0
    return masked


def box_is_masked(box: Box, frame: Frame, display_scale: float, padding_px: int) -> bool:
    """True if any overlay rectangle overlaps this box. Uses frame.overlay_rects and frame.region.

    Masks are filled with black, which looks like an empty bar, so a covered reader must report
    unknown rather than read the mask. Uses the same bounds as mask_overlay, so the two can't
    disagree about what's covered.
    """
    height, width = frame.image.shape[:2]
    # Round outward too, so a crop can't reach a pixel this check didn't consider.
    box_left = math.floor(box.x * width)
    box_top = math.floor(box.y * height)
    box_right = math.ceil((box.x + box.w) * width)
    box_bottom = math.ceil((box.y + box.h) * height)
    for rect_dip in frame.overlay_rects:
        left, top, right, bottom = _frame_pixels(rect_dip, display_scale, padding_px, frame.region)
        if left < box_right and box_left < right and top < box_bottom and box_top < bottom:
            return True
    return False
