"""The single conversion path between model output, screen pixels and overlay coordinates.

Gemini boxes are [ymin, xmin, ymax, xmax] on a 0-1000 scale relative to the image sent. A relative
scale means downscaling the image before sending doesn't change the result.
"""

from dataclasses import dataclass

from shared.protocol.messages import Rect


@dataclass(frozen=True)
class NormalizedBox:
    ymin: float
    xmin: float
    ymax: float
    xmax: float

    def __post_init__(self) -> None:
        values = (self.ymin, self.xmin, self.ymax, self.xmax)
        if any(v < 0 or v > 1000 for v in values):
            raise ValueError(f"Box outside the 0-1000 range: {values}")
        if self.ymin >= self.ymax or self.xmin >= self.xmax:
            raise ValueError(f"Box has no area: {values}")


@dataclass(frozen=True)
class CropRegion:
    """Where the image sent to the model came from, in physical screen pixels."""

    x: int
    y: int
    width: int
    height: int


def box_to_physical_rect(box: NormalizedBox, crop: CropRegion) -> Rect:
    return Rect(
        x=crop.x + box.xmin / 1000 * crop.width,
        y=crop.y + box.ymin / 1000 * crop.height,
        width=(box.xmax - box.xmin) / 1000 * crop.width,
        height=(box.ymax - box.ymin) / 1000 * crop.height,
    )


def physical_to_dip(rect: Rect, display_scale: float) -> Rect:
    return Rect(
        x=rect.x / display_scale,
        y=rect.y / display_scale,
        width=rect.width / display_scale,
        height=rect.height / display_scale,
    )


def dip_to_physical(rect: Rect, display_scale: float) -> Rect:
    return Rect(
        x=rect.x * display_scale,
        y=rect.y * display_scale,
        width=rect.width * display_scale,
        height=rect.height * display_scale,
    )


def box_to_dip_rect(box: NormalizedBox, crop: CropRegion, display_scale: float) -> Rect:
    """Model box to overlay coordinates. Use this for all pointing."""
    return physical_to_dip(box_to_physical_rect(box, crop), display_scale)
