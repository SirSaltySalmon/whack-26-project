"""Bars in boxes looser than the bar: vision's boxes rarely end exactly where a full bar does."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from brain.learner.validate import Sample, calibrate, propose_color, validate
from brain.perception.profile_schema import ColorFillParams, ReaderSpec
from brain.perception.readers import CompiledReader, compile_reader
from brain.tests.reader_fixtures import RED_RANGE, bar

# A full bar reaches 78% of the way along its box, as Terraria's hearts did in a live test.
FULL_AT = 0.78


def loose(fraction: float) -> Sample:
    """A bar `fraction` full, in a box whose last 22% the bar never reaches."""
    return Sample(bar(fraction * FULL_AT), fraction)


def reader(color: ColorFillParams) -> CompiledReader:
    spec = ReaderSpec(name="health", region="health", type="color_fill", color=color)
    return compile_reader(spec)


def red() -> ColorFillParams:
    return ColorFillParams.model_validate(RED_RANGE)


async def test_a_loose_box_without_calibration_is_rejected() -> None:
    samples = [loose(1.0), loose(1.0), loose(1.0)]
    accepted, why = await validate(reader(red()), samples, None)
    assert not accepted
    assert "78%" in why


async def test_calibration_finds_where_full_ends_and_the_reader_passes() -> None:
    samples = [loose(1.0), loose(1.0), loose(1.0)]
    color = calibrate(red(), samples)
    assert color.full_at == pytest.approx(FULL_AT, abs=0.01)
    accepted, _ = await validate(reader(color), samples, None)
    assert accepted


async def test_a_calibrated_reader_follows_damage() -> None:
    color = calibrate(red(), [loose(1.0), loose(1.0)])
    reading = reader(color).read(loose(0.5).crop)
    assert reading.value == pytest.approx(0.5, abs=0.02)
    assert reading.display == "50%"


def test_partly_full_samples_calibrate_too() -> None:
    color = calibrate(red(), [loose(0.6), loose(0.5)])
    assert color.full_at == pytest.approx(FULL_AT, abs=0.02)


def test_near_empty_samples_are_left_out() -> None:
    # 10% full is too little to say where full ends, so nothing is calibrated.
    assert calibrate(red(), [loose(0.1)]).full_at == 1.0


async def test_colour_covering_too_little_of_the_box_isnt_calibrated() -> None:
    # Vision says full, but the colour covers 5% of the box: more likely something else.
    samples = [Sample(bar(0.05), 1.0), Sample(bar(0.05), 1.0)]
    color = calibrate(red(), samples)
    assert color.full_at == 1.0
    accepted, _ = await validate(reader(color), samples, None)
    assert not accepted


def test_a_reading_past_full_is_capped() -> None:
    color = red().model_copy(update={"full_at": 0.5})
    assert reader(color).read(bar(0.9)).value == 1.0


def test_profiles_saved_before_calibration_read_the_same() -> None:
    assert red().full_at == 1.0
    assert reader(red()).read(bar(0.6)).value == pytest.approx(0.6, abs=0.01)


def test_proposed_colour_starts_uncalibrated() -> None:
    color = propose_color(bar(1.0))
    assert color is not None and color.full_at == 1.0


# Astra's review: a 100 x 10 black crop with whole columns painted red, calibrated on two full
# samples. Each of these read wrongly when the reader measured the furthest red column.


def columns(*spans: tuple[int, int]) -> np.ndarray:
    crop = np.zeros((10, 100, 3), dtype=np.uint8)
    for start, end in spans:
        crop[:, start:end] = (0, 0, 255)
    return crop


async def calibrated_on(full: np.ndarray) -> CompiledReader:
    samples = [Sample(full, 1.0), Sample(full.copy(), 1.0)]
    color = calibrate(red(), samples)
    built = reader(color)
    accepted, why = await validate(built, samples, None)
    assert accepted, why
    return built


async def test_padding_before_the_bar_doesnt_inflate_a_low_reading() -> None:
    built = await calibrated_on(columns((20, 80)))
    assert built.read(columns((20, 26))).value == pytest.approx(0.1, abs=0.01)


async def test_a_bar_that_drains_from_the_other_end_reads_low() -> None:
    built = await calibrated_on(columns((0, 100)))
    assert built.read(columns((90, 100))).value == pytest.approx(0.1, abs=0.01)


async def test_a_fixed_end_cap_doesnt_hide_damage() -> None:
    built = await calibrated_on(columns((0, 100)))
    # 10 of 99 fillable columns, plus the permanent cap: reads 11%, close to the true 10%.
    assert built.read(columns((0, 10), (99, 100))).value == pytest.approx(0.1, abs=0.02)


# Astra's second round.


async def test_losing_a_whole_row_of_icons_halves_the_reading() -> None:
    def icons(count: int) -> np.ndarray:
        crop = np.zeros((20, 100, 3), dtype=np.uint8)
        for i in range(count):
            x, y = 20 * (i % 5), 12 * (i // 5)
            crop[y : y + 8, x : x + 16] = (0, 0, 255)
        return crop

    built = await calibrated_on(icons(10))
    assert built.read(icons(5)).value == pytest.approx(0.5, abs=0.02)


async def test_only_near_empty_samples_cant_vouch_for_a_bar() -> None:
    samples = [Sample(columns((0, 4)), 0.08), Sample(columns((0, 8)), 0.16)]
    accepted, why = await validate(reader(calibrate(red(), samples)), samples, None)
    assert not accepted
    assert "scale is unknown" in why


async def test_a_rejection_lists_every_samples_reading() -> None:
    samples = [Sample(columns((0, 100)), 1.0), Sample(columns((0, 50)), 1.0)]
    accepted, why = await validate(reader(red()), samples, None)
    assert not accepted
    assert "100% vs 1.0" in why and "50% vs 1.0" in why


def test_debug_samples_are_saved_with_what_vision_said(tmp_path: Path) -> None:
    from brain.learner.debug_samples import save_samples

    samples = [Sample(columns((0, 100)), 1.0), Sample(columns((0, 50)), 1.0)]
    save_samples(tmp_path / "learner", "health", samples, False, "read '50%'")
    saved = sorted(path.name for path in (tmp_path / "learner").iterdir())
    assert saved == ["health-0.png", "health-1.png", "health.json"]
    assert (
        '"expected": [\n    1.0,\n    1.0\n  ]'
        in (tmp_path / "learner" / "health.json").read_text()
    )


def test_a_named_fill_beats_a_more_colourful_frame_and_background() -> None:
    # Like Terraria's hearts: a red fill inside a wider gold frame, on a green background.
    crop = np.full((30, 100, 3), (40, 140, 40), dtype=np.uint8)  # Green background
    crop[2:28, 2:98] = (30, 180, 220)  # Gold frame, the most common colour
    crop[10:20, 10:40] = (0, 0, 255)  # The red fill
    assert propose_color(crop) is not None
    assert propose_color(crop).hsv_low[0] not in range(170, 180)  # Unnamed, the frame wins
    named = propose_color(crop, "red")
    assert named is not None and named.hsv_low[0] >= 160  # A range around red, wrapping past 0
    built = reader(calibrate(named, [Sample(crop, 1.0)]))
    half = crop.copy()
    half[10:20, 25:40] = (30, 180, 220)  # Half the red gone, frame showing instead
    assert built.read(half).value == pytest.approx(0.5, abs=0.05)


def test_a_named_fill_the_crop_lacks_proposes_nothing() -> None:
    assert propose_color(bar(1.0), "blue") is None


def test_a_light_blue_fill_called_cyan_still_matches() -> None:
    crop = np.full((30, 30, 3), (40, 140, 40), dtype=np.uint8)  # Green background
    crop[8:22, 8:22] = (255, 120, 90)  # Light blue, OpenCV hue about 107
    color = propose_color(crop, "cyan")
    assert color is not None and color.hsv_low[0] <= 107 <= color.hsv_high[0]


# Astra's third round.


def test_a_red_range_never_spills_into_an_orange_border() -> None:
    def crop(red_columns: int) -> np.ndarray:
        hsv = np.zeros((10, 100, 3), dtype=np.uint8)
        hsv[:, :20] = (15, 255, 255)  # A fixed orange border
        hsv[:, 20 : 20 + red_columns] = (9, 255, 255)  # The red fill
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    color = propose_color(crop(30), "red")
    assert color is not None
    low, high = color.hsv_low[0], color.hsv_high[0]
    assert not (low <= 15 <= high) and (low > high or high <= 9)  # Orange's 15 is left out
    built = reader(calibrate(color, [Sample(crop(30), 1.0), Sample(crop(24), 0.8)]))
    # 3 of 30 columns left is 10%, low enough for the health_low alert at 25%.
    assert built.read(crop(3)).value == pytest.approx(0.1, abs=0.02)
