import numpy as np

from brain.perception.masking import mask_overlay
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


def test_rects_off_screen_are_clipped() -> None:
    masked = mask_overlay(white(), [Rect(x=190, y=90, width=500, height=500)], 1.0, 0)
    assert masked[99, 199].sum() == 0
    masked = mask_overlay(white(), [Rect(x=900, y=900, width=10, height=10)], 1.0, 0)
    assert masked.min() == 255
