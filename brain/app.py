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
from brain.replay.source import ReplayFrameSource
from brain.server import OverlayLink, create_app
from brain.voice.pipeline import SubtitleOnlyVoice

log = logging.getLogger(__name__)


async def run(settings: Settings, replay_dir: Path | None = None) -> None:
    bus = EventBus()
    link = OverlayLink(bus)
    voice = SubtitleOnlyVoice(link)
    director = Director(bus, voice, proactive=lambda: link.settings.proactive)

    source: FrameSource = ReplayFrameSource(replay_dir) if replay_dir else default_live_source()
    capacity = settings.capture_fps * settings.ring_buffer_seconds
    capture = CaptureLoop(source, RingBuffer(capacity), link, settings.capture_fps)

    config = uvicorn.Config(
        create_app(link), host=WS_HOST, port=settings.brain_port, log_level="warning"
    )
    server = uvicorn.Server(config)

    log.info("Brain listening on ws://%s:%s/ws", WS_HOST, settings.brain_port)
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(server.serve())
        tasks.create_task(director.run())
        tasks.create_task(capture.run())
