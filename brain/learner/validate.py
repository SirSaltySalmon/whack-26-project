"""Checks a learned reader against what vision saw, before it's trusted to raise events.

A rejected reader isn't a failure: the observer keeps covering that value, just more slowly. This
must never be loosened so a reader passes, and never gain handling for a particular game.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from brain.perception.numbers import first_number, parse_fraction
from brain.perception.ocr import OcrWorker
from brain.perception.profile_schema import ColorFillParams
from brain.perception.readers import CompiledReader, OcrReader, Reading, colour_reach

MIN_SAMPLES_AGREEING = 2
FRACTION_TOLERANCE = 0.15
# Saturated, bright pixels are the bar. Greys, black and white are backgrounds and borders.
MIN_SATURATION = 90
MIN_VALUE = 70
MIN_COLOURED_SHARE = 0.05
HUE_TOLERANCE = 10
# Calibration only uses samples at least this full: near empty, one column either way would
# swing where "full" lands.
CALIBRATE_FROM = 0.2
# A full bar whose colour covers less of its box than this is more likely something else in the
# box, so it isn't calibrated and validation decides.
MIN_FULL_AT = 0.4


@dataclass(frozen=True)
class Sample:
    crop: np.ndarray  # BGR crop for this region
    expected: float | str | None  # What vision said: fraction_seen or text_seen


def propose_color(crop: np.ndarray) -> ColorFillParams | None:
    """The dominant saturated hue in a bar crop. None if nothing stands out."""
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    coloured = (hsv[..., 1] >= MIN_SATURATION) & (hsv[..., 2] >= MIN_VALUE)
    if coloured.mean() < MIN_COLOURED_SHARE:
        return None
    hues = hsv[..., 0][coloured]
    histogram = np.bincount(hues, minlength=180).astype(float)
    # Smoothed around the circle, because red sits on both sides of 0.
    window = np.ones(2 * 3 + 1)
    padded = np.concatenate([histogram[-3:], histogram, histogram[:3]])
    peak = int(np.argmax(np.convolve(padded, window, mode="valid")))
    near = np.minimum(np.abs(hues.astype(int) - peak), 180 - np.abs(hues.astype(int) - peak))
    matching = hsv[coloured][near <= HUE_TOLERANCE]
    low_s = max(40, int(np.percentile(matching[:, 1], 5)) - 20)
    low_v = max(40, int(np.percentile(matching[:, 2], 5)) - 20)
    height, width = crop.shape[:2]
    return ColorFillParams(
        hsv_low=((peak - HUE_TOLERANCE) % 180, low_s, low_v),
        hsv_high=((peak + HUE_TOLERANCE) % 180, 255, 255),
        axis="x" if width >= height else "y",
    )


def calibrate(color: ColorFillParams, samples: Sequence[Sample]) -> ColorFillParams:
    """Sets where "full" ends inside the box, from how full vision said each sample was.

    Each sample gives reach / expected, and the median is used. validate() then still checks
    every sample against vision. When every sample was at the same level, that only shows the
    reader is consistent, not that it follows changes: the live low-health check covers that.
    """
    estimates = []
    for sample in samples:
        if not isinstance(sample.expected, float) or sample.expected < CALIBRATE_FROM:
            continue
        reach = colour_reach(sample.crop, color)
        if reach is not None:
            estimates.append(reach / sample.expected)
    if not estimates:
        return color
    full_at = min(1.0, float(np.median(estimates)))
    if full_at < MIN_FULL_AT:
        return color
    return color.model_copy(update={"full_at": round(full_at, 3)})


async def _read(reader: CompiledReader, crop: np.ndarray, ocr: OcrWorker | None) -> Reading:
    if isinstance(reader, OcrReader):
        if ocr is None:
            return Reading(reader.spec.name, "unreadable")
        return reader.parse(await ocr.read(reader.prepare(crop), reader.detect))
    return reader.read(crop)


def _agrees(reader: CompiledReader, reading: Reading, expected: float | str) -> bool:
    kind = reader.spec.type
    value = reading.value
    if kind in ("color_fill", "ocr_fraction"):
        if isinstance(expected, str):
            numbers = parse_fraction(expected)
            if numbers is None:
                return False
            expected = numbers[0] / numbers[1]
        return isinstance(value, float) and abs(value - expected) <= FRACTION_TOLERANCE
    if kind == "ocr_number":
        number = first_number(str(expected))
        return number is not None and value == number
    return str(value).strip().casefold() == str(expected).strip().casefold()


async def validate(
    reader: CompiledReader, samples: Sequence[Sample], ocr: OcrWorker | None
) -> tuple[bool, str]:
    """Accepts when at least 2 samples read ok and agree with vision, and none disagree.

    Numbers agree within 0.15, text exactly after trimming. Returns the reason, for the log.
    """
    agreeing = 0
    for sample in samples:
        if sample.expected is None:
            continue
        reading = await _read(reader, sample.crop, ocr)
        if reading.status != "ok":
            continue
        if not _agrees(reader, reading, sample.expected):
            return False, f"read {reading.display!r} where vision saw {sample.expected!r}"
        agreeing += 1
    if agreeing < MIN_SAMPLES_AGREEING:
        return False, f"only {agreeing} of {len(samples)} samples could be checked"
    return True, f"{agreeing} samples agreed with vision"
