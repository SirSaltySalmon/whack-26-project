"""Compiled readers: cheap local checks of a HUD region, built from specs the learner saved as data.

Nothing here knows any game. A reader is a region, a reading method and some rules, all stored in
the profile (see profile_schema.py). Readers never call a model, so they react in well under a
second. Anything they can't read stays with the slower vision observer.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np
from pydantic import ValidationError

from brain.perception.masking import box_pixels
from brain.perception.numbers import first_number, parse_fraction
from brain.perception.ocr import OcrLine
from brain.perception.profile_schema import (
    Box,
    ColorFillParams,
    LearnedFor,
    ReaderSpec,
    Region,
)

log = logging.getLogger(__name__)

Status = Literal["ok", "masked", "unreadable"]

# A column (or row) of a bar counts as filled when this share of its pixels match the colour. Bars
# often have borders, shading or text drawn over them, so it can't require every pixel.
FILLED_SHARE = 0.3
MAX_TEXT_CHARS = 120
FRACTION_TYPES = ("color_fill", "ocr_fraction")


@dataclass(frozen=True)
class Reading:
    reader: str
    status: Status
    # color_fill and ocr_fraction: 0-1. ocr_number: the number. ocr_text: the text.
    value: float | str | None = None
    display: str | None = None  # For live state, such as "72/100" or "62%"


def crop_box(image: np.ndarray, box: Box) -> np.ndarray:
    height, width = image.shape[:2]
    left, top, right, bottom = box_pixels(box, width, height)
    return image[top:bottom, left:right]


def _colour_mask(hsv: np.ndarray, params: ColorFillParams) -> np.ndarray:
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    low, high = params.hsv_low, params.hsv_high
    # A low hue above the high hue is a range that wraps past 0, which is where reds sit.
    if low[0] <= high[0]:
        hue_ok = (hue >= low[0]) & (hue <= high[0])
    else:
        hue_ok = (hue >= low[0]) | (hue <= high[0])
    return (
        hue_ok
        & (saturation >= low[1])
        & (saturation <= high[1])
        & (value >= low[2])
        & (value <= high[2])
    )


class ColorFillReader:
    """How full a bar is, from how many of its box's columns (rows on axis y) show its colour.

    Counted against how many show it when the bar is full (`full_at`), so it doesn't depend on
    which way the bar drains, padding inside a loose box, a fixed end cap, or the gaps in a row
    of icons such as hearts. Measuring the furthest coloured column got all four wrong.
    """

    uses_ocr = False

    def __init__(self, spec: ReaderSpec) -> None:
        assert spec.color is not None  # The schema guarantees it for color_fill
        self.spec = spec
        self._params = spec.color

    def read(self, crop: np.ndarray) -> Reading:
        share = colour_share(crop, self._params)
        # No colour at all might mean empty, or a bar that's gone or changed colour. Those can't be
        # told apart, so it isn't read as 0: a false "health low" is worse than not knowing.
        if share is None:
            return Reading(self.spec.name, "unreadable")
        fraction = round(min(1.0, share / self._params.full_at), 3)
        return Reading(self.spec.name, "ok", fraction, f"{round(fraction * 100)}%")


def colour_share(crop: np.ndarray, params: ColorFillParams) -> float | None:
    """The share of the box's lines, 0-1, that show the colour, before any full_at scaling."""
    if crop.size == 0:
        return None
    matches = _colour_mask(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV), params)
    lines = matches.mean(axis=0 if params.axis == "x" else 1)
    filled = int(np.count_nonzero(lines >= FILLED_SHARE))
    return filled / len(lines) if filled else None


class OcrReader:
    """Reads text in a region. The engine runs OCR in its worker; parsing here stays pure."""

    uses_ocr = True

    def __init__(self, spec: ReaderSpec) -> None:
        assert spec.ocr is not None  # The schema guarantees it for ocr_*
        self.spec = spec
        self._params = spec.ocr
        # Numbers sit on one line, so recognition alone is enough and about 50 times faster.
        self.detect = spec.type == "ocr_text"

    def prepare(self, crop: np.ndarray) -> np.ndarray:
        """Enlarges by a whole number with nearest-neighbour, which keeps pixel fonts crisp."""
        if self._params.upscale <= 1 or crop.size == 0:
            return crop
        factor = self._params.upscale
        return cv2.resize(crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_NEAREST)

    def parse(self, lines: list[OcrLine]) -> Reading:
        text = " ".join(t.strip() for t, score in lines if score >= self._params.min_score).strip()
        name = self.spec.name
        if not text:
            return Reading(name, "unreadable")
        if self.spec.type == "ocr_fraction":
            numbers = parse_fraction(text)
            if numbers is None:
                return Reading(name, "unreadable")
            current, maximum = numbers
            return Reading(name, "ok", round(current / maximum, 3), f"{current}/{maximum}")
        if self.spec.type == "ocr_number":
            number = first_number(text)
            if number is None:
                return Reading(name, "unreadable")
            shown = str(int(number)) if number.is_integer() else str(number)
            return Reading(name, "ok", number, shown)
        clipped = text[:MAX_TEXT_CHARS]
        return Reading(name, "ok", clipped, clipped)


CompiledReader = ColorFillReader | OcrReader


def compile_reader(spec: ReaderSpec) -> CompiledReader:
    return ColorFillReader(spec) if spec.type == "color_fill" else OcrReader(spec)


@dataclass(frozen=True)
class PlacedReader:
    reader: CompiledReader
    box: Box

    @property
    def spec(self) -> ReaderSpec:
        return self.reader.spec


def _valid(model: type[Any], raw: Any, what: str) -> Any | None:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        # Profiles come from a vision model, so one bad entry is expected now and then.
        log.warning("Skipping a bad %s in the profile: %s", what, exc.errors()[:1])
        return None


def compile_profile(data: Mapping[str, Any]) -> list[PlacedReader]:
    """Skips and logs any entry that fails to validate. One bad entry can't stop the others."""
    regions: dict[str, Region] = {}
    for raw in data.get("regions") or []:
        region = _valid(Region, raw, "region")
        if region is not None:
            regions[region.name] = region
    placed: list[PlacedReader] = []
    names: set[str] = set()
    for raw in data.get("readers") or []:
        spec = _valid(ReaderSpec, raw, "reader")
        if spec is None:
            continue
        region = regions.get(spec.region)
        if region is None or spec.name in names:
            log.warning("Skipping reader %s: unknown region or a duplicate name", spec.name)
            continue
        names.add(spec.name)
        placed.append(PlacedReader(compile_reader(spec), region.box))
    return placed


def learned_size(data: Mapping[str, Any]) -> LearnedFor | None:
    raw = data.get("learned_for")
    return None if raw is None else _valid(LearnedFor, raw, "learned_for")
