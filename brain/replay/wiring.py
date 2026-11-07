"""Builds the recording and replay parts of a run, so brain/app.py stays a short list of parts."""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from brain.capture.ring_buffer import RingBuffer
from brain.config import Settings
from brain.events import EventBus
from brain.llm.base import LLMUnavailableError, TextLLM
from brain.replay.recorder import MessageLog, SessionRecorder
from brain.replay.scripted import ScriptedTalker, partner_lines
from brain.server import OverlayLink

log = logging.getLogger(__name__)


class ReplayDone(Exception):
    """Ends the run's task group once a replay with --exit-when-done has played."""


async def exit_after(finished: asyncio.Event, grace_s: float) -> None:
    await finished.wait()
    # The last recorded line may still be on its way to the overlay.
    await asyncio.sleep(grace_s)
    raise ReplayDone


def no_note_model() -> TextLLM:
    """Stands in for the deep model on a replay, so session notes make no network calls and can't
    make two runs differ. A replay's memory is thrown away when it ends anyway."""
    raise LLMUnavailableError("Replays don't call a model for session notes")


async def replay_talker(
    settings: Settings, live_talker: Callable[[], TextLLM | None], session: Path
) -> TextLLM | None:
    """The recorded lines, in order, unless REPLAY_LIVE_TALKER asks for the real model."""
    if settings.replay_live_talker:
        log.warning("Replay is asking the live talker model, so its replies can differ")
        return live_talker()
    lines = await asyncio.to_thread(partner_lines, session)
    log.info("Replay answers with %d recorded lines", len(lines))
    return ScriptedTalker(lines)


def build_recording(
    settings: Settings,
    buffer: RingBuffer,
    bus: EventBus,
    link: OverlayLink,
    record: bool,
    write_messages: Path | None,
) -> tuple[SessionRecorder | None, MessageLog | None]:
    """Hooks them up to every message sent. Build before anything publishes, so no event is
    missed: each one subscribes to the bus when it's built."""
    recorder = None
    if record:
        # Stores screen data, so only ever when asked.
        recorder = SessionRecorder(
            settings.sessions_dir,
            settings.game_title,
            buffer,
            bus,
            lambda: link.display_scale,
            settings.record_fps,
            settings.record_max_gb,
            settings=lambda: link.settings,
        )
        link.on_send = recorder.on_message
    message_log = MessageLog(write_messages) if write_messages else None
    if message_log:
        link.on_send = message_log.on_message
    return recorder, message_log
