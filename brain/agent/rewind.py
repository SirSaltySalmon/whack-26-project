"""look_back: answers "what just hit me?" once the moment has passed.

look_closer reads the one frame from when the player began speaking. The most interesting moments
are over by then, so this tiles a few frames from before it into one sheet, and one vision call
sees what happened in order. Kept apart from handlers.py, which is near the file length limit.
"""

import asyncio
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from brain.agent.schemas import BLINDED, CANT_SEE, LOOK_BACK_PROMPT, LookBackInput, LookReply
from brain.agent.tools import Tool, TurnContext
from brain.capture.ring_buffer import Frame, RingBuffer
from brain.llm.base import VisionLLM
from brain.perception.closeup import encode_jpeg
from brain.perception.masking import mask_overlay

# Seconds before the player began speaking. Starting values: the 10 s buffer holds them all, and a
# hit and what caused it usually fit in 6 s.
OFFSETS_S = (6.0, 4.0, 2.0, 0.0)
# A frame further than this from its moment shows a different moment, so it's left out.
MAX_GAP_S = 1.0
# One frame can't show what changed, which is the whole point.
MIN_MOMENTS = 2
COLUMNS = 2
# Labels sit in a strip above each picture, so they never cover the game.
LABEL_STRIP_PX = 22
GAP_PX = 4
# Light grey, so the sheet's background can't be mistaken for a black overlay mask.
BACKGROUND = 235
LABEL_COLOR = (0, 0, 0)
MAX_TOKENS = 1000  # The same room as look_closer's answer.
# Claude shrinks an image past about 1.15 megapixels. A 2x2 sheet of 16:9 frames 1280 px wide
# stays under that, so a wider one would only cost upload time, not show more.
SHEET_MAX_EDGE_PX = 1280


@dataclass(frozen=True)
class Moment:
    label: str
    frame: Frame


@dataclass(frozen=True)
class Sheet:
    image: np.ndarray
    # Each moment's picture in the sheet, as (x, y, width, height), in time order.
    tiles: tuple[tuple[int, int, int, int], ...]


def _label(offset_s: float) -> str:
    return "now" if offset_s == 0 else f"-{offset_s:g} s"


def pick_moments(buffer: RingBuffer, reference: float) -> list[Moment]:
    """Frames from before `reference`, oldest first, each near its moment and none repeated."""
    moments: list[Moment] = []
    taken: set[float] = set()
    for offset in OFFSETS_S:
        target = reference - offset
        frame = buffer.nearest(target)
        if frame is None or abs(frame.ts - target) > MAX_GAP_S or frame.ts in taken:
            continue
        taken.add(frame.ts)
        moments.append(Moment(_label(offset), frame))
    return moments


def make_sheet(
    moments: Sequence[Moment], display_scale: float, padding_px: int, max_edge_px: int
) -> Sheet:
    """CPU-bound, so callers run it in a worker thread. The buffer's frames are left untouched."""
    images = [
        mask_overlay(
            m.frame.image, m.frame.overlay_rects, display_scale, padding_px, m.frame.region
        )
        for m in moments
    ]
    # The newest frame sets the shape, in case the window was resized partway through.
    height, width = images[-1].shape[:2]
    rows = math.ceil(len(images) / COLUMNS)
    scale = min(
        (max_edge_px - GAP_PX * (COLUMNS - 1)) / (COLUMNS * width),
        (max_edge_px / rows - LABEL_STRIP_PX) / height,
    )
    tile_w, tile_h = max(1, int(width * scale)), max(1, int(height * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_NEAREST
    sheet = np.full(
        (rows * (LABEL_STRIP_PX + tile_h), COLUMNS * tile_w + GAP_PX * (COLUMNS - 1), 3),
        BACKGROUND,
        dtype=np.uint8,
    )
    tiles: list[tuple[int, int, int, int]] = []
    for index, (moment, image) in enumerate(zip(moments, images, strict=True)):
        row, column = divmod(index, COLUMNS)
        x = column * (tile_w + GAP_PX)
        top = row * (LABEL_STRIP_PX + tile_h) + LABEL_STRIP_PX
        cv2.putText(
            sheet,
            moment.label,
            (x + 6, top - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            LABEL_COLOR,
            1,
            cv2.LINE_AA,
        )
        sheet[top : top + tile_h, x : x + tile_w] = cv2.resize(
            image, (tile_w, tile_h), interpolation=interpolation
        )
        tiles.append((x, top, tile_w, tile_h))
    return Sheet(sheet, tuple(tiles))


def _sheet_jpeg(
    moments: Sequence[Moment], display_scale: float, padding_px: int, max_edge_px: int
) -> bytes:
    return encode_jpeg(make_sheet(moments, display_scale, padding_px, max_edge_px).image)


class Rewind:
    def __init__(
        self,
        buffer: RingBuffer,
        display_scale: Callable[[], float],
        vision: Callable[[], VisionLLM],
        padding_px: int,
        max_edge_px: int,
        *,
        watching: Callable[[], bool] = lambda: True,
    ) -> None:
        self._buffer = buffer
        self._display_scale = display_scale
        self._vision = vision
        self._padding_px = padding_px
        self._max_edge_px = min(max_edge_px, SHEET_MAX_EDGE_PX)
        # The player's vision setting. Blind means blind to the past few seconds as well.
        self._watching = watching

    def tool(self, timeout_s: float) -> Tool:
        # Not quick: the filler line plays, and the turn survives a barge-in like look_closer.
        return Tool(
            "look_back",
            "Look back over the last few seconds of the game, for something that may no longer "
            "be on screen: what happened, what hit or killed the player, or 'did you see that'. "
            "For what's on screen now, use look_closer. Takes a couple of seconds.",
            LookBackInput,
            self._look_back,
            timeout_s,
        )

    async def _look_back(self, arguments: LookBackInput, turn: TurnContext) -> str:
        if not self._watching():
            return BLINDED
        # From when they began speaking, because they ask after the moment, not during it.
        reference = turn.started_at if turn.started_at is not None else time.monotonic()
        moments = pick_moments(self._buffer, reference)
        if len(moments) < MIN_MOMENTS:
            return CANT_SEE
        image = await asyncio.to_thread(
            _sheet_jpeg, moments, self._display_scale(), self._padding_px, self._max_edge_px
        )
        reply = await self._vision().vision_json(
            LOOK_BACK_PROMPT.format(question=arguments.question),
            image,
            "image/jpeg",
            LookReply,
            MAX_TOKENS,
            detail="high",
        )
        return reply.as_result()
