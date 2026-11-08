"""A second, closer look around a HUD element already found, for small ones a full view misses.

A whole-screen image at 1280 px loses small, low-contrast icons. In a live Terraria run the single
mana star went unreported in every frame, while a crop around the hearts, enlarged, showed it.
Resource displays tend to sit together, so the area around the first one found is where to look.
Nothing here knows a game: the anchor is whichever bar the full view agreed on.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import cv2

from brain.capture.ring_buffer import Frame
from brain.learner.regions import AgreedRegion, RegionProposal, agree
from brain.perception.closeup import encode_jpeg, fit_image
from brain.perception.masking import mask_overlay
from brain.perception.profile_schema import Box

# How far around the anchor to look, in multiples of its own width and height.
SIDE_WIDTHS = 3.0
UP_DOWN_HEIGHTS = 4.0
MAX_ENLARGE = 4.0

# Sends one zoomed image and returns what vision saw, or None once the call budget is spent.
Ask = Callable[[bytes, int, int], Awaitable[RegionProposal | None]]


@dataclass(frozen=True)
class Zoom:
    image: bytes
    width: int  # The image sent, after enlarging
    height: int
    left: int  # The crop, in frame pixels
    top: int
    crop_width: int
    crop_height: int


def zoom_around(
    frame: Frame, box: Box, display_scale: float, padding_px: int, max_edge_px: int
) -> Zoom | None:
    """CPU-bound, so run it in a worker thread. The overlay is masked first, as for any look."""
    masked = mask_overlay(frame.image, frame.overlay_rects, display_scale, padding_px, frame.region)
    height, width = masked.shape[:2]
    x, y, w, h = box.x * width, box.y * height, box.w * width, box.h * height
    left = int(max(0.0, x - SIDE_WIDTHS * w))
    right = int(min(float(width), x + w + SIDE_WIDTHS * w))
    top = int(max(0.0, y - UP_DOWN_HEIGHTS * h))
    bottom = int(min(float(height), y + h + UP_DOWN_HEIGHTS * h))
    crop = masked[top:bottom, left:right]
    if crop.size == 0:
        return None
    # Enlarged by any factor, not only whole ones: a 759 px crop at 1280 px would otherwise stay
    # its own size, and the mana star it was meant to show stayed too small to read.
    factor = min(MAX_ENLARGE, max_edge_px / max(crop.shape[:2]))
    if factor > 1:
        size = (round(crop.shape[1] * factor), round(crop.shape[0] * factor))
        fitted = cv2.resize(crop, size, interpolation=cv2.INTER_NEAREST)
    else:
        fitted = fit_image(crop, max_edge_px)
    return Zoom(
        encode_jpeg(fitted), fitted.shape[1], fitted.shape[0], left, top, right - left, bottom - top
    )


def to_image_space(
    proposal: RegionProposal, zoom: Zoom, frame_size: tuple[int, int], image_size: tuple[int, int]
) -> RegionProposal:
    """Moves boxes from the zoomed image's pixels to the full view's, so both can agree."""
    frame_w, frame_h = frame_size
    image_w, image_h = image_size

    def x(value: float) -> float:
        return (zoom.left + value / zoom.width * zoom.crop_width) / frame_w * image_w

    def y(value: float) -> float:
        return (zoom.top + value / zoom.height * zoom.crop_height) / frame_h * image_h

    regions = [
        region.model_copy(update={"box_px": [x(b[0]), y(b[1]), x(b[2]), y(b[3])]})
        for region in proposal.regions
        if len(b := region.box_px) == 4
    ]
    return proposal.model_copy(update={"regions": regions})


def anchor_of(agreed: Sequence[AgreedRegion]) -> AgreedRegion | None:
    """Health if it was found, else any bar: resource displays tend to sit beside it."""
    bars = [a for a in agreed if a.region.kind == "bar"]
    return next((a for a in bars if a.region.name == "health"), bars[0] if bars else None)


async def zoom_pass(
    frames: Sequence[Frame],
    agreed: Sequence[AgreedRegion],
    image_size: tuple[int, int],
    ask: Ask,
    zoom: Callable[[Frame, Box], Awaitable[Zoom | None]],
) -> list[AgreedRegion]:
    """Regions only the closer look found and most zoomed frames agree on, in full-view pixels."""
    anchor = anchor_of(agreed)
    if anchor is None:
        return []
    known = {a.region.name for a in agreed}
    seen: list[RegionProposal] = []
    for frame in frames:
        zoomed = await zoom(frame, anchor.region.box)
        if zoomed is None:
            break
        proposal = await ask(zoomed.image, zoomed.width, zoomed.height)
        if proposal is None:
            break
        height, width = frame.image.shape[:2]
        seen.append(to_image_space(proposal, zoomed, (width, height), image_size))
    # Frame indices line up with `frames` because this stops early rather than skipping one.
    return [a for a in agree(seen, image_size) if a.region.name not in known]
