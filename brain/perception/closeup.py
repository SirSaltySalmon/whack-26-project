"""Makes the image for a closer look: masked, cropped to an area, and sized for a model to read.

The ring buffer already holds full-resolution frames, so "closer" mostly means not shrinking them.
Small crops are also enlarged, which helps with pixel fonts and tiny HUD icons.
"""

from dataclasses import dataclass
from typing import Literal, get_args

import cv2
import numpy as np

from brain.capture.ring_buffer import Frame
from brain.perception.coords import CropRegion
from brain.perception.masking import mask_overlay

JPEG_QUALITY = 90

# The turn model can't see the frame, so it names an area rather than giving coordinates.
Area = Literal[
    "whole",
    "top",
    "bottom",
    "left",
    "right",
    "center",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
]
AREA_NAMES: tuple[str, ...] = get_args(Area)

# Fractions of the frame: left, top, right, bottom.
_AREAS: dict[str, tuple[float, float, float, float]] = {
    "whole": (0.0, 0.0, 1.0, 1.0),
    "top": (0.0, 0.0, 1.0, 0.5),
    "bottom": (0.0, 0.5, 1.0, 1.0),
    "left": (0.0, 0.0, 0.5, 1.0),
    "right": (0.5, 0.0, 1.0, 1.0),
    "center": (0.25, 0.25, 0.75, 0.75),
    "top_left": (0.0, 0.0, 0.5, 0.5),
    "top_right": (0.5, 0.0, 1.0, 0.5),
    "bottom_left": (0.0, 0.5, 0.5, 1.0),
    "bottom_right": (0.5, 0.5, 1.0, 1.0),
}


@dataclass(frozen=True)
class Closeup:
    image: bytes
    # What the image covers, in physical screen pixels. A model's box converts through this.
    region: CropRegion


def encode_jpeg(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError("Could not encode the frame as JPEG")
    return encoded.tobytes()


def _fit(image: np.ndarray, max_edge_px: int) -> np.ndarray:
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest > max_edge_px:
        scale = max_edge_px / longest
        return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    # Whole multiples with nearest-neighbour keep pixel fonts crisp instead of blurring them.
    factor = max_edge_px // longest
    if factor >= 2:
        return cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_NEAREST)
    return image


def make_closeup(
    frame: Frame,
    display_scale: float,
    padding_px: int,
    max_edge_px: int,
    area: str = "whole",
) -> Closeup:
    """CPU-bound, so callers run it in a worker thread. The buffer's frame is left untouched."""
    masked = mask_overlay(frame.image, frame.overlay_rects, display_scale, padding_px, frame.region)
    height, width = masked.shape[:2]
    left_f, top_f, right_f, bottom_f = _AREAS.get(area, _AREAS["whole"])
    left, top = round(width * left_f), round(height * top_f)
    right, bottom = round(width * right_f), round(height * bottom_f)
    offset_x, offset_y = (frame.region.x, frame.region.y) if frame.region else (0, 0)
    return Closeup(
        image=encode_jpeg(_fit(masked[top:bottom, left:right], max_edge_px)),
        region=CropRegion(offset_x + left, offset_y + top, right - left, bottom - top),
    )
