"""The debug view's sightings: what the observer noticed and what the tools looked at, as boxes.

Only sent with --debug-regions. Model boxes are untrusted, so a bad one is dropped, never raised.
"""

import asyncio
import time
from typing import Any

import pytest

from brain.agent.tools import TurnContext
from brain.events import EventBus
from brain.perception.coords import CropRegion
from brain.perception.focus import Focus, FocusIntervals
from brain.perception.observation import (
    OBSERVATION_PROMPT,
    Observation,
    SightedObservation,
)
from brain.perception.observer import DEBUG_MAX_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS, Observer
from brain.perception.sightings import NOTICED_TTL_MS, TOOL_TTL_MS, noticed, short
from brain.perception.tracker import ObservationTracker
from brain.tests.agent_rig import LOOK, POINT, rig
from brain.tests.fakes import FakeOverlay, FakeVision, VisionReply, make_buffer, make_frame
from shared.protocol.messages import DebugSightings, PointerFly, Rect

REPORT: dict[str, Any] = {
    "screen_type": "gameplay",
    "summary": "A fight.",
    "player_action": None,
    "health_visible": False,
    "health_raw": None,
    "health_percent": None,
    "danger_level": "low",
    "threats": ["a green slime"],
    "selected_item": None,
    "menu_title": None,
    "location": None,
    "on_screen_text": [],
    "notable": None,
    "unsure": [],
}
# A 1920 x 1080 window at (100, 50) goes out at 960 x 540, half size.
WINDOW = CropRegion(100, 50, 1920, 1080)


def assert_rect(rect: Rect, x: float, y: float, width: float, height: float) -> None:
    assert (rect.x, rect.y, rect.width, rect.height) == pytest.approx((x, y, width, height))


def sightings_sent(overlay: FakeOverlay) -> list[DebugSightings]:
    return [message for message in overlay.sent if isinstance(message, DebugSightings)]


async def observe(
    reply: VisionReply, *, debug: bool, scale: float = 1.0
) -> tuple[Observer, FakeOverlay, FakeVision]:
    overlay = FakeOverlay(display_scale=scale)
    vision = FakeVision(reply)
    frame = make_frame(1920, 1080, ts=time.monotonic(), region=WINDOW)
    observer = Observer(
        make_buffer(frame),
        overlay,
        vision,
        EventBus(),
        ObservationTracker(),
        Focus(FocusIntervals(1.3, 0.8, 0.6), 5.0),
        960,
        0,
        debug_send=overlay.send if debug else None,
    )
    observer._tick(time.monotonic())
    await asyncio.gather(*observer._tasks)
    return observer, overlay, vision


async def test_with_debug_on_the_observer_asks_for_boxes_and_draws_them_where_they_are() -> None:
    reply = {**REPORT, "sightings": [{"label": "green slime", "box_px": [96, 54, 192, 108]}]}
    observer, overlay, vision = await observe(reply, debug=True, scale=1.5)
    call = vision.calls[0]
    assert call.schema is SightedObservation and call.max_tokens == DEBUG_MAX_OUTPUT_TOKENS
    assert call.prompt.startswith(OBSERVATION_PROMPT) and "960 x 540 image" in call.prompt
    [message] = sightings_sent(overlay)
    [sighting] = message.sightings
    assert sighting.kind == "noticed" and sighting.label == "green slime"
    assert sighting.ttl_ms == NOTICED_TTL_MS
    # x 0.1-0.2 and y 0.1-0.2 of the window, in physical pixels, then divided by 1.5 for DIPs.
    assert_rect(sighting.rect, (100 + 192) / 1.5, (50 + 108) / 1.5, 192 / 1.5, 108 / 1.5)
    # The report still counts as usual.
    assert observer._last_applied_ts is not None


async def test_a_malformed_box_is_dropped_and_the_rest_of_the_report_kept() -> None:
    reply = {
        **REPORT,
        "sightings": [
            {"label": "too short", "box_px": [0, 0, 10]},
            {"label": "no area", "box_px": [50, 50, 50, 80]},
            {"label": "not numbers", "box_px": ["a", "b", "c", "d"]},
            {"label": "missing box"},
            "not even an object",
            {"label": "a bat", "box_px": [0, 0, 96, 54]},
        ],
    }
    observer, overlay, _ = await observe(reply, debug=True)
    [message] = sightings_sent(overlay)
    assert [sighting.label for sighting in message.sightings] == ["a bat"]
    assert observer._last_applied_ts is not None


async def test_sightings_that_arent_a_list_mean_none_rather_than_a_lost_report() -> None:
    observer, overlay, _ = await observe({**REPORT, "sightings": "lots"}, debug=True)
    assert sightings_sent(overlay) == []
    assert observer._last_applied_ts is not None


async def test_with_debug_off_the_prompt_is_unchanged_and_nothing_is_sent() -> None:
    reply = {**REPORT}
    _, overlay, vision = await observe(reply, debug=False)
    call = vision.calls[0]
    assert call.prompt == OBSERVATION_PROMPT and call.schema is Observation
    assert call.max_tokens == MAX_OUTPUT_TOKENS
    assert "sightings" not in Observation.model_json_schema()["properties"]
    assert overlay.sent == []


def test_noticed_clips_a_box_a_little_past_the_edge_and_drops_one_far_past_it() -> None:
    items = [("edge", [-2, 0, 100, 100]), ("far", [0, 0, 5000, 100])]
    kept = noticed(items, 1000, 500, CropRegion(0, 0, 1000, 500), 1.0)
    assert [sighting.label for sighting in kept] == ["edge"]
    assert_rect(kept[0].rect, 0, 0, 100, 100)


def test_labels_are_kept_short_on_one_line() -> None:
    assert short("a\nslime") == "a slime"
    assert len(short("x" * 100)) == 32


async def test_look_closer_shows_the_area_it_sent_when_debugging() -> None:
    r = rig(make_frame(600, 300, region=CropRegion(300, 150, 600, 300)), scale=1.5, debug=True)
    await r.run("look_closer", **{**LOOK, "area": "top_right"})
    [message] = sightings_sent(r.overlay)
    [sighting] = message.sightings
    assert sighting.kind == "look" and sighting.label == LOOK["question"]
    assert sighting.ttl_ms == TOOL_TTL_MS
    assert_rect(sighting.rect, 600 / 1.5, 150 / 1.5, 300 / 1.5, 150 / 1.5)


async def test_point_at_shows_its_target_box_when_debugging() -> None:
    reply = {"found": True, "label": "the door", "box_px": [0, 0, 160, 90]}
    r = rig(make_frame(), reply=reply, debug=True)
    await r.run("point_at", **POINT)
    pointer = next(message for message in r.overlay.sent if isinstance(message, PointerFly))
    [message] = sightings_sent(r.overlay)
    assert message.sightings[0].kind == "point" and message.sightings[0].label == "the door"
    assert message.sightings[0].rect == pointer.target


@pytest.mark.parametrize("tool", ["look_closer", "point_at"])
async def test_tools_send_no_sightings_without_debug(tool: str) -> None:
    reply = {"found": True, "label": "the door", "box_px": [0, 0, 160, 90], "answer": "A door."}
    r = rig(make_frame(), reply=reply)
    await r.run(tool, **(LOOK if tool == "look_closer" else POINT))
    assert sightings_sent(r.overlay) == []


async def test_look_back_shows_the_game_area_when_debugging() -> None:
    now = time.monotonic()
    region = CropRegion(40, 20, 320, 180)
    frames = [make_frame(ts=now - age, region=region) for age in (6, 4, 2, 0)]
    r = rig(*frames, scale=2.0, debug=True)
    await r.run("look_back", TurnContext(started_at=now), question="what hit me?")
    [message] = sightings_sent(r.overlay)
    assert message.sightings[0].kind == "look_back"
    assert_rect(message.sightings[0].rect, 20, 10, 160, 90)
