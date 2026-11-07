import math

import numpy as np
import pytest

from brain.capture.ring_buffer import Frame
from brain.perception.coords import CropRegion
from brain.perception.masking import box_is_masked, mask_overlay
from brain.perception.profile_schema import Box
from brain.tests.fakes import make_frame
from shared.protocol.messages import Rect


def white(height: int = 100, width: int = 200) -> np.ndarray:
    return np.full((height, width, 3), 255, dtype=np.uint8)


def test_masks_rect_with_padding_and_keeps_the_original() -> None:
    image = white()
    masked = mask_overlay(image, [Rect(x=10, y=10, width=20, height=20)], 1.0, 2)
    assert masked[8, 8].sum() == 0 and masked[31, 31].sum() == 0
    assert masked[7, 7].sum() > 0 and masked[32, 32].sum() > 0
    assert image.min() == 255


def test_converts_dips_to_physical_pixels() -> None:
    masked = mask_overlay(white(), [Rect(x=10, y=10, width=10, height=10)], 2.0, 0)
    assert masked[20, 20].sum() == 0 and masked[39, 39].sum() == 0
    assert masked[40, 40].sum() > 0


def test_cropped_frame_is_masked_where_the_overlay_really_is() -> None:
    rect = Rect(x=110, y=60, width=10, height=10)
    masked = mask_overlay(white(), [rect], 1.0, 0, CropRegion(100, 50, 200, 100))
    assert masked[10, 10].sum() == 0 and masked[19, 19].sum() == 0
    assert masked[20, 20].sum() > 0 and masked[60, 110].sum() > 0


def test_rects_off_screen_are_clipped() -> None:
    masked = mask_overlay(white(), [Rect(x=190, y=90, width=500, height=500)], 1.0, 0)
    assert masked[99, 199].sum() == 0
    masked = mask_overlay(white(), [Rect(x=900, y=900, width=10, height=10)], 1.0, 0)
    assert masked.min() == 255


# Powers of two, so a box's fractions and its pixels convert exactly.
WIDTH, HEIGHT = 512, 256


def pixels(frame: Frame, left: int, top: int, right: int, bottom: int) -> Box:
    """A box from frame pixels, which is easier to check against a rectangle than fractions."""
    height, width = frame.image.shape[:2]
    return Box(x=left / width, y=top / height, w=(right - left) / width, h=(bottom - top) / height)


def covered_frame(rect: Rect, region: CropRegion | None = None) -> Frame:
    return make_frame(WIDTH, HEIGHT, region=region, rects=[rect])


def test_a_box_under_an_overlay_rect_is_masked() -> None:
    frame = covered_frame(Rect(x=100, y=40, width=20, height=20))
    assert box_is_masked(pixels(frame, 110, 50, 130, 70), frame, 1.0, 0)


def test_a_box_fully_inside_or_around_a_rect_is_masked() -> None:
    frame = covered_frame(Rect(x=100, y=40, width=40, height=40))
    assert box_is_masked(pixels(frame, 110, 50, 120, 60), frame, 1.0, 0)
    assert box_is_masked(pixels(frame, 90, 30, 150, 90), frame, 1.0, 0)


def test_a_box_clear_of_every_rect_is_not_masked() -> None:
    rects = [Rect(x=0, y=0, width=20, height=20), Rect(x=400, y=200, width=20, height=20)]
    frame = make_frame(WIDTH, HEIGHT, rects=rects)
    assert not box_is_masked(pixels(frame, 100, 100, 200, 150), frame, 1.0, 0)


def test_any_one_rect_overlapping_is_enough() -> None:
    rects = [Rect(x=0, y=0, width=20, height=20), Rect(x=150, y=120, width=20, height=20)]
    frame = make_frame(WIDTH, HEIGHT, rects=rects)
    assert box_is_masked(pixels(frame, 100, 100, 200, 150), frame, 1.0, 0)


def test_with_no_rects_nothing_is_masked() -> None:
    frame = make_frame(WIDTH, HEIGHT)
    assert not box_is_masked(Box(x=0, y=0, w=1, h=1), frame, 1.5, 8)


def test_rects_are_dips_at_100_percent() -> None:
    frame = covered_frame(Rect(x=100, y=40, width=20, height=20))
    assert box_is_masked(pixels(frame, 100, 40, 120, 60), frame, 1.0, 0)
    assert not box_is_masked(pixels(frame, 150, 60, 180, 90), frame, 1.0, 0)


def test_rects_are_dips_at_150_percent() -> None:
    # The same rectangle is x 150 to 180 and y 60 to 90 in physical pixels.
    frame = covered_frame(Rect(x=100, y=40, width=20, height=20))
    assert box_is_masked(pixels(frame, 150, 60, 180, 90), frame, 1.5, 0)
    assert not box_is_masked(pixels(frame, 100, 40, 120, 60), frame, 1.5, 0)


def test_a_cropped_frame_uses_its_window_offset() -> None:
    # Screen x 110 to 120 is frame x 10 to 20, so the box at frame x 110 is clear of it.
    window = CropRegion(100, 50, WIDTH, HEIGHT)
    frame = covered_frame(Rect(x=110, y=60, width=10, height=10), window)
    assert box_is_masked(pixels(frame, 10, 10, 20, 20), frame, 1.0, 0)
    assert not box_is_masked(pixels(frame, 110, 60, 120, 70), frame, 1.0, 0)


def test_scale_applies_before_the_window_offset() -> None:
    # At 150%, screen x 330 to 360, which is frame x 30 to 60 once the window's 300 is taken off.
    # Taking the offset off first would land somewhere else entirely.
    window = CropRegion(300, 150, WIDTH, HEIGHT)
    frame = covered_frame(Rect(x=220, y=120, width=20, height=20), window)
    assert box_is_masked(pixels(frame, 40, 40, 50, 50), frame, 1.5, 0)
    assert not box_is_masked(pixels(frame, 64, 64, 96, 96), frame, 1.5, 0)


def test_padding_reaches_exactly_as_far_as_the_mask() -> None:
    # The rectangle's right edge is x 120. Padding of 5 blanks up to, but not including, x 125.
    frame = covered_frame(Rect(x=100, y=40, width=20, height=20))
    box = pixels(frame, 125, 40, 140, 60)
    assert not box_is_masked(box, frame, 1.0, 0)
    assert not box_is_masked(box, frame, 1.0, 5)
    assert box_is_masked(box, frame, 1.0, 6)


@pytest.mark.parametrize(
    "edge",
    [
        (120, 40, 160, 60),  # Right of the rectangle
        (60, 40, 100, 60),  # Left of it
        (100, 60, 120, 100),  # Below it
        (100, 8, 120, 40),  # Above it
        (120, 60, 160, 100),  # Touching only at a corner
    ],
)
def test_a_rect_touching_an_edge_without_overlapping_is_not_masked(
    edge: tuple[int, int, int, int],
) -> None:
    frame = covered_frame(Rect(x=100, y=40, width=20, height=20))
    assert not box_is_masked(pixels(frame, *edge), frame, 1.0, 0)


def test_a_box_starting_part_way_through_a_pixel_counts_that_pixel() -> None:
    # A crop could reach pixel 119, so a box starting inside it isn't clear of a rect ending at 120.
    frame = covered_frame(Rect(x=100, y=40, width=20, height=20))
    box = Box(x=119.5 / WIDTH, y=40 / HEIGHT, w=20 / WIDTH, h=20 / HEIGHT)
    assert box_is_masked(box, frame, 1.0, 0)


def test_a_partly_covered_rect_pixel_counts_as_covered() -> None:
    # A rectangle ending at 30.5 still blanks pixel 30, as mask_overlay does.
    frame = covered_frame(Rect(x=10.5, y=10, width=20, height=10))
    assert box_is_masked(pixels(frame, 30, 10, 40, 20), frame, 1.0, 0)
    assert not box_is_masked(pixels(frame, 31, 10, 40, 20), frame, 1.0, 0)


def test_a_black_bar_with_nothing_over_it_is_not_masked() -> None:
    # An empty bar and a mask are both black, so this has to go by rectangles, never by pixels.
    black = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    frame = make_frame(image=black, rects=[Rect(x=400, y=200, width=20, height=20)])
    assert not box_is_masked(pixels(frame, 0, 0, 100, 20), frame, 1.0, 0)


def test_a_bright_bar_under_a_rect_is_still_masked() -> None:
    bright = np.full((HEIGHT, WIDTH, 3), 255, dtype=np.uint8)
    frame = make_frame(image=bright, rects=[Rect(x=0, y=0, width=100, height=20)])
    assert box_is_masked(pixels(frame, 0, 0, 100, 20), frame, 1.0, 0)


def test_rects_outside_the_frame_mask_nothing() -> None:
    frame = covered_frame(Rect(x=0, y=0, width=50, height=50), CropRegion(100, 100, WIDTH, HEIGHT))
    assert not box_is_masked(Box(x=0, y=0, w=1, h=1), frame, 1.0, 0)


def test_a_rect_crossing_the_frames_edge_masks_what_it_reaches() -> None:
    window = CropRegion(100, 100, WIDTH, HEIGHT)
    frame = covered_frame(Rect(x=90, y=90, width=20, height=20), window)
    assert box_is_masked(pixels(frame, 0, 0, 16, 16), frame, 1.0, 0)
    assert not box_is_masked(pixels(frame, 16, 16, 32, 32), frame, 1.0, 0)


@pytest.mark.parametrize(
    ("scale", "padding", "region"),
    [
        (1.0, 0, None),
        (1.0, 3, CropRegion(40, 20, 64, 48)),
        (1.25, 0, CropRegion(7, 3, 64, 48)),
        (1.5, 2, None),
        (1.5, 0, CropRegion(40, 20, 64, 48)),
        (1.75, 1, CropRegion(11, 13, 64, 48)),
        (2.0, 0, CropRegion(40, 20, 64, 48)),
    ],
)
def test_box_is_masked_agrees_with_what_mask_overlay_blanks(
    scale: float, padding: int, region: CropRegion | None
) -> None:
    # Fractional, overlapping and crossing the frame's edges, so rounding gets exercised.
    rects = [
        Rect(x=33.3, y=21.7, width=11.1, height=7.9),
        Rect(x=9.4, y=30.2, width=3.3, height=4.1),
        Rect(x=-5.5, y=-5.5, width=12.6, height=12.6),
        Rect(x=52.1, y=40.9, width=30.0, height=30.0),
    ]
    white = np.full((48, 64, 3), 255, dtype=np.uint8)
    frame = make_frame(image=white, region=region, rects=rects)
    masked = mask_overlay(white, rects, scale, padding, region)

    seen = {True: 0, False: 0}
    for left in range(0, 62, 3):
        for top in range(0, 46, 3):
            for width, height in ((1, 1), (2.5, 1.5), (7, 3), (3, 11), (20, 2)):
                if left + width > 64 or top + height > 48:
                    continue
                box = Box(x=left / 64, y=top / 48, w=width / 64, h=height / 48)
                reached = masked[
                    math.floor(box.y * 48) : math.ceil((box.y + box.h) * 48),
                    math.floor(box.x * 64) : math.ceil((box.x + box.w) * 64),
                ]
                blanked = bool((reached == 0).any())
                assert box_is_masked(box, frame, scale, padding) == blanked, (left, top, width)
                seen[blanked] += 1
    # Guards the check itself: it has to have seen plenty of both answers.
    assert seen[True] > 50 and seen[False] > 50
