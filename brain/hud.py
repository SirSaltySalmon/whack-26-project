"""Builds the HUD readers and the learner that finds the HUD, and joins them to the observer.

Kept out of app.py, which is near the file length limit. The readers also run on replays, so a
reader change shows up when a recorded session is replayed. The learner only runs live, because
it calls a vision model.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from brain.capture.ring_buffer import RingBuffer
from brain.config import Settings
from brain.events import EventBus
from brain.learner.learner import GameLearner, LearnerConfig
from brain.llm.factory import LLMFactory
from brain.memory.db import Database
from brain.memory.models import GameProfile
from brain.memory.profile import ProfileStore
from brain.perception.observer import Observer
from brain.perception.ocr import OcrWorker
from brain.perception.reader_engine import ReaderEngine
from brain.server import OverlayLink
from brain.switches import is_off
from shared.protocol import BrainMessage
from shared.protocol.messages import DebugRegion, DebugRegions

log = logging.getLogger(__name__)

# The overlay hides the view 3 s after the last message, so twice a second keeps it steady.
DEBUG_INTERVAL_S = 0.5


@dataclass
class Hud:
    readers: ReaderEngine
    learner: GameLearner | None
    ocr: OcrWorker

    def close(self) -> None:
        self.ocr.close()


def build_hud(
    settings: Settings,
    factory: LLMFactory,
    database: Database,
    buffer: RingBuffer,
    link: OverlayLink,
    bus: EventBus,
    observer: Observer | None,
    live: bool,
) -> Hud:
    game = settings.game_title

    def in_gameplay() -> bool:
        # Without the observer there's no way to tell menus from play, so assume play.
        return observer is None or observer.live_state().get("screen") == "gameplay"

    async def load_profile() -> GameProfile:
        return await database.run(lambda conn: ProfileStore(conn).get(game))

    ocr = OcrWorker()
    readers = ReaderEngine(
        buffer,
        link,
        bus,
        load_profile,
        settings.mask_padding_px,
        settings.reader_tick_s,
        settings.reader_failing_after_s,
        ocr=ocr,
        in_gameplay=in_gameplay,
    )
    if observer is not None:
        observer.suppressed_events = readers.provides

    learner = None
    if live and is_off(settings, "learner"):
        log.warning("Not learning where the HUD is: turned off for this run")
    elif live:
        config = LearnerConfig(
            frames=settings.learner_frames,
            frame_gap_s=settings.learner_frame_gap_s,
            max_vision_calls=settings.learner_max_vision_calls,
            relearn_gap_s=settings.learner_relearn_gap_s,
            # Under Claude's ~1.15 MP limit, so its pixel boxes refer to the image as sent.
            closeup_max_edge_px=settings.ai_image_max_edge_px,
            mask_padding_px=settings.mask_padding_px,
            profile_fixture=settings.profile_fixture,
            debug_dir=(
                settings.sessions_dir / f"learner-{time.strftime('%Y%m%d-%H%M%S')}"
                if settings.debug_regions
                else None
            ),
        )
        learner = GameLearner(
            database,
            game,
            factory.vision,
            buffer,
            link,
            bus,
            link.send,
            config,
            ocr=ocr,
            in_gameplay=in_gameplay,
        )
    return Hud(readers, learner, ocr)


def live_state(
    voice: dict[str, str], readers: dict[str, str], observer: dict[str, str]
) -> dict[str, str]:
    """Mood first, then readers, then the observer's other keys.

    Memory cuts this block to a fixed length from the end, so the fast, exact reader values go
    early, and a reader replaces the observer's slower value for the same key.
    """
    rest = {key: value for key, value in observer.items() if key not in readers}
    return {**voice, **readers, **rest}


async def send_debug_regions(
    readers: ReaderEngine, send: Callable[[BrainMessage], Awaitable[None]]
) -> None:
    """Shows where each reader looks and what it reads, over the game, for debugging."""
    log.info("Drawing the HUD regions over the game (--debug-regions)")
    shown = False
    while True:
        views = readers.debug_view()
        # An empty list clears the view, so it's sent once when the readers go away.
        if views or shown:
            regions = [DebugRegion(name=v.name, rect=v.rect, status=v.status, display=v.display)
                       for v in views]  # fmt: skip
            await send(DebugRegions(regions=regions))
            shown = bool(views)
        await asyncio.sleep(DEBUG_INTERVAL_S)
