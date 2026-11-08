"""The closer look around a found HUD element, which caught Terraria's mana star in a test."""

from typing import Any

import numpy as np
import pytest

from brain.capture.ring_buffer import Frame
from brain.learner.regions import AgreedRegion, RegionProposal, agree
from brain.learner.zoom import Zoom, anchor_of, to_image_space, zoom_around, zoom_pass
from brain.perception.profile_schema import Box

FRAME = (400, 200)
IMAGE = (800, 400)  # The full view sent for a 400x200 frame
# Health at x 200-240 and y 20-30 of the frame, so 40 wide and 10 tall.
HEALTH = Box(x=0.5, y=0.1, w=0.1, h=0.05)


def frame() -> Frame:
    return Frame(0.0, np.zeros((FRAME[1], FRAME[0], 3), dtype=np.uint8))


def region(name: str, box_px: list[float], kind: str = "bar") -> dict[str, Any]:
    return {"name": name, "kind": kind, "box_px": box_px, "text_seen": None,
            "fraction_seen": 1.0, "fill_color": "red", "confidence": 0.9}  # fmt: skip


def proposal(*regions: dict[str, Any]) -> RegionProposal:
    return RegionProposal.model_validate({"is_gameplay": True, "regions": list(regions)})


def health_found() -> list[AgreedRegion]:
    # Health in full-view pixels: twice the frame's.
    seen = proposal(region("health", [400, 40, 480, 60]))
    return agree([seen, seen], IMAGE)


def test_the_zoom_covers_the_area_around_the_anchor_and_enlarges_it() -> None:
    zoom = zoom_around(frame(), HEALTH, 1.0, 0, 800)
    assert zoom is not None
    # 3 widths either side and 4 heights above and below, clamped to the frame.
    assert (zoom.left, zoom.top, zoom.crop_width, zoom.crop_height) == (80, 0, 280, 70)
    # Enlarged to fill the long edge, by any factor: 800 / 280 here.
    assert (zoom.width, zoom.height) == (800, 200)


def test_the_zoom_never_enlarges_more_than_four_times() -> None:
    tiny = Box(x=0.5, y=0.1, w=0.01, h=0.01)  # 4 x 2 pixels, so its area is 28 x 18
    zoom = zoom_around(frame(), tiny, 1.0, 0, 1280)
    assert zoom is not None and (zoom.width, zoom.height) == (112, 72)


def test_a_zoomed_box_maps_back_to_full_view_pixels() -> None:
    zoom = Zoom(b"", 560, 140, 80, 0, 280, 70)
    whole = to_image_space(proposal(region("energy", [0, 0, 560, 140])), zoom, FRAME, IMAGE)
    # The whole zoom is frame x 80-360, y 0-70, which is double that in the full view.
    assert whole.regions[0].box_px == pytest.approx([160, 0, 720, 140])


def test_health_anchors_the_zoom_and_a_lone_number_cant() -> None:
    assert anchor_of(health_found()) is not None
    number = proposal(region("currency", [10, 10, 50, 30], kind="number"))
    assert anchor_of(agree([number, number], IMAGE)) is None


async def test_the_closer_look_adds_what_only_it_found() -> None:
    asked: list[tuple[int, int]] = []

    async def ask(_image: bytes, width: int, height: int) -> RegionProposal | None:
        asked.append((width, height))
        # Health again, plus a mana star to its right, in the zoomed image's pixels.
        return proposal(region("health", [240, 40, 320, 60]), region("energy", [440, 40, 470, 70]))

    async def zoom(found: Frame, box: Box) -> Zoom | None:
        # 560 enlarges the 280 x 70 area exactly twice, which keeps the numbers below simple.
        return zoom_around(found, box, 1.0, 0, 560)

    extra = await zoom_pass([frame(), frame(), frame()], health_found(), IMAGE, ask, zoom)
    assert [a.region.name for a in extra] == ["energy"]  # Health was already known
    assert asked == [(560, 140)] * 3
    box = extra[0].region.box
    # Zoom x 440-470 is frame x 80 + 220..235, so 300-315, and y 20-35, as fractions.
    assert (box.x, box.y, box.w, box.h) == pytest.approx((0.75, 0.1, 0.0375, 0.075))


async def test_the_closer_look_stops_when_the_budget_runs_out() -> None:
    calls = 0

    async def ask(_image: bytes, _width: int, _height: int) -> RegionProposal | None:
        nonlocal calls
        calls += 1
        return proposal(region("energy", [440, 40, 470, 70])) if calls == 1 else None

    async def zoom(found: Frame, box: Box) -> Zoom | None:
        # 560 enlarges the 280 x 70 area exactly twice, which keeps the numbers below simple.
        return zoom_around(found, box, 1.0, 0, 560)

    # One zoomed sighting can't agree with anything, so nothing is added.
    assert await zoom_pass([frame(), frame(), frame()], health_found(), IMAGE, ask, zoom) == []
    assert calls == 2


async def test_nothing_to_anchor_means_no_calls() -> None:
    async def ask(_image: bytes, _width: int, _height: int) -> RegionProposal | None:
        raise AssertionError("no call expected")

    async def zoom(found: Frame, box: Box) -> Zoom | None:
        raise AssertionError("no zoom expected")

    assert await zoom_pass([frame()], [], IMAGE, ask, zoom) == []
