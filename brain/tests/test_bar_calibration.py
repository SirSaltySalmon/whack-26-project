"""Bars in boxes looser than the bar: vision's boxes rarely end exactly where a full bar does."""

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
    # Vision says full, but the colour covers a quarter of the box: more likely something else.
    samples = [Sample(bar(0.25), 1.0), Sample(bar(0.25), 1.0)]
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
