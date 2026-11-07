import pytest

from brain.perception.coords import CropRegion, NormalizedBox, box_to_dip_rect, dip_to_physical
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
    "box", [(-1, 0, 10, 10), (0, 0, 1001, 10), (10, 0, 10, 10), (0, 20, 10, 10)]
)
def test_bad_boxes_are_rejected(box: tuple[int, int, int, int]) -> None:
    with pytest.raises(ValueError):
        NormalizedBox(*box)
