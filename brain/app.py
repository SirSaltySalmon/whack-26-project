"""Wires the components together and runs them until shutdown."""

import asyncio
import logging
from pathlib import Path

import uvicorn

from brain.capture.loop import CaptureLoop
from brain.capture.ring_buffer import RingBuffer
from brain.capture.source import default_live_source, live_frame_scale
from brain.capture.window import create_game_window
from brain.config import WS_HOST, Settings
from brain.control import ShutdownRequested, stop_when
from brain.control_wiring import StatusParts, build_control
from brain.danger_feed import forward_danger
from brain.debug_panel import BrainPanel
from brain.director.director import Director
from brain.director.personalities import load_personalities
from brain.director.why import ignore_decision
from brain.events import EventBus
from brain.game_setup import ensure_brief, name_game
from brain.hud import build_hud, live_state, send_debug_regions
from brain.learner.questions import plan_and_queue_questions
from brain.llm.factory import LLMFactory
from brain.loop_watch import watch_loop
from brain.memory.db import Database, connect
from brain.memory.embeddings import FastEmbedder
from brain.memory.notes import NoteWriter
from brain.memory.semantic import SemanticRecall
from brain.memory.service import MemoryService
from brain.memory.snapshot import connect_replay
from brain.parts import (
    find_wiki,
    make_agent_tools,
    make_bark_bank,
    make_observer,
    make_progress_scout,
    make_talker,
    make_tips,
    survive,
    tool_registry,
)
from brain.replay.source import ReplayLoop
from brain.replay.wiring import (
    ReplayDone,
    build_recording,
    exit_after,
    no_note_model,
    replay_talker,
)
from brain.server import MOMENTARY_SETTINGS, OverlayLink, create_app
from brain.voice.pipeline import SubtitleOnlyVoice, create_voice
from brain.voice.typed import typed_turns
from shared.protocol.messages import Settings as OverlaySettings

log = logging.getLogger(__name__)


async def run(
    settings: Settings,
    replay_dir: Path | None = None,
    typed: bool = False,
    record: bool = False,
    speed: float = 1.0,
    exit_when_done: bool = False,
    write_messages: Path | None = None,
    game_hint: str = "",
) -> None:
    bus = EventBus()
    link = OverlayLink(bus)
    # One factory, because limiters are per model and vision and deep notes can share a model.
    factory = LLMFactory(settings)
    # Before memory opens, because memory is filed under the game's title.
    settings, written = (
        (settings, None) if replay_dir else await name_game(settings, factory.deep, game_hint)
    )
    personalities = load_personalities()
    link.personalities = personalities.names
    link.voices = settings.voice_options
    # Replays are test and fallback runs: they start from a fixed snapshot and leave no trace.
    conn = connect_replay(settings.replay_snapshot) if replay_dir else connect(settings.db_path)
    database = Database(conn)
    # Replays recall by keywords only, so a stage fallback never waits on a model download.
    semantic = (
        None
        if replay_dir
        else SemanticRecall(
            database,
            bus,
            lambda: FastEmbedder(settings.embedding_model, settings.embedding_cache_dir),
            min_similarity=settings.recall_min_similarity,
        )
    )
    memory = MemoryService(
        database,
        bus,
        link.send,
        settings.game_title,
        NoteWriter(no_note_model if replay_dir else factory.deep),
        vault_dir=None if replay_dir else settings.vault_dir,
        note_interval_s=settings.note_interval_s,
        note_min_new_events=settings.note_min_new_events,
        question_answer_timeout_s=settings.question_answer_timeout_s,
        question_typed_timeout_s=settings.question_typed_timeout_s,
        question_max_turns=settings.question_max_turns,
        semantic=semantic,
    )
    await memory.start()
    saved = await memory.load_settings(OverlaySettings)
    link.settings = saved.model_copy(update=MOMENTARY_SETTINGS)
    if semantic:
        semantic.follow(link.settings)
    buffer = RingBuffer(settings.capture_fps * settings.ring_buffer_seconds)
    replay = ReplayLoop(replay_dir, buffer, bus, link, speed=speed) if replay_dir else None
    if not replay_dir:
        link.frame_scale_override = live_frame_scale()
    capture = replay or CaptureLoop(
        default_live_source(),
        buffer,
        link,
        settings.capture_fps,
        create_game_window(settings.game_process),
    )
    # Replays are tests and fallbacks, so they never spend money on vision.
    scout = (
        None
        if replay_dir
        else make_progress_scout(settings, factory, buffer, link, memory, database)
    )
    observer = (
        None
        if replay_dir
        else make_observer(settings, factory, buffer, link, bus, scout.notice if scout else None)
    )
    if observer is None:
        # Nothing would wake it.
        scout = None
    recorder, message_log = build_recording(
        settings, buffer, bus, link, record and not replay_dir, write_messages
    )
    # Replay never opens the mic, which would mix live speech into the recording, and never
    # spends TTS characters. Subtitles also keep two runs' messages comparable.
    voice = SubtitleOnlyVoice(link) if replay_dir else create_voice(settings, bus, link)
    # Readers run on replays too, so a reader change shows up in a replayed session.
    hud = build_hud(settings, factory, database, buffer, link, bus, observer, live=not replay_dir)

    async def talker_context(query: str) -> str:
        # What the partner hears and sees now, on top of what memory knows.
        observed = observer.live_state() if observer else {}
        live = live_state(voice.live_state(), hud.readers.live_state(), observed)
        return await memory.context(live, query)

    async def on_spoken(text: str) -> None:
        if recorder:
            recorder.on_partner_said(text)
        await memory.record_partner_turn(text)

    live_talker = None if replay_dir else make_talker(factory)
    if replay_dir:
        talker = await replay_talker(settings, lambda: make_talker(factory), replay_dir)
    else:
        talker = live_talker
    # Replays never spend money on vision, so they get plain replies with no tools.
    tools, open_page = (
        make_agent_tools(settings, factory, buffer, link, bus, memory, talker_context)
        if live_talker is not None
        else (None, None)
    )

    # Replays get no barks: they'd spend TTS, and a cached one would replace a recorded line.
    barks = None if replay_dir else make_bark_bank(settings, personalities)

    def voice_id() -> str | None:
        # Matches the voice PipecatVoice picks: the player's choice, then the configured default.
        return link.settings.voice_id or settings.elevenlabs_voice_id

    panel = BrainPanel() if settings.debug_regions else None
    director = Director(
        bus,
        voice,
        proactive=lambda: link.settings.proactive,
        talker=talker,
        personality=lambda: link.settings.personality,
        custom_instructions=lambda: link.settings.custom_instructions,
        max_words=settings.talker_max_words,
        context=talker_context,
        on_spoken=on_spoken,
        agent=live_talker if tools else None,
        tip_llm=make_tips(factory) if live_talker else None,
        tools=tool_registry(tools, observer),
        personalities=personalities,
        take_question=memory.take_question,
        release_question=memory.release_question,
        pacing=link.settings.pacing,
        advice_after_learning_s=settings.advice_after_learning_s,
        page_excerpt=open_page.excerpt_for if open_page else None,
        barks=barks,
        voice_id=voice_id,
        on_decision=panel.note_decision if panel else ignore_decision,
    )
    startup_voice = voice_id()

    parts = StatusParts(replay_dir is not None, voice, observer, talker, tools, voice_id)
    control, stop = build_control(settings, link, bus, database, memory, parts, talker_context)

    config = uvicorn.Config(
        create_app(link, control), host=WS_HOST, port=settings.brain_port, log_level="warning"
    )
    server = uvicorn.Server(config)

    log.info("Brain listening on ws://%s:%s/ws", WS_HOST, settings.brain_port)
    try:
        async with asyncio.TaskGroup() as tasks:
            for name, part in (("Recorder", recorder), ("Message log", message_log)):
                if part:
                    tasks.create_task(survive(name, part.run()))
            tasks.create_task(server.serve())
            tasks.create_task(stop_when(stop))
            tasks.create_task(survive("Loop watch", watch_loop()))
            tasks.create_task(director.run())
            tasks.create_task(survive("Danger feed", forward_danger(bus, link.send)))
            tasks.create_task(capture.run())
            tasks.create_task(survive("Voice", voice.run()))
            if observer:
                tasks.create_task(survive("Observer", observer.run()))
            tasks.create_task(survive("Readers", hud.readers.run()))
            if hud.learner:
                tasks.create_task(survive("Learner", hud.learner.run()))
            if settings.debug_regions:
                debug = send_debug_regions(hud.readers, link.send)
                tasks.create_task(survive("Debug view", debug))
            if panel:
                tasks.create_task(survive("Debug panel", panel.run(bus, link.send)))
            if scout:
                tasks.create_task(survive("Progress", scout.run()))
            tasks.create_task(memory.run())
            if semantic:
                tasks.create_task(survive("Memory search", semantic.run()))
            if barks and startup_voice:
                # In the background: until a bark is ready, its event goes to the talker instead.
                tasks.create_task(survive("Barks", barks.prepare(startup_voice)))
            if not replay_dir:

                async def brief_then_questions() -> None:
                    # The questions are drafted from the brief, so they wait for it.
                    await ensure_brief(
                        database,
                        settings.game_title,
                        factory.deep,
                        game_hint,
                        written,
                        settings.brief_timeout_s,
                    )
                    await plan_and_queue_questions(
                        database,
                        memory,
                        settings.game_title,
                        factory.deep,
                        settings.planned_questions_max,
                        settings.brief_timeout_s,
                    )

                tasks.create_task(survive("Game brief", brief_then_questions()))
            if tools:
                tasks.create_task(survive("Wiki", find_wiki(settings, database, tools, control)))
            if open_page:
                tasks.create_task(survive("Open page", open_page.run()))
            if typed:
                tasks.create_task(survive("Typing", typed_turns(bus)))
            if replay and exit_when_done:
                tasks.create_task(exit_after(replay.finished, settings.replay_exit_grace_s))
    except* ReplayDone:
        log.info("Replay finished; exiting")
    except* ShutdownRequested:
        log.info("Stopped from the Control Center")
    finally:
        hud.close()
        if tools and tools.research:
            await tools.research.aclose()
        database.close()
