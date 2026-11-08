import pytest

from brain.perception.coords import (
    CropRegion,
    NormalizedBox,
    box_to_dip_rect,
    dip_to_physical,
    pixel_box_to_normalized,
)
from shared.protocol.messages import Rect

SCREEN = CropRegion(0, 0, 1920, 1080)


def test_box_maps_to_dips_at_100_percent() -> None:
    rect = box_to_dip_rect(NormalizedBox(500, 250, 1000, 750), SCREEN, 1.0)
    assert rect == Rect(x=480, y=540, width=960, height=540)


def test_box_maps_to_dips_at_150_percent() -> None:
    rect = box_to_dip_rect(NormalizedBox(500, 250, 1000, 750), SCREEN, 1.5)
    assert rect == Rect(x=320, y=360, width=640, height=360)


def test_crop_offset_is_applied_before_scaling() -> None:
    crop = CropRegion(300, 150, 600, 300)
    rect = box_to_dip_rect(NormalizedBox(0, 0, 1000, 1000), crop, 1.5)
    assert rect == Rect(x=200, y=100, width=400, height=200)


def test_dip_to_physical_scales_up() -> None:
    assert dip_to_physical(Rect(x=200, y=100, width=400, height=200), 1.5) == Rect(
        x=300, y=150, width=600, height=300
    )


@pytest.mark.parametrize(
    "box",
    [
        (-1, 0, 10, 10),
        (0, 0, 1001, 10),
        (10, 0, 10, 10),
        (0, 20, 10, 10),
        (float("nan"), 0, 10, 10),
        (0, 0, float("inf"), 10),
    ],
)
def test_bad_boxes_are_rejected(box: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValueError):
        NormalizedBox(*box)


def test_a_pixel_box_on_a_shrunk_image_lands_on_the_full_screen() -> None:
    # A 1920x1080 screen sent as 1280x720: the right half of the image is the right half of it.
    box = pixel_box_to_normalized([640, 0, 1280, 720], 1280, 720)
    assert (box.ymin, box.xmin, box.ymax, box.xmax) == (0, 500, 1000, 1000)
    rect = box_to_dip_rect(box, SCREEN, 1.0)
    assert (rect.x, rect.y, rect.width, rect.height) == (960, 0, 960, 1080)


def test_a_pixel_box_at_150_percent_scaling() -> None:
    box = pixel_box_to_normalized([320, 180, 960, 540], 1280, 720)
    rect = box_to_dip_rect(box, SCREEN, 1.5)
    # The middle quarter of 1920x1080 physical pixels, in DIPs at 150%.
    assert (rect.x, rect.y, rect.width, rect.height) == pytest.approx((320, 180, 640, 360))


@pytest.mark.parametrize(
    "box_px",
    [
        [0, 0, 100],
        [-5, 0, 100, 100],
        [0, 0, 1281, 100],
        [100, 0, 100, 100],
        [float("nan"), 0, 1, 1],
    ],
)
def test_a_pixel_box_that_cant_be_used_is_refused(box_px: list[float]) -> None:
    with pytest.raises(ValueError):
        pixel_box_to_normalized(box_px, 1280, 720)
