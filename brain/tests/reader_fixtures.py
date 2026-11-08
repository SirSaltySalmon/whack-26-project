"""Synthetic HUDs for reader tests: numpy bars and OpenCV text. No real game's images."""

from typing import Any

import cv2
import numpy as np

RED = (0, 0, 255)  # BGR
GREY = (60, 60, 60)
# Pure red sits at hue 0, so the range wraps past it, as reds do in OpenCV.
RED_RANGE = {"hsv_low": [170, 100, 100], "hsv_high": [10, 255, 255]}


def bar(fraction: float, length: int = 200, thickness: int = 20, axis: str = "x",
        reverse: bool = False) -> np.ndarray:  # fmt: skip
    """A red bar on grey, filled from the start edge: left, or bottom on axis y."""
    filled = round(length * fraction)
    strip = np.full((thickness, length, 3), GREY, dtype=np.uint8)
    if reverse:
        strip[:, length - filled :] = RED
    else:
        strip[:, :filled] = RED
    if axis == "x":
        return strip
    # Rotating a left-filled strip by 90 degrees counter-clockwise puts the fill at the bottom.
    return np.ascontiguousarray(np.rot90(strip))


def hearts(full: int, total: int = 10, size: int = 16, gap: int = 4) -> np.ndarray:
    """A row of icons with gaps between them, like a heart-style health display."""
    width = total * (size + gap)
    row = np.zeros((size, width, 3), dtype=np.uint8)
    for index in range(total):
        left = index * (size + gap) + gap // 2
        row[:, left : left + size] = RED if index < full else GREY
    return row


def text_image(text: str, width: int = 200, height: int = 32) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(image, text, (4, 24), cv2.FONT_HERSHEY_PLAIN, 1.5, (255, 255, 255), 1, cv2.LINE_8)
    return image


def place(canvas: np.ndarray, patch: np.ndarray, x: int, y: int) -> np.ndarray:
    canvas[y : y + patch.shape[0], x : x + patch.shape[1]] = patch
    return canvas


def health_profile(
    width: int = 400,
    height: int = 200,
    *,
    reader_type: str = "color_fill",
    rules: list[dict[str, Any]] | None = None,
    interval_s: float = 0.2,
) -> dict[str, Any]:
    """A profile with one health region at (20, 20), 200x20 pixels, in a width x height frame."""
    reader: dict[str, Any] = {
        "name": "health",
        "region": "health",
        "type": reader_type,
        "rules": rules
        if rules is not None
        else [{"when": "below", "value": 0.25, "clear_at": 0.4, "event": "health_low"}],
        "interval_s": interval_s,
    }
    if reader_type == "color_fill":
        reader["color"] = RED_RANGE
    else:
        reader["ocr"] = {"upscale": 1}
    return {
        "regions": [
            {
                "name": "health",
                "kind": "bar",
                "box": {"x": 20 / width, "y": 20 / height, "w": 200 / width, "h": 20 / height},
                "confidence": 1.0,
            }
        ],
        "readers": [reader],
        "learned_for": {"width": width, "height": height},
    }


def health_frame_image(fraction: float, width: int = 400, height: int = 200) -> np.ndarray:
    canvas = np.full((height, width, 3), 30, dtype=np.uint8)
    return place(canvas, bar(fraction), 20, 20)
