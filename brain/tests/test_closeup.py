import cv2
import numpy as np
import pytest

from brain.perception.closeup import AREA_NAMES, Closeup, make_closeup
from brain.perception.coords import CropRegion
from brain.tests.fakes import make_frame
from shared.protocol.messages import Rect

WIDTH, HEIGHT = 400, 200
WINDOW = CropRegion(30, 40, WIDTH, HEIGHT)

# In physical screen pixels, for a frame at the window offset above.
EXPECTED_REGIONS = {
    "whole": CropRegion(30, 40, 400, 200),
    "top": CropRegion(30, 40, 400, 100),
    "bottom": CropRegion(30, 140, 400, 100),
    "left": CropRegion(30, 40, 200, 200),
    "right": CropRegion(230, 40, 200, 200),
    "center": CropRegion(130, 90, 200, 100),
    "top_left": CropRegion(30, 40, 200, 100),
    "top_right": CropRegion(230, 40, 200, 100),
    "bottom_left": CropRegion(30, 140, 200, 100),
    "bottom_right": CropRegion(230, 140, 200, 100),
}


def decoded(closeup: Closeup) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(closeup.image, np.uint8), cv2.IMREAD_COLOR)


def gradient(width: int = WIDTH, height: int = HEIGHT) -> np.ndarray:
    """Each pixel's colour gives away where it came from, and smooth colours survive JPEG."""
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[..., 0] = np.linspace(0, 255, width).astype(np.uint8)
    image[..., 1] = np.linspace(0, 255, height).astype(np.uint8)[:, None]
    return image


def size_of(image: np.ndarray) -> tuple[int, int]:
    return image.shape[1], image.shape[0]


def test_every_area_has_an_expected_region() -> None:
    assert set(EXPECTED_REGIONS) == set(AREA_NAMES)
    assert len(AREA_NAMES) == 10


@pytest.mark.parametrize("area", AREA_NAMES)
def test_each_area_gives_the_right_region_with_the_window_offset(area: str) -> None:
    closeup = make_closeup(make_frame(WIDTH, HEIGHT, region=WINDOW), 1.0, 0, WIDTH, area)
    assert closeup.region == EXPECTED_REGIONS[area]


@pytest.mark.parametrize("area", AREA_NAMES)
def test_a_frame_with_no_window_starts_at_the_corner(area: str) -> None:
    expected = EXPECTED_REGIONS[area]
    closeup = make_closeup(make_frame(WIDTH, HEIGHT), 1.0, 0, WIDTH, area)
    assert closeup.region == CropRegion(
        expected.x - WINDOW.x, expected.y - WINDOW.y, expected.width, expected.height
    )


@pytest.mark.parametrize("area", AREA_NAMES)
def test_the_image_shows_the_pixels_its_region_claims(area: str) -> None:
    # A pointer's position comes from the region, so it has to describe what the model saw.
    image = gradient()
    closeup = make_closeup(make_frame(image=image, region=WINDOW), 1.0, 0, WIDTH, area)
    region = closeup.region
    left, top = region.x - WINDOW.x, region.y - WINDOW.y
    want = image[top : top + region.height, left : left + region.width].astype(int)
    got = cv2.resize(decoded(closeup), (region.width, region.height)).astype(int)
    assert np.abs(want - got)[..., :2].mean() < 4


@pytest.mark.parametrize(
    ("first", "second"),
    [("left", "right"), ("top", "bottom"), ("top_left", "top_right"), ("top_left", "bottom_left")],
)
def test_neighbouring_areas_leave_no_gap_on_odd_sizes(first: str, second: str) -> None:
    frame = make_frame(301, 151)
    one = make_closeup(frame, 1.0, 0, 301, first).region
    two = make_closeup(frame, 1.0, 0, 301, second).region
    if one.x == two.x:
        assert one.y + one.height == two.y
    else:
        assert one.x + one.width == two.x


def test_an_unknown_area_falls_back_to_the_whole_frame() -> None:
    frame = make_frame(WIDTH, HEIGHT, region=WINDOW)
    closeup = make_closeup(frame, 1.0, 0, WIDTH, "behind_the_waterfall")
    assert closeup.region == WINDOW
    assert size_of(decoded(closeup)) == (WIDTH, HEIGHT)


@pytest.mark.parametrize(
    ("size", "max_edge", "expected"),
    [
        # Shrinks to the limit, keeping its shape.
        ((800, 400), 200, (200, 100)),
        ((400, 800), 200, (100, 200)),
        # Already fits exactly.
        ((300, 150), 300, (300, 150)),
        # Grows by a whole multiple that fits.
        ((100, 50), 200, (200, 100)),
        ((100, 50), 350, (300, 150)),
        # 2.5 times would fit, but only whole multiples keep a pixel font crisp.
        ((120, 60), 300, (240, 120)),
        # Nearly double isn't double, so it stays as it is.
        ((150, 75), 299, (150, 75)),
    ],
)
def test_crops_are_sized_for_a_model_to_read(
    size: tuple[int, int], max_edge: int, expected: tuple[int, int]
) -> None:
    closeup = make_closeup(make_frame(*size), 1.0, 0, max_edge)
    assert size_of(decoded(closeup)) == expected


def test_resizing_leaves_the_region_in_screen_pixels() -> None:
    # Boxes come back relative to the image, so the region must still describe the real screen.
    shrunk = make_closeup(make_frame(800, 400, region=CropRegion(10, 20, 800, 400)), 1.0, 0, 200)
    grown = make_closeup(make_frame(100, 50, region=CropRegion(10, 20, 100, 50)), 1.0, 0, 400)
    assert shrunk.region == CropRegion(10, 20, 800, 400)
    assert grown.region == CropRegion(10, 20, 100, 50)


def test_doubling_keeps_hard_edges_with_no_blending() -> None:
    # A one-pixel checkerboard turns to flat grey under any smoothing resize.
    rows, cols = np.indices((32, 64))
    board = (((rows + cols) % 2) * 255).astype(np.uint8)
    image = cv2.cvtColor(board, cv2.COLOR_GRAY2BGR)
    out = decoded(make_closeup(make_frame(image=image), 1.0, 0, 128))
    assert size_of(out) == (128, 64)
    # JPEG rings a little, so allow for it. Each source pixel must still be a block of its colour.
    blocks = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(int)
    assert np.abs(blocks[::2, ::2] - board).mean() < 24
    assert np.abs(blocks[1::2, 1::2] - board).mean() < 24


def test_masking_comes_before_the_crop_and_uses_the_window_offset() -> None:
    white = np.full((100, 200, 3), 255, dtype=np.uint8)
    # At 150%, in physical pixels: x 150 to 210, y 75 to 105. Relative to this window, x 50 to 110
    # and y 25 to 55. The right half starts at x 100, so 10 pixels of the mask land in the crop.
    frame = make_frame(
        image=white,
        region=CropRegion(100, 50, 200, 100),
        rects=[Rect(x=100, y=50, width=40, height=20)],
    )
    out = decoded(make_closeup(frame, 1.5, 0, 100, "right"))
    assert out[40, 4].max() < 40
    assert out[40, 16].min() > 215
    assert out[15, 4].min() > 215


def test_masking_includes_the_padding() -> None:
    white = np.full((64, 64, 3), 255, dtype=np.uint8)
    frame = make_frame(image=white, rects=[Rect(x=24, y=24, width=16, height=16)])
    unpadded = decoded(make_closeup(frame, 1.0, 0, 64))
    padded = decoded(make_closeup(frame, 1.0, 8, 64))
    assert unpadded[20, 32].min() > 215
    assert padded[20, 32].max() < 40


def test_overlay_elements_outside_the_crop_leave_it_alone() -> None:
    white = np.full((100, 200, 3), 255, dtype=np.uint8)
    frame = make_frame(image=white, rects=[Rect(x=0, y=0, width=50, height=100)])
    assert decoded(make_closeup(frame, 1.0, 0, 100, "right")).min() > 215


def test_the_buffers_frame_is_left_untouched() -> None:
    frame = make_frame(100, 50, fill=255, rects=[Rect(x=0, y=0, width=100, height=50)])
    closeup = make_closeup(frame, 1.0, 0, 100)
    assert decoded(closeup).max() < 40
    assert frame.image.min() == 255
