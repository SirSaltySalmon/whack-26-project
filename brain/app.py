"""Wires the components together and runs them until shutdown."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import uvicorn

from brain.agent.focus_tool import watch_tool
from brain.agent.handlers import AgentLimits, AgentTools
from brain.agent.tools import ToolRegistry
from brain.capture.loop import CaptureLoop
from brain.capture.ring_buffer import RingBuffer
from brain.capture.source import FrameSource, default_live_source, live_frame_scale
from brain.capture.window import create_game_window
from brain.config import WS_HOST, Settings
from brain.director.director import Director
from brain.director.personalities import PersonalityBook, load_personalities
from brain.events import EventBus
from brain.learner.progress import ProgressScout
from brain.llm.base import LLMUnavailableError
from brain.llm.factory import LLMFactory
from brain.llm.gemini import GeminiClient
from brain.memory.db import Database, connect
from brain.memory.notes import NoteWriter
from brain.memory.service import MemoryService
from brain.memory.snapshot import connect_replay
from brain.perception.focus import Focus, FocusIntervals
from brain.perception.observation import Observation
from brain.perception.observer import Observer
from brain.perception.tracker import ObservationTracker
from brain.replay.source import ReplayFrameSource
from brain.research import ExaSearch, WikiResearch
from brain.research.open_page import OpenPage
from brain.research.wiki_cache import WikiCache
from brain.server import OverlayLink, create_app
from brain.voice.barks import BarkBank, ElevenLabsSynth
from brain.voice.pipeline import create_voice
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
    settings: Settings,
    factory: LLMFactory,
    buffer: RingBuffer,
    link: OverlayLink,
    bus: EventBus,
    on_observation: Callable[[Observation, float], None] | None = None,
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
        on_observation,
    )


def _progress_scout(
    settings: Settings,
    factory: LLMFactory,
    buffer: RingBuffer,
    link: OverlayLink,
    memory: MemoryService,
) -> ProgressScout | None:
    try:
        vision = factory.vision()
    except LLMUnavailableError as exc:
        log.warning("Not guessing the player's progress: %s", exc)
        return None
    return ProgressScout(
        buffer,
        link,
        vision,
        memory,
        settings.game_title,
        max_edge_px=settings.closeup_max_edge_px,
        mask_padding_px=settings.mask_padding_px,
        max_calls=settings.progress_max_vision_calls,
        retry_gap_s=settings.progress_retry_gap_s,
        recheck_s=settings.progress_recheck_s,
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


def _bark_bank(settings: Settings, book: PersonalityBook) -> BarkBank:
    key = settings.elevenlabs_api_key
    if key is None:
        log.info("No ElevenLabs key, so barks are never generated; cached ones still play")
    synth = ElevenLabsSynth(key.get_secret_value()) if key else None
    return BarkBank(book, synth, settings.barks_dir, settings.tts_model, settings.tts_sample_rate)


async def _survive(name: str, work: Coroutine[Any, Any, None]) -> None:
    """Keeps a failure in an optional part, such as no audio device, from ending the brain."""
    try:
        await work
    except Exception:
        log.exception("%s stopped; carrying on without it", name)


async def run(settings: Settings, replay_dir: Path | None = None, typed: bool = False) -> None:
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
        NoteWriter(factory.deep),
        vault_dir=None if replay_dir else settings.vault_dir,
        note_interval_s=settings.note_interval_s,
        note_min_new_events=settings.note_min_new_events,
    )
    await memory.start()
    link.settings = await memory.load_settings(OverlaySettings)

    source: FrameSource = ReplayFrameSource(replay_dir) if replay_dir else default_live_source()
    buffer = RingBuffer(settings.capture_fps * settings.ring_buffer_seconds)
    window = None if replay_dir else create_game_window(settings.game_process)
    if not replay_dir:
        link.frame_scale_override = live_frame_scale()
    capture = CaptureLoop(source, buffer, link, settings.capture_fps, window)
    # Replays are tests and fallbacks, so they never spend money on vision.
    scout = None if replay_dir else _progress_scout(settings, factory, buffer, link, memory)
    observer = (
        None
        if replay_dir
        else _observer(settings, factory, buffer, link, bus, scout.notice if scout else None)
    )
    if observer is None:
        # Nothing would wake it.
        scout = None

    voice = create_voice(settings, bus, link)

    async def talker_context(query: str) -> str:
        # What the partner hears and sees now, on top of what memory knows. Mood goes first
        # because it's short and memory cuts this to a fixed length.
        live = {**voice.live_state(), **(observer.live_state() if observer else {})}
        return await memory.context(live, query)

    talker = _talker(factory)
    # Replays never spend money on vision, so they get plain replies with no tools.
    tools = None
    open_page = None
    if talker is not None and not replay_dir:
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
        live_tools = tools

        def wiki_host() -> str | None:
            # None until the wiki is found in the background, and then no page is read.
            research = live_tools.research
            return urlparse(research.site.info.server).hostname if research else None

        open_page = OpenPage(bus, link.send, wiki_host)
        tools.open_page = open_page

    barks = _bark_bank(settings, personalities)

    def voice_id() -> str | None:
        # Matches the voice PipecatVoice picks: the player's choice, then the configured default.
        return link.settings.voice_id or settings.elevenlabs_voice_id

    director = Director(
        bus,
        voice,
        proactive=lambda: link.settings.proactive,
        talker=talker,
        personality=lambda: link.settings.personality,
        max_words=settings.talker_max_words,
        context=talker_context,
        on_spoken=memory.record_partner_turn,
        agent=talker if tools else None,
        tools=_registry(tools, observer),
        personalities=personalities,
        take_question=memory.take_question,
        send=link.send,
        question_gap_s=settings.question_gap_s,
        question_quiet_s=settings.question_quiet_s,
        advice_gap_s=settings.advice_gap_s,
        advice_quiet_s=settings.advice_quiet_s,
        page_excerpt=open_page.excerpt_for if open_page else None,
        barks=barks,
        voice_id=voice_id,
    )
    startup_voice = voice_id()

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
            tasks.create_task(_survive("Voice", voice.run()))
            if observer:
                tasks.create_task(_survive("Observer", observer.run()))
            if scout:
                tasks.create_task(_survive("Progress", scout.run()))
            tasks.create_task(memory.run())
            if startup_voice:
                # In the background: until a bark is ready, its event goes to the talker instead.
                tasks.create_task(_survive("Barks", barks.prepare(startup_voice)))
            if tools:
                tasks.create_task(_survive("Wiki", _find_wiki(settings, database, tools)))
            if open_page:
                tasks.create_task(_survive("Open page", open_page.run()))
            if typed:
                tasks.create_task(_survive("Typing", typed_turns(bus)))
    finally:
        if tools and tools.research:
            await tools.research.aclose()
        database.close()
