"""The contract between the learner, which writes these, and the readers, which read them.

Stored in `profile.data` under the top-level keys `regions`, `readers`, `scenes` and `learned_for`,
so `ProfileStore.merge_data` can update each one alone. Everything here comes from a vision model
and is checked on the way in, so a nonsense value is rejected rather than read from later.
"""

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

# Averaged boxes can land a hair past the frame's edge from floating point alone.
_EDGE_TOLERANCE = 1e-9
_MAX_HUE = 179
_MAX_CHANNEL = 255


class Box(BaseModel):
    """Fractions of the frame. Survives resolution changes, as CLAUDE.md requires."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _inside_the_frame(self) -> Self:
        if self.x + self.w > 1 + _EDGE_TOLERANCE or self.y + self.h > 1 + _EDGE_TOLERANCE:
            raise ValueError(f"Box runs outside the frame: {self}")
        return self


class Region(BaseModel):
    name: str  # "health", "boss_health", "objective"...
    kind: Literal["bar", "number", "text", "stable_ui"]
    box: Box
    confidence: float = Field(ge=0, le=1)  # The share of learning frames that agreed


class ColorFillParams(BaseModel):
    """OpenCV ranges: H 0-179, S and V 0-255.

    Hue wraps around, and reds sit on both sides of 0. So a low hue above the high hue means the
    range that crosses 0: H >= low or H <= high. S and V don't wrap.
    """

    hsv_low: tuple[int, int, int]
    hsv_high: tuple[int, int, int]
    axis: Literal["x", "y"] = "x"  # The direction the bar fills
    # Which end it fills from. Kept so saved profiles still load: readings no longer depend on it.
    reverse: bool = False
    # The share of the box's lines that show the colour when the bar is full. Vision's boxes are
    # often looser than the bar, and icons have gaps, so it's rarely 1. Learned from samples.
    full_at: float = Field(default=1.0, gt=0, le=1)

    @model_validator(mode="after")
    def _in_opencv_range(self) -> Self:
        for hue, saturation, value in (self.hsv_low, self.hsv_high):
            if not (
                0 <= hue <= _MAX_HUE
                and 0 <= saturation <= _MAX_CHANNEL
                and 0 <= value <= _MAX_CHANNEL
            ):
                raise ValueError(f"HSV outside OpenCV's range: {self}")
        if self.hsv_low[1] > self.hsv_high[1] or self.hsv_low[2] > self.hsv_high[2]:
            raise ValueError(f"Saturation and value ranges can't wrap: {self}")
        return self


class OcrParams(BaseModel):
    upscale: int = Field(default=3, ge=1)  # Whole number, nearest-neighbour, for pixel fonts
    min_score: float = Field(default=0.6, ge=0, le=1)  # Below this the read counts as unreadable


class EventRule(BaseModel):
    when: Literal["below", "above", "changed"]
    value: float | None = None  # For below and above
    clear_at: float | None = None  # Hysteresis: must pass this before firing again
    event: str  # The GameEvent name
    confirm_reads: int = Field(default=2, ge=1)  # Consecutive reads before it counts

    @model_validator(mode="after")
    def _threshold_is_set(self) -> Self:
        if self.when != "changed" and self.value is None:
            raise ValueError(f"A '{self.when}' rule needs a value: {self}")
        return self


class ReaderSpec(BaseModel):
    name: str  # Unique. Also the default live-state key
    region: str  # A Region.name
    type: Literal["color_fill", "ocr_fraction", "ocr_number", "ocr_text"]
    color: ColorFillParams | None = None  # Required for color_fill
    ocr: OcrParams | None = None  # Required for ocr_*
    rules: list[EventRule] = []
    live_key: str | None = None  # Defaults to name. None-valued reads stay out
    interval_s: float = Field(default=0.2, gt=0)  # OCR readers should use 0.5 or more

    @model_validator(mode="after")
    def _has_params_for_its_type(self) -> Self:
        if self.type == "color_fill" and self.color is None:
            raise ValueError(f"A color_fill reader needs color: {self.name}")
        if self.type != "color_fill" and self.ocr is None:
            raise ValueError(f"An {self.type} reader needs ocr: {self.name}")
        return self


class SceneRef(BaseModel):
    label: str  # An Observation.screen_type value
    region: str  # A stable_ui Region.name
    phash: str  # Hex, from str(imagehash.phash(pil_image))


class LearnedFor(BaseModel):
    width: int = Field(gt=0)  # Frame size in physical pixels when learned
    height: int = Field(gt=0)
