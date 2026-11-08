"""look_back: what happened in the last few seconds, from one tiled image of earlier frames."""

import time

import cv2
import numpy as np

from brain.agent.rewind import CANT_SEE, LABEL_STRIP_PX, SHEET_MAX_EDGE_PX, contact_sheet
from brain.agent.tools import TurnContext
from brain.tests.agent_rig import rig
from brain.tests.fakes import VisionCall, make_frame
from shared.protocol.messages import Rect

WIDTH, HEIGHT = 320, 180
REPLY = {"answer": "A slime jumped on you.", "sure": True}
SPOKE = TurnContext(started_at=1000.0)
WHITE = 255


def frames_around(spoke_at: float, marked_offset: float | None = None) -> list:  # type: ignore[type-arg]
    """One frame at each moment look_back wants, 6, 4, 2 and 0 s before speaking. The test rig's
    buffer holds 8 frames, so these fit. The one `marked_offset` back gets a white square."""
    frames = []
    for offset in (6.0, 4.0, 2.0, 0.0):
        image = np.full((HEIGHT, WIDTH, 3), 60, dtype=np.uint8)
        if offset == marked_offset:
            image[60:120, 120:200] = WHITE
        frames.append(make_frame(ts=spoke_at - offset, image=image))
    return frames


def sheet_of(call: VisionCall) -> np.ndarray:
    sheet = cv2.imdecode(np.frombuffer(call.image, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert sheet is not None
    return sheet


def tiles(sheet: np.ndarray) -> list[np.ndarray]:
    """The four pictures, in time order, without their label strips."""
    cell_h, tile_w = sheet.shape[0] // 2, sheet.shape[1] // 2
    tile_h = cell_h - LABEL_STRIP_PX
    return [
        sheet[row * cell_h : row * cell_h + tile_h, col * tile_w : (col + 1) * tile_w]
        for row in range(2)
        for col in range(2)
    ]


def patched_clock(monkeypatch, now: float) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(time, "monotonic", lambda: now)


async def test_four_tiles_in_time_order_and_only_the_marked_moment_shows_the_square(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    patched_clock(monkeypatch, 1000.5)
    r = rig(*frames_around(1000.0, marked_offset=4.0), reply=REPLY)
    output = await r.run("look_back", SPOKE, question="what hit me?")
    assert "A slime jumped on you." in output and "not sure" not in output
    sheet = sheet_of(r.vision.calls[0])
    assert max(sheet.shape[:2]) <= SHEET_MAX_EDGE_PX
    brightness = [float(tile.mean()) for tile in tiles(sheet)]
    # Tiles are -6 s, -4 s, -2 s and now: only the second one holds the white square.
    assert brightness[1] > max(brightness[0], brightness[2], brightness[3]) + 10


async def test_it_makes_exactly_one_call_at_high_detail(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    patched_clock(monkeypatch, 1000.5)
    r = rig(*frames_around(1000.0), reply=REPLY)
    await r.run("look_back", SPOKE, question="what happened?")
    assert len(r.vision.calls) == 1 and r.vision.calls[0].detail == "high"
    assert "what happened?" in r.vision.calls[0].prompt


async def test_the_overlay_is_masked_in_every_tile(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    patched_clock(monkeypatch, 1000.5)
    bright = [
        make_frame(
            ts=f.ts,
            image=np.full((HEIGHT, WIDTH, 3), 200, dtype=np.uint8),
            rects=[Rect(x=0, y=0, width=WIDTH // 2, height=HEIGHT)],
        )  # fmt: skip
        for f in frames_around(1000.0)
    ]
    r = rig(*bright, reply=REPLY)
    await r.run("look_back", SPOKE, question="what was that?")
    for tile in tiles(sheet_of(r.vision.calls[0])):
        half = tile.shape[1] // 2
        assert tile[:, : half - 4].mean() < 20  # The overlay's half is blacked out
        assert tile[:, half + 4 :].mean() > 150


async def test_it_looks_back_from_when_the_player_spoke_not_from_now(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    patched_clock(monkeypatch, 1003.0)
    # Spoke at 1000; frames run to 1003. The marked frame is 2 s before speaking, 5 s before now.
    later = [make_frame(ts=1000.0 + step) for step in (1.0, 2.0, 3.0)]
    marked = frames_around(1000.0, marked_offset=2.0)
    r = rig(*marked, *later, reply=REPLY)
    await r.run("look_back", SPOKE, question="what was that?")
    brightness = [float(tile.mean()) for tile in tiles(sheet_of(r.vision.calls[0]))]
    assert brightness[2] > max(brightness[0], brightness[1], brightness[3]) + 10


async def test_too_few_fresh_frames_means_no_call(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    patched_clock(monkeypatch, 1000.5)
    r = rig(make_frame(ts=1000.0), reply=REPLY)  # Only "now" is there
    assert await r.run("look_back", SPOKE, question="what hit me?") == CANT_SEE
    assert r.vision.calls == []


async def test_stale_frames_mean_no_call(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    patched_clock(monkeypatch, 2000.0)  # The newest frame is far older than max_age
    r = rig(*frames_around(1000.0), reply=REPLY)
    assert await r.run("look_back", SPOKE, question="what hit me?") == CANT_SEE
    assert r.vision.calls == []


async def test_it_says_when_it_isnt_sure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    patched_clock(monkeypatch, 1000.5)
    r = rig(*frames_around(1000.0), reply={"answer": "Maybe a slime.", "sure": False})
    assert "Maybe a slime. (not sure of this)" in await r.run("look_back", SPOKE, question="?")


def test_labels_sit_below_the_pictures() -> None:
    frame = make_frame(ts=0.0, image=np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8))
    sheet = contact_sheet([(6.0, frame), (0.0, frame)], 1.0, 0, 640)
    for tile in tiles(sheet):
        assert tile.max() == 0  # Nothing drawn over the game itself
    assert sheet.max() == 255  # The labels are there, in the strips
