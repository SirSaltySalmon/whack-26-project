"""Turns what a model looked at or noticed into boxes for the debug view (--debug-regions).

Only the debug view uses these, so nothing here decides anything. Model boxes are untrusted, so a
malformed one is dropped with a log line, never raised.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal

from brain.perception.coords import (
    CropRegion,
    box_to_dip_rect,
    physical_to_dip,
    pixel_box_to_normalized,
)
from shared.protocol import BrainMessage
from shared.protocol.messages import DebugSighting, DebugSightings, Rect

log = logging.getLogger(__name__)

Kind = Literal["noticed", "look", "point", "look_back"]
Send = Callable[[BrainMessage], Awaitable[None]]

# A little longer than the observer's slowest interval, 1.3 s, so its boxes rarely blink out
# between reports, but short enough that a moving enemy doesn't trail old boxes.
NOTICED_TTL_MS = 1600
# Tool boxes come once per player turn, so they stay long enough to be read.
TOOL_TTL_MS = 4000
MAX_LABEL_CHARS = 32


def short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_LABEL_CHARS else text[: MAX_LABEL_CHARS - 1] + "…"


def crop_of(width: int, height: int, region: CropRegion | None) -> CropRegion:
    """Where a whole frame of this size sits on screen, in physical pixels."""
    x, y = (region.x, region.y) if region else (0, 0)
    return CropRegion(x, y, width, height)


def noticed(
    items: Sequence[tuple[str, Sequence[float]]],
    image_width: int,
    image_height: int,
    crop: CropRegion,
    display_scale: float,
    ttl_ms: int = NOTICED_TTL_MS,
) -> list[DebugSighting]:
    """Labelled pixel boxes in the image sent, as overlay rects. Malformed boxes are dropped."""
    sightings = []
    for label, box_px in items:
        try:
            box = pixel_box_to_normalized(box_px, image_width, image_height)
        except (TypeError, ValueError):
            log.debug("Dropped an unusable sighting box for %r: %s", label, box_px)
            continue
        rect = box_to_dip_rect(box, crop, display_scale)
        sightings.append(rect_sighting(label, rect, "noticed", ttl_ms))
    return sightings


def area_sighting(
    label: str, crop: CropRegion, display_scale: float, kind: Kind, ttl_ms: int = TOOL_TTL_MS
) -> DebugSighting:
    """A whole area a tool sent to vision, such as look_closer's crop."""
    physical = Rect(x=crop.x, y=crop.y, width=crop.width, height=crop.height)
    rect = physical_to_dip(physical, display_scale)
    return DebugSighting(label=short(label), rect=rect, kind=kind, ttl_ms=ttl_ms)


def rect_sighting(label: str, rect: Rect, kind: Kind, ttl_ms: int = TOOL_TTL_MS) -> DebugSighting:
    """A box already in overlay coordinates, such as point_at's target."""
    return DebugSighting(label=short(label), rect=rect, kind=kind, ttl_ms=ttl_ms)


async def show(send: Send | None, sightings: list[DebugSighting]) -> None:
    """Sends them when debugging. A failed send only loses a debug box, so it never raises."""
    if send is None or not sightings:
        return
    try:
        await send(DebugSightings(sightings=sightings))
    except Exception:
        log.exception("Could not send %d debug sightings", len(sightings))
