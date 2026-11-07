"""Wires the components together and runs them until shutdown."""

import asyncio
import logging
from pathlib import Path

import uvicorn

from brain.capture.loop import CaptureLoop
from brain.capture.ring_buffer import RingBuffer
from brain.capture.source import FrameSource, default_live_source
from brain.config import WS_HOST, Settings
from brain.director.director import Director
from brain.events import EventBus
from brain.llm.base import LLMUnavailableError, TextLLM
from brain.llm.factory import LLMFactory
from brain.memory.db import Database, connect
from brain.memory.notes import NoteWriter
from brain.memory.service import MemoryService
from brain.memory.snapshot import connect_replay
from brain.replay.source import ReplayFrameSource
from brain.server import OverlayLink, create_app
from brain.voice.pipeline import create_voice
from shared.protocol.messages import Settings as OverlaySettings

log = logging.getLogger(__name__)


def _talker(settings: Settings) -> TextLLM | None:
    try:
        return LLMFactory(settings).talker()
    except LLMUnavailableError as exc:
        log.warning("Talker disabled: %s", exc)
        return None


async def run(settings: Settings, replay_dir: Path | None = None) -> None:
    bus = EventBus()
    link = OverlayLink(bus)

    # Replays are test and fallback runs: they start from a fixed snapshot and leave no trace.
    conn = connect_replay(settings.replay_snapshot) if replay_dir else connect(settings.db_path)
    database = Database(conn)
    memory = MemoryService(
        database,
        bus,
        link.send,
        settings.game_title,
        NoteWriter(LLMFactory(settings).deep),
        vault_dir=None if replay_dir else settings.vault_dir,
        note_interval_s=settings.note_interval_s,
        note_min_new_events=settings.note_min_new_events,
    )
    await memory.start()
    link.settings = await memory.load_settings(OverlaySettings)

    voice = create_voice(settings, bus, link)
    director = Director(
        bus,
        voice,
        proactive=lambda: link.settings.proactive,
        talker=_talker(settings),
        personality=lambda: link.settings.personality,
        max_words=settings.talker_max_words,
    )

    source: FrameSource = ReplayFrameSource(replay_dir) if replay_dir else default_live_source()
    capacity = settings.capture_fps * settings.ring_buffer_seconds
    capture = CaptureLoop(source, RingBuffer(capacity), link, settings.capture_fps)

    config = uvicorn.Config(
        create_app(link), host=WS_HOST, port=settings.brain_port, log_level="warning"
    )
    server = uvicorn.Server(config)

    log.info("Brain listening on ws://%s:%s/ws", WS_HOST, settings.brain_port)
    try:
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(server.serve())
            tasks.create_task(director.run())
            tasks.create_task(capture.run())
            tasks.create_task(voice.run())
            tasks.create_task(memory.run())
    finally:
        database.close()
