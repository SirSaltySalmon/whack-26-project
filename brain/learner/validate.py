"""Checks a learned reader against what vision saw, before it's trusted to raise events.

A rejected reader isn't a failure: the observer keeps covering that value, just more slowly. This
must never be loosened so a reader passes, and never gain handling for a particular game.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from brain.perception.numbers import first_number, parse_fraction
from brain.perception.ocr import OcrWorker
from brain.perception.profile_schema import ColorFillParams
from brain.perception.readers import CompiledReader, OcrReader, Reading, colour_share

MIN_SAMPLES_AGREEING = 2
FRACTION_TOLERANCE = 0.15
# Saturated, bright pixels are the bar. Greys, black and white are backgrounds and borders.
MIN_SATURATION = 90
MIN_VALUE = 70
MIN_COLOURED_SHARE = 0.05
HUE_TOLERANCE = 10
# OpenCV hue ranges (0-179) for the colour names vision gives a bar's fill. Names are loose, so
# neighbours overlap: Haiku called Terraria's light blue mana star "cyan". Red stays tight,
# because gold frames sit just past it.
FILL_HUES: dict[str, tuple[int, int]] = {
    "red": (165, 9),
    "orange": (8, 24),
    "yellow": (18, 36),
    "green": (35, 84),
    "cyan": (80, 130),
    "blue": (80, 135),
    "purple": (125, 158),
    "pink": (140, 172),
}
# Calibration only uses samples at least this full: near empty, one column either way would
# swing where "full" lands.
CALIBRATE_FROM = 0.2
# A full bar whose colour covers less of its box than this is more likely something else in the
# box, so it isn't calibrated and validation decides. Icons such as hearts leave gaps, and
# vision's boxes are loose, so a real bar can cover well under half.
MIN_FULL_AT = 0.1


@dataclass(frozen=True)
class Sample:
    crop: np.ndarray  # BGR crop for this region
    expected: float | str | None  # What vision said: fraction_seen or text_seen


def propose_color(crop: np.ndarray, fill: str | None = None) -> ColorFillParams | None:
    """The bar's hue: the strongest saturated hue within `fill`'s range if named, else overall.

    Without a name the frame or background often wins: Terraria's gold heart frames and a green
    background behind its blue mana star both outnumbered the fill in a live test.
    """
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    coloured = (hsv[..., 1] >= MIN_SATURATION) & (hsv[..., 2] >= MIN_VALUE)
    if coloured.mean() < MIN_COLOURED_SHARE:
        return None
    hues = hsv[..., 0][coloured]
    histogram = np.bincount(hues, minlength=180).astype(float)
    allowed = np.ones(180, dtype=bool)
    if fill in FILL_HUES:
        allowed = _hue_range(*FILL_HUES[fill])
        if histogram[allowed].sum() == 0:
            # Vision named a colour the crop doesn't have, so the box or the name is wrong.
            return None
        histogram = np.where(allowed, histogram, 0.0)
    # Smoothed around the circle, because red sits on both sides of 0.
    window = np.ones(2 * 3 + 1)
    padded = np.concatenate([histogram[-3:], histogram, histogram[:3]])
    peak = int(np.argmax(np.convolve(padded, window, mode="valid")))
    # The reader's hues: near the peak, and inside the named colour. Without the second part a
    # red peak at 9 reached orange at 16 and counted a fixed orange border as health.
    window_hues = _hue_range((peak - HUE_TOLERANCE) % 180, (peak + HUE_TOLERANCE) % 180) & allowed
    low_h, high_h = _bounds(window_hues, peak)
    keep = window_hues[hues]
    matching = hsv[coloured][keep]
    low_s = max(40, int(np.percentile(matching[:, 1], 5)) - 20)
    low_v = max(40, int(np.percentile(matching[:, 2], 5)) - 20)
    height, width = crop.shape[:2]
    return ColorFillParams(
        hsv_low=(low_h, low_s, low_v),
        hsv_high=(high_h, 255, 255),
        axis="x" if width >= height else "y",
    )


def fit_color(samples: Sequence[Sample], fills: Sequence[str]) -> ColorFillParams | None:
    """A bar's colour from its fullest sample, in the fill vision named most, calibrated."""
    if not samples:
        return None
    fullest = max(samples, key=lambda s: s.expected if isinstance(s.expected, float) else 0)
    fill = Counter(fills).most_common(1)[0][0] if fills else None
    color = propose_color(fullest.crop, fill)
    return calibrate(color, samples) if color is not None else None


def _hue_range(low: int, high: int) -> np.ndarray:
    """Which of the 180 hues fall in [low, high]. A low above high wraps past 0, as red does."""
    hue = np.arange(180)
    return (hue >= low) & (hue <= high) if low <= high else (hue >= low) | (hue <= high)


def _bounds(hues: np.ndarray, peak: int) -> tuple[int, int]:
    """The ends of the unbroken run of allowed hues around the peak, going round the circle."""
    low = high = peak
    while hues[(low - 1) % 180] and (low - 1) % 180 != peak:
        low = (low - 1) % 180
    while hues[(high + 1) % 180] and (high + 1) % 180 != peak:
        high = (high + 1) % 180
    return low, high


def calibrate(color: ColorFillParams, samples: Sequence[Sample]) -> ColorFillParams:
    """Sets how much of the box a full bar colours, from how full vision said each sample was.

    Each sample gives share / expected, and the median is used. validate() then still checks
    every sample against vision. When every sample was at the same level, that only shows the
    reader is consistent, not that it follows changes: the live low-health check covers that.
    """
    estimates = []
    for sample in samples:
        if not isinstance(sample.expected, float) or sample.expected < CALIBRATE_FROM:
            continue
        share = colour_share(sample.crop, color)
        if share is not None:
            estimates.append(share / sample.expected)
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

    Numbers agree within 0.15, text exactly after trimming. A bar also needs a sample at least
    CALIBRATE_FROM full: near-empty samples agree with almost any scale, so they prove nothing.
    Returns the reason for the log, with every sample's reading so a rejection can be diagnosed.
    """
    if reader.spec.type == "color_fill" and not any(
        isinstance(s.expected, float) and s.expected >= CALIBRATE_FROM for s in samples
    ):
        return False, f"no sample was at least {CALIBRATE_FROM:.0%} full, so its scale is unknown"
    agreeing = 0
    seen: list[str] = []
    wrong: str | None = None
    for sample in samples:
        if sample.expected is None:
            seen.append("no label")
            continue
        reading = await _read(reader, sample.crop, ocr)
        if reading.status != "ok":
            seen.append(reading.status)
            continue
        seen.append(f"{reading.display} vs {sample.expected!r}")
        if not _agrees(reader, reading, sample.expected):
            wrong = wrong or f"read {reading.display!r} where vision saw {sample.expected!r}"
        else:
            agreeing += 1
    readings = f" (samples: {'; '.join(seen)})"
    if wrong:
        return False, wrong + readings
    if agreeing < MIN_SAMPLES_AGREEING:
        return False, f"only {agreeing} of {len(samples)} samples could be checked" + readings
    return True, f"{agreeing} samples agreed with vision" + readings
