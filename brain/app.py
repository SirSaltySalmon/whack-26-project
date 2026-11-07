"""Wires the components together and runs them until shutdown."""

import asyncio
import logging
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import uvicorn

from brain.agent.focus_tool import watch_tool
from brain.agent.handlers import AgentLimits, AgentTools
from brain.agent.tools import ToolRegistry
from brain.capture.loop import CaptureLoop
from brain.capture.ring_buffer import RingBuffer
from brain.capture.source import default_live_source
from brain.capture.window import GameWindow
from brain.config import WS_HOST, Settings
from brain.director.director import Director
from brain.director.personalities import load_personalities
from brain.events import EventBus
from brain.llm.base import LLMUnavailableError
from brain.llm.factory import LLMFactory
from brain.llm.gemini import GeminiClient
from brain.memory.db import Database, connect
from brain.memory.notes import NoteWriter
from brain.memory.service import MemoryService
from brain.memory.snapshot import connect_replay
from brain.perception.focus import Focus, FocusIntervals
from brain.perception.observer import Observer
from brain.perception.tracker import ObservationTracker
from brain.replay.source import ReplayLoop
from brain.replay.wiring import (
    ReplayDone,
    build_recording,
    exit_after,
    no_note_model,
    replay_talker,
)
from brain.research import ExaSearch, WikiResearch
from brain.research.wiki_cache import WikiCache
from brain.server import OverlayLink, create_app
from brain.voice.pipeline import SubtitleOnlyVoice, create_voice
from brain.voice.typed import typed_turns
from shared.protocol.messages import Settings as OverlaySettings

log = logging.getLogger(__name__)


def _talker(factory: LLMFactory) -> GeminiClient | None:
    try:
        return factory.talker()
    except LLMUnavailableError as exc:
        log.warning("Talker disabled: %s", exc)
        return None


def _observer(
    settings: Settings, factory: LLMFactory, buffer: RingBuffer, link: OverlayLink, bus: EventBus
) -> Observer | None:
    try:
        vision = factory.observer()
    except LLMUnavailableError as exc:
        log.warning("Not watching the screen: %s", exc)
        return None
    return Observer(
        buffer,
        link,
        vision,
        bus,
        ObservationTracker(),
        Focus(
            FocusIntervals(
                settings.observer_interval_low_s,
                settings.observer_interval_medium_s,
                settings.observer_interval_high_s,
            ),
            settings.focus_hold_s,
        ),
        settings.ai_image_max_edge_px,
        settings.mask_padding_px,
    )


def _registry(tools: AgentTools | None, observer: Observer | None) -> ToolRegistry | None:
    if tools is None:
        return None
    # Only offered while something is watching, or the boost would do nothing.
    return tools.registry().including(watch_tool(observer.focus)) if observer else tools.registry()


async def _find_wiki(settings: Settings, database: Database, tools: AgentTools) -> None:
    """In the background, so a slow or dead wiki can't hold up the brain's start."""
    title = settings.game_title.strip()
    if not title or title == Settings.model_fields["game_title"].default:
        log.warning("No wiki lookups: set GAME_TITLE to the game being played")
        return
    key = settings.exa_api_key
    web_search = ExaSearch(key.get_secret_value()) if key else None
    tools.research = await WikiResearch.for_game(title, WikiCache(database), web_search=web_search)
    if tools.research is None:
        log.warning("No wiki found for %s", title)
    else:
        log.info("Using the wiki at %s", tools.research.site.api_url)


async def _survive(name: str, work: Coroutine[Any, Any, None]) -> None:
    """Keeps a failure in an optional part, such as no audio device, from ending the brain."""
    try:
        await work
    except Exception:
        log.exception("%s stopped; carrying on without it", name)


async def run(
    settings: Settings,
    replay_dir: Path | None = None,
    typed: bool = False,
    record: bool = False,
    speed: float = 1.0,
    exit_when_done: bool = False,
    write_messages: Path | None = None,
) -> None:
    bus = EventBus()
    link = OverlayLink(bus)
    # One factory, because limiters are per model and vision and deep notes can share a model.
    factory = LLMFactory(settings)
    personalities = load_personalities()
    link.personalities = personalities.names
    link.voices = settings.voice_options

    # Replays are test and fallback runs: they start from a fixed snapshot and leave no trace.
    conn = connect_replay(settings.replay_snapshot) if replay_dir else connect(settings.db_path)
    database = Database(conn)
    memory = MemoryService(
        database,
        bus,
        link.send,
        settings.game_title,
        NoteWriter(no_note_model if replay_dir else factory.deep),
        vault_dir=None if replay_dir else settings.vault_dir,
        note_interval_s=settings.note_interval_s,
        note_min_new_events=settings.note_min_new_events,
    )
    await memory.start()
    link.settings = await memory.load_settings(OverlaySettings)

    buffer = RingBuffer(settings.capture_fps * settings.ring_buffer_seconds)
    replay = ReplayLoop(replay_dir, buffer, bus, link, speed=speed) if replay_dir else None
    capture = replay or CaptureLoop(
        default_live_source(),
        buffer,
        link,
        settings.capture_fps,
        GameWindow(settings.game_process),
    )
    # Replays are tests and fallbacks, so they never spend money on vision.
    observer = None if replay_dir else _observer(settings, factory, buffer, link, bus)
    recorder, message_log = build_recording(
        settings, buffer, bus, link, record and not replay_dir, write_messages
    )

    # Replay never opens the mic, which would mix live speech into the recording, and never
    # spends TTS characters. Subtitles also keep two runs' messages comparable.
    voice = SubtitleOnlyVoice(link) if replay_dir else create_voice(settings, bus, link)

    async def talker_context(query: str) -> str:
        # What the partner hears and sees now, on top of what memory knows. Mood goes first
        # because it's short and memory cuts this to a fixed length.
        live = {**voice.live_state(), **(observer.live_state() if observer else {})}
        return await memory.context(live, query)

    async def on_spoken(text: str) -> None:
        if recorder:
            recorder.on_partner_said(text)
        await memory.record_partner_turn(text)

    live_talker = None if replay_dir else _talker(factory)
    if replay_dir:
        talker = await replay_talker(settings, lambda: _talker(factory), replay_dir)
    else:
        talker = live_talker
    # Replays never spend money on vision, so they get plain replies with no tools.
    tools = None
    if live_talker is not None:
        tools = AgentTools(
            buffer,
            link,
            factory.vision,
            factory.deep,
            memory,
            talker_context,
            AgentLimits(
                settings.mask_padding_px,
                settings.closeup_max_edge_px,
                settings.look_max_frame_age_s,
                settings.pointer_ttl_ms,
            ),
            look_vision=factory.closeup,
        )

    director = Director(
        bus,
        voice,
        proactive=lambda: link.settings.proactive,
        talker=talker,
        personality=lambda: link.settings.personality,
        max_words=settings.talker_max_words,
        context=talker_context,
        on_spoken=on_spoken,
        agent=live_talker if tools else None,
        tools=_registry(tools, observer),
        personalities=personalities,
        take_question=memory.take_question,
        send=link.send,
        question_gap_s=settings.question_gap_s,
        question_quiet_s=settings.question_quiet_s,
    )

    config = uvicorn.Config(
        create_app(link), host=WS_HOST, port=settings.brain_port, log_level="warning"
    )
    server = uvicorn.Server(config)

    log.info("Brain listening on ws://%s:%s/ws", WS_HOST, settings.brain_port)
    try:
        async with asyncio.TaskGroup() as tasks:
            for name, part in (("Recorder", recorder), ("Message log", message_log)):
                if part:
                    tasks.create_task(_survive(name, part.run()))
            tasks.create_task(server.serve())
            tasks.create_task(director.run())
            tasks.create_task(capture.run())
            tasks.create_task(_survive("Voice", voice.run()))
            if observer:
                tasks.create_task(_survive("Observer", observer.run()))
            tasks.create_task(memory.run())
            if tools:
                tasks.create_task(_survive("Wiki", _find_wiki(settings, database, tools)))
            if typed:
                tasks.create_task(_survive("Typing", typed_turns(bus)))
            if replay and exit_when_done:
                tasks.create_task(exit_after(replay.finished, settings.replay_exit_grace_s))
    except* ReplayDone:
        log.info("Replay finished; exiting")
    finally:
        if tools and tools.research:
            await tools.research.aclose()
        database.close()
