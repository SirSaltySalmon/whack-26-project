"""look_back: the frames it picks, the sheet's layout, what's hidden, and when it gives up."""

import time

import cv2
import numpy as np
import pytest

from brain.agent.rewind import (
    LABEL_STRIP_PX,
    SHEET_MAX_EDGE_PX,
    Rewind,
    make_sheet,
    pick_moments,
)
from brain.agent.schemas import CANT_SEE, LookBackInput
from brain.agent.tools import TurnContext
from brain.capture.ring_buffer import Frame
from brain.tests.agent_rig import rig
from brain.tests.fakes import FakeVision, VisionCall, make_buffer, make_frame
from shared.protocol.messages import Rect

ASK = {"question": "what hit me?"}
DIM = 60
BRIGHT = 230
EVERY_MOMENT = (6, 4, 2, 0)
MAX_EDGE = 320  # The rig's closeup_max_edge_px


def sent_image(call: VisionCall) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(call.image, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return image


def centre(image: np.ndarray, tile: tuple[int, int, int, int]) -> float:
    x, y, width, height = tile
    return float(
        image[y + height // 4 : y + 3 * height // 4, x + width // 4 : x + 3 * width // 4].mean()
    )


def frames(now: float, marked_age: float | None = None) -> list[Frame]:
    made = []
    for age in EVERY_MOMENT:
        image = np.full((180, 320, 3), DIM, dtype=np.uint8)
        if age == marked_age:
            image[45:135, 80:240] = BRIGHT
        made.append(make_frame(ts=now - age, image=image))
    return made


def test_the_sheet_has_four_tiles_in_time_order_and_a_shape_shows_only_where_it_was() -> None:
    now = time.monotonic()
    moments = pick_moments(make_buffer(*frames(now, marked_age=4)), now)
    assert [moment.label for moment in moments] == ["-6 s", "-4 s", "-2 s", "now"]
    sheet = make_sheet(moments, 1.0, 0, MAX_EDGE)
    tiles = sheet.tiles
    # Left to right, then top to bottom.
    assert tiles[0][1] == tiles[1][1] < tiles[2][1] == tiles[3][1]
    assert tiles[0][0] == tiles[2][0] < tiles[1][0] == tiles[3][0]
    assert [centre(sheet.image, tile) > 150 for tile in tiles] == [False, True, False, False]
    assert max(sheet.image.shape[:2]) <= MAX_EDGE


def test_labels_sit_in_a_strip_above_each_picture_never_on_it() -> None:
    now = time.monotonic()
    sheet = make_sheet(pick_moments(make_buffer(*frames(now)), now), 1.0, 0, MAX_EDGE)
    for x, y, width, height in sheet.tiles:
        picture = sheet.image[y : y + height, x : x + width]
        assert picture.min() == picture.max() == DIM
        assert sheet.image[y - LABEL_STRIP_PX : y, x : x + width].min() < 50, "the label's text"


def test_our_own_ui_is_black_in_every_tile() -> None:
    now = time.monotonic()
    masked = [
        make_frame(ts=now - age, fill=200, rects=[Rect(x=0, y=0, width=160, height=180)])
        for age in EVERY_MOMENT
    ]
    sheet = make_sheet(pick_moments(make_buffer(*masked), now), 1.0, 0, MAX_EDGE)
    for x, y, width, height in sheet.tiles:
        assert sheet.image[y + height // 2, x + width // 4].max() < 40, "under the overlay"
        assert sheet.image[y + height // 2, x + 3 * width // 4].min() > 160, "beside it"


def test_a_frame_near_two_moments_is_used_once_and_far_ones_are_left_out() -> None:
    # Exact times, so a gap of exactly 1 s isn't lost to rounding. 999 is 1 s from both the -2 s
    # and now moments, and nothing is within 1 s of -4 s.
    buffer = make_buffer(make_frame(ts=994.0), make_frame(ts=999.0))
    assert [moment.label for moment in pick_moments(buffer, 1000.0)] == ["-6 s", "-2 s"]


async def test_it_looks_back_from_when_the_player_began_not_from_the_newest_frame() -> None:
    now = time.monotonic()
    started = now - 4
    before = [make_frame(ts=started - age, fill=DIM) for age in EVERY_MOMENT]
    after = [make_frame(ts=now - age, fill=BRIGHT) for age in (2, 0)]
    r = rig(*before, *after)
    result = await r.run("look_back", TurnContext(started_at=started), **ASK)

    assert len(r.vision.calls) == 1
    call = r.vision.calls[0]
    assert (call.detail, call.media_type) == ("high", "image/jpeg")
    assert "what hit me?" in call.prompt
    expected = make_sheet(pick_moments(r.buffer, started), 1.0, 0, MAX_EDGE)
    sent = sent_image(call)
    assert sent.shape == expected.image.shape
    assert all(centre(sent, tile) < 100 for tile in expected.tiles)
    assert result.endswith("A red door.") and result.startswith("[seen on screen")


async def test_an_unsure_answer_says_so() -> None:
    now = time.monotonic()
    r = rig(*frames(now), reply={"answer": "Maybe an arrow.", "sure": False})
    result = await r.run("look_back", TurnContext(started_at=now), **ASK)
    assert result.endswith("Maybe an arrow. (not sure of this)")


@pytest.mark.parametrize(
    "ages", [(), (0,), (30, 29)], ids=["no frames", "one frame", "frames from long before"]
)
async def test_fewer_than_two_usable_frames_means_it_cant_see_and_calls_nothing(
    ages: tuple[float, ...],
) -> None:
    now = time.monotonic()
    r = rig(*(make_frame(ts=now - age) for age in ages))
    assert await r.run("look_back", TurnContext(started_at=now), **ASK) == CANT_SEE
    assert r.vision.calls == []


async def test_a_full_hd_game_is_sent_no_wider_than_claude_takes_unshrunk() -> None:
    # The live closeup edge is 1920, past what Claude takes unshrunk, so the sheet is capped.
    now = time.monotonic()
    vision = FakeVision({"answer": "A slime.", "sure": True})
    big = [make_frame(1920, 1080, ts=now - age) for age in EVERY_MOMENT]
    tool = Rewind(make_buffer(*big), lambda: 1.0, lambda: vision, 0, 1920).tool(5.0)
    await tool.handler(LookBackInput(question="what hit me?"), TurnContext(started_at=now))
    height, width = sent_image(vision.calls[0]).shape[:2]
    # Uses the room it has, and stays under Claude's resize threshold.
    assert SHEET_MAX_EDGE_PX - 10 < max(height, width) <= SHEET_MAX_EDGE_PX
    assert height * width < 1_150_000
