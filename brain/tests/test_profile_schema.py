import json
import math
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from brain.memory.db import connect
from brain.memory.profile import ProfileStore
from brain.perception.profile_schema import (
    Box,
    ColorFillParams,
    EventRule,
    LearnedFor,
    OcrParams,
    ReaderSpec,
    Region,
    SceneRef,
)

GAME = "Some game"
RED = ColorFillParams(hsv_low=(170, 100, 100), hsv_high=(10, 255, 255))


def bar_reader() -> ReaderSpec:
    return ReaderSpec(
        name="health",
        region="health",
        type="color_fill",
        color=ColorFillParams(
            hsv_low=(50, 80, 80), hsv_high=(70, 255, 255), axis="y", reverse=True
        ),
        rules=[EventRule(when="below", value=0.25, clear_at=0.4, event="health_low")],
        live_key="health",
    )


def text_reader() -> ReaderSpec:
    return ReaderSpec(
        name="objective",
        region="objective",
        type="ocr_text",
        ocr=OcrParams(upscale=4, min_score=0.7),
        rules=[EventRule(when="changed", event="objective_changed", confirm_reads=3)],
        interval_s=1.0,
    )


def region() -> Region:
    return Region(name="health", kind="bar", box=Box(x=0.1, y=0.2, w=0.3, h=0.05), confidence=2 / 3)


EVERY_MODEL: list[Callable[[], BaseModel]] = [
    lambda: Box(x=0.1, y=0.2, w=0.3, h=0.05),
    region,
    lambda: RED,
    lambda: OcrParams(),
    lambda: EventRule(when="above", value=0.0, clear_at=0.0, event="boss_visible"),
    bar_reader,
    text_reader,
    lambda: SceneRef(label="menu", region="stable_ui", phash="ff00aa5511223344"),
    lambda: LearnedFor(width=1920, height=1080),
]


@pytest.mark.parametrize(
    ("x", "y", "w", "h"),
    [(0, 0, 1, 1), (0.7, 0, 0.3, 0.1), (0, 0.7, 0.1, 0.3), (0.999, 0.999, 0.001, 0.001)],
)
def test_boxes_inside_the_frame_are_accepted(x: float, y: float, w: float, h: float) -> None:
    assert Box(x=x, y=y, w=w, h=h).x == x


def test_rounding_alone_cant_push_a_box_off_the_frame() -> None:
    # One floating point step above 0.6 and 0.4, as averaging a few boxes can land.
    start, size = math.nextafter(0.6, 1), math.nextafter(0.4, 1)
    assert start + size > 1  # The premise: this does pass 1, purely from rounding.
    assert Box(x=start, y=0, w=size, h=0.1).w == size
    assert Box(x=0, y=start, w=0.1, h=size).h == size


@pytest.mark.parametrize(
    ("x", "y", "w", "h"),
    [
        (0.9, 0, 0.2, 0.1),  # Past the right edge
        (0, 0.9, 0.1, 0.2),  # Past the bottom edge
        (0.7, 0, 0.30001, 0.1),  # Only just past it, but more than rounding could do
        (-0.1, 0, 0.2, 0.1),
        (0, -0.1, 0.2, 0.1),
        (1.1, 0, 0.1, 0.1),
        (0, 1.1, 0.1, 0.1),
        (0, 0, 0, 0.1),  # No area
        (0, 0, 0.1, 0),
        (0, 0, -0.1, 0.1),
        (0, 0, 1.1, 0.1),
        (0, 0, 0.1, 1.1),
    ],
)
def test_boxes_a_reader_couldnt_crop_are_rejected(x: float, y: float, w: float, h: float) -> None:
    with pytest.raises(ValidationError):
        Box(x=x, y=y, w=w, h=h)


@pytest.mark.parametrize(
    "changes", [{"kind": "icon"}, {"confidence": 1.1}, {"confidence": -0.1}, {"box": {"x": 2}}]
)
def test_regions_with_bad_fields_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Region.model_validate({**region().model_dump(), **changes})


def test_color_fill_defaults_to_filling_left_to_right() -> None:
    params = ColorFillParams(hsv_low=(0, 0, 0), hsv_high=(179, 255, 255))
    assert params.axis == "x" and params.reverse is False


def test_a_hue_range_may_wrap_around_zero_for_reds() -> None:
    assert RED.hsv_low[0] > RED.hsv_high[0]


@pytest.mark.parametrize(
    ("low", "high"),
    [
        ((180, 0, 0), (179, 255, 255)),  # OpenCV's hue stops at 179
        ((0, 0, 0), (180, 255, 255)),
        ((0, 256, 0), (179, 255, 255)),
        ((0, 0, 256), (179, 255, 255)),
        ((0, 0, 0), (179, 256, 255)),
        ((0, 0, 0), (179, 255, 256)),
        ((-1, 0, 0), (179, 255, 255)),
        ((0, -1, 0), (179, 255, 255)),
        ((0, 0, -1), (179, 255, 255)),
    ],
)
def test_hsv_outside_opencvs_range_is_rejected(
    low: tuple[int, int, int], high: tuple[int, int, int]
) -> None:
    with pytest.raises(ValidationError):
        ColorFillParams(hsv_low=low, hsv_high=high)


@pytest.mark.parametrize(
    ("low", "high"),
    [
        ((0, 200, 0), (179, 100, 255)),  # Saturation doesn't wrap
        ((0, 0, 200), (179, 255, 100)),  # Nor does value
    ],
)
def test_saturation_and_value_ranges_cant_wrap(
    low: tuple[int, int, int], high: tuple[int, int, int]
) -> None:
    with pytest.raises(ValidationError):
        ColorFillParams(hsv_low=low, hsv_high=high)


@pytest.mark.parametrize("hsv", [[0, 0], [0, 0, 0, 0]])
def test_hsv_needs_exactly_three_values(hsv: list[int]) -> None:
    with pytest.raises(ValidationError):
        ColorFillParams.model_validate({"hsv_low": hsv, "hsv_high": [179, 255, 255]})


def test_ocr_defaults_suit_pixel_fonts() -> None:
    assert OcrParams() == OcrParams(upscale=3, min_score=0.6)


@pytest.mark.parametrize(
    "fields", [{"upscale": 0}, {"upscale": 1.5}, {"min_score": 1.1}, {"min_score": -0.1}]
)
def test_bad_ocr_params_are_rejected(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        OcrParams.model_validate(fields)


@pytest.mark.parametrize("when", ["below", "above"])
def test_threshold_rules_need_a_value(when: str) -> None:
    with pytest.raises(ValidationError):
        EventRule.model_validate({"when": when, "event": "something"})


def test_a_threshold_of_zero_counts_as_a_value() -> None:
    rule = EventRule(when="above", value=0.0, clear_at=0.0, event="boss_visible")
    assert rule.value == 0.0 and rule.clear_at == 0.0


def test_a_changed_rule_needs_no_value() -> None:
    assert EventRule(when="changed", event="objective_changed").value is None


def test_rules_need_two_reads_by_default() -> None:
    assert EventRule(when="changed", event="something").confirm_reads == 2


@pytest.mark.parametrize(
    "fields",
    [
        {"when": "changed", "event": "something", "confirm_reads": 0},
        {"when": "sometimes", "event": "something"},
        {"when": "changed"},
    ],
)
def test_bad_rules_are_rejected(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EventRule.model_validate(fields)


def test_a_color_fill_reader_needs_its_colour() -> None:
    with pytest.raises(ValidationError, match="color"):
        ReaderSpec(name="health", region="health", type="color_fill", ocr=OcrParams())


@pytest.mark.parametrize("kind", ["ocr_fraction", "ocr_number", "ocr_text"])
def test_an_ocr_reader_needs_its_params(kind: str) -> None:
    with pytest.raises(ValidationError, match="ocr"):
        ReaderSpec.model_validate({"name": "ammo", "region": "ammo", "type": kind, "color": RED})
    spec = ReaderSpec.model_validate(
        {"name": "ammo", "region": "ammo", "type": kind, "ocr": OcrParams()}
    )
    assert spec.ocr == OcrParams()


def test_an_unknown_reader_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ReaderSpec.model_validate({"name": "a", "region": "a", "type": "guess", "ocr": {}})


def test_reader_defaults() -> None:
    spec = ReaderSpec(name="health", region="health", type="color_fill", color=RED)
    assert spec.rules == [] and spec.live_key is None and spec.interval_s == 0.2


def test_readers_dont_share_their_default_rules() -> None:
    first = ReaderSpec(name="a", region="a", type="color_fill", color=RED)
    second = ReaderSpec(name="b", region="b", type="color_fill", color=RED)
    first.rules.append(EventRule(when="changed", event="something"))
    assert second.rules == []


@pytest.mark.parametrize("interval", [0, -1])
def test_a_reader_has_to_run_on_some_interval(interval: float) -> None:
    with pytest.raises(ValidationError):
        ReaderSpec(name="a", region="a", type="color_fill", color=RED, interval_s=interval)


@pytest.mark.parametrize("size", [(0, 1080), (1920, 0), (-1, 1080)])
def test_learned_for_needs_a_real_frame_size(size: tuple[int, int]) -> None:
    with pytest.raises(ValidationError):
        LearnedFor(width=size[0], height=size[1])


@pytest.mark.parametrize("build", EVERY_MODEL)
def test_every_model_survives_a_trip_through_json(build: Callable[[], BaseModel]) -> None:
    # merge_data stores plain JSON, which turns tuples into lists.
    model = build()
    stored = json.loads(json.dumps(model.model_dump(mode="json")))
    assert type(model).model_validate(stored) == model


def test_a_whole_profile_survives_the_real_store() -> None:
    conn = connect(":memory:")
    store = ProfileStore(conn)
    scene = SceneRef(label="menu", region="stable_ui", phash="ff00aa5511223344")
    learned = LearnedFor(width=1920, height=1080)
    store.merge_data(
        GAME,
        {
            "regions": [region().model_dump(mode="json")],
            "readers": [
                bar_reader().model_dump(mode="json"),
                text_reader().model_dump(mode="json"),
            ],
            "scenes": [scene.model_dump(mode="json")],
            "learned_for": learned.model_dump(mode="json"),
        },
    )
    data = store.get(GAME).data
    assert [Region.model_validate(item) for item in data["regions"]] == [region()]
    readers = [ReaderSpec.model_validate(item) for item in data["readers"]]
    assert readers == [bar_reader(), text_reader()]
    assert [SceneRef.model_validate(item) for item in data["scenes"]] == [scene]
    assert LearnedFor.model_validate(data["learned_for"]) == learned
    conn.close()


def test_writing_new_readers_leaves_the_regions_alone() -> None:
    conn = connect(":memory:")
    store = ProfileStore(conn)
    regions = [region().model_dump(mode="json")]
    store.merge_data(GAME, {"regions": regions, "readers": []})
    store.merge_data(GAME, {"readers": [text_reader().model_dump(mode="json")]})
    data = store.get(GAME).data
    assert data["regions"] == regions and len(data["readers"]) == 1
    conn.close()
