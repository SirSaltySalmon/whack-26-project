"""Compiled readers on synthetic HUDs: bars, icon rows and text."""

import numpy as np
import pytest

from brain.perception.coords import CropRegion, fraction_box_to_dip_rect
from brain.perception.ocr import OcrWorker
from brain.perception.profile_schema import Box, ReaderSpec
from brain.perception.readers import ColorFillReader, OcrReader, compile_profile, crop_box
from brain.tests.reader_fixtures import (
    RED_RANGE,
    bar,
    health_profile,
    hearts,
    text_image,
)


def colour_reader(axis: str = "x", reverse: bool = False) -> ColorFillReader:
    color = {**RED_RANGE, "axis": axis, "reverse": reverse}
    spec = ReaderSpec(name="health", region="health", type="color_fill", color=color)  # type: ignore[arg-type]
    return ColorFillReader(spec)


def ocr_reader(kind: str, min_score: float = 0.6) -> OcrReader:
    spec = ReaderSpec(name="hp", region="hp", type=kind, ocr={"min_score": min_score})  # type: ignore[arg-type]
    return OcrReader(spec)


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("reverse", [False, True])
def test_a_bar_reads_how_full_it_is(axis: str, reverse: bool) -> None:
    reading = colour_reader(axis, reverse).read(bar(0.72, axis=axis, reverse=reverse))
    assert reading.status == "ok"
    assert reading.value == pytest.approx(0.72, abs=0.05)
    assert reading.display == "72%"


def test_a_row_of_icons_with_gaps_reads_against_a_full_row() -> None:
    # Ten 16-pixel hearts with 4-pixel gaps colour 80% of the row's columns when full.
    reader = colour_reader()
    reader._params = reader._params.model_copy(update={"full_at": 0.8})
    reading = reader.read(hearts(full=7))
    assert reading.status == "ok"
    assert reading.value == pytest.approx(0.7, abs=0.05)


def test_no_matching_colour_is_unreadable_not_empty() -> None:
    reader = colour_reader()
    assert reader.read(bar(0.0)).status == "unreadable"
    assert reader.read(np.zeros((20, 200, 3), dtype=np.uint8)).status == "unreadable"
    assert reader.read(np.zeros((0, 0, 3), dtype=np.uint8)).status == "unreadable"


def test_ocr_text_is_parsed_by_reader_type() -> None:
    fraction = ocr_reader("ocr_fraction").parse([("Life: 340/400", 0.99)])
    assert (fraction.status, fraction.value, fraction.display) == ("ok", 0.85, "340/400")
    number = ocr_reader("ocr_number").parse([("Gold 1,250", 0.98)])
    assert (number.value, number.display) == (1250.0, "1250")
    text = ocr_reader("ocr_text").parse([("Defeat the boss", 0.97)])
    assert text.value == "Defeat the boss"


@pytest.mark.parametrize(
    ("kind", "lines"),
    [
        ("ocr_fraction", [("72/100", 0.3)]),  # Below min_score
        ("ocr_fraction", [("120/100", 0.99)]),  # More than the maximum
        ("ocr_fraction", [("no numbers", 0.99)]),
        ("ocr_number", [("none here", 0.99)]),
        ("ocr_text", []),
    ],
)
def test_bad_ocr_is_unreadable(kind: str, lines: list[tuple[str, float]]) -> None:
    assert ocr_reader(kind).parse(lines).status == "unreadable"


async def test_real_ocr_reads_a_drawn_fraction() -> None:
    worker = OcrWorker()
    reader = ocr_reader("ocr_fraction")
    try:
        lines = await worker.read(reader.prepare(text_image("72/100")), reader.detect)
    finally:
        worker.close()
    reading = reader.parse(lines)
    assert reading.status == "ok" and reading.value == pytest.approx(0.72)
    assert not reader.detect  # Numbers skip text detection, which is about 50 times slower


def test_a_bad_entry_is_skipped_and_the_rest_still_compile() -> None:
    data = health_profile()
    outside = {"x": 0.9, "y": 0, "w": 0.5, "h": 0.1}  # Runs off the frame's right edge
    data["regions"].append({"name": "broken", "kind": "bar", "box": outside, "confidence": 1})
    data["readers"] += [
        {"name": "no_color", "region": "health", "type": "color_fill"},
        {"name": "orphan", "region": "missing", "type": "ocr_text", "ocr": {}},
        {**data["readers"][0]},  # A duplicate name
    ]
    placed = compile_profile(data)
    assert [p.spec.name for p in placed] == ["health"]


def test_crop_matches_the_box_in_pixels() -> None:
    image = np.zeros((200, 400, 3), dtype=np.uint8)
    crop = crop_box(image, Box(x=0.05, y=0.1, w=0.5, h=0.1))
    assert crop.shape[:2] == (20, 200)


@pytest.mark.parametrize("scale", [1.0, 1.5])
def test_a_learned_box_converts_to_overlay_coordinates(scale: float) -> None:
    box = Box(x=0.25, y=0.5, w=0.5, h=0.25)
    rect = fraction_box_to_dip_rect(box, 800, 400, CropRegion(100, 60, 800, 400), scale)
    assert rect.x == pytest.approx((100 + 200) / scale)
    assert rect.y == pytest.approx((60 + 200) / scale)
    assert rect.width == pytest.approx(400 / scale)
    assert rect.height == pytest.approx(100 / scale)
