"""Builds a run's optional parts. Each can be missing, such as with no key, so each logs why."""

import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any
from urllib.parse import urlparse

from brain.agent.focus_tool import watch_tool
from brain.agent.handlers import AgentLimits, AgentMemory, AgentTools
from brain.agent.tools import ToolRegistry
from brain.capture.ring_buffer import RingBuffer
from brain.config import Settings
from brain.control import ControlLink
from brain.director.personalities import PersonalityBook
from brain.events import EventBus
from brain.learner.progress import ProgressScout
from brain.learner.questions import planned_progress_question
from brain.llm.base import LLMUnavailableError
from brain.llm.claude import ClaudeClient
from brain.llm.factory import LLMFactory
from brain.llm.gemini import GeminiClient
from brain.memory.db import Database
from brain.memory.service import MemoryService
from brain.perception.focus import Focus, FocusIntervals
from brain.perception.observation import Observation
from brain.perception.observer import Observer
from brain.perception.tracker import ObservationTracker
from brain.research import ExaSearch, WikiResearch
from brain.research.open_page import OpenPage
from brain.research.wiki_cache import WikiCache
from brain.server import OverlayLink
from brain.switches import is_off
from brain.voice.barks import BarkBank, ElevenLabsSynth

log = logging.getLogger(__name__)


def make_talker(factory: LLMFactory) -> ClaudeClient | GeminiClient | None:
    try:
        return factory.talker()
    except LLMUnavailableError as exc:
        log.warning("Talker disabled: %s", exc)
        return None


def make_tips(factory: LLMFactory) -> ClaudeClient | GeminiClient | None:
    """None means tips use the talker, which doesn't think first."""
    try:
        return factory.tips()
    except LLMUnavailableError as exc:
        log.warning("Tips use the talker: %s", exc)
        return None


def make_agent_tools(
    settings: Settings,
    factory: LLMFactory,
    buffer: RingBuffer,
    link: OverlayLink,
    bus: EventBus,
    memory: AgentMemory,
    context: Callable[[str], Awaitable[str]],
) -> tuple[AgentTools, OpenPage]:
    """The player-turn tools, and the open wiki page they may read, on the game's wiki only."""
    tools = AgentTools(
        buffer,
        link,
        factory.vision,
        factory.deep,
        memory,
        context,
        AgentLimits(
            settings.mask_padding_px,
            settings.closeup_max_edge_px,
            settings.look_max_frame_age_s,
            settings.pointer_ttl_ms,
        ),
        look_vision=factory.closeup,
    )

    def wiki_host() -> str | None:
        # None until the wiki is found in the background, and then no page is read.
        research = tools.research
        return urlparse(research.site.info.server).hostname if research else None

    open_page = OpenPage(bus, link.send, wiki_host)
    tools.open_page = open_page
    return tools, open_page


def make_observer(
    settings: Settings,
    factory: LLMFactory,
    buffer: RingBuffer,
    link: OverlayLink,
    bus: EventBus,
    on_observation: Callable[[Observation, float], None] | None = None,
) -> Observer | None:
    if is_off(settings, "observer"):
        log.warning("Not watching the screen: turned off for this run")
        return None
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
        watching=lambda: link.settings.vision_enabled,
    )


def make_progress_scout(
    settings: Settings,
    factory: LLMFactory,
    buffer: RingBuffer,
    link: OverlayLink,
    memory: MemoryService,
    database: Database,
) -> ProgressScout | None:
    if is_off(settings, "scout"):
        log.warning("Not guessing the player's progress: turned off for this run")
        return None
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
        # The game's own planned question beats one drafted from a single frame.
        planned_question=lambda: planned_progress_question(database, settings.game_title),
    )


def tool_registry(tools: AgentTools | None, observer: Observer | None) -> ToolRegistry | None:
    if tools is None:
        return None
    # Only offered while something is watching, or the boost would do nothing.
    return tools.registry().including(watch_tool(observer.focus)) if observer else tools.registry()


async def find_wiki(
    settings: Settings, database: Database, tools: AgentTools, control: ControlLink
) -> None:
    """In the background, so a slow or dead wiki can't hold up the brain's start."""
    if is_off(settings, "wiki"):
        log.warning("No wiki lookups: turned off for this run")
        return
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
        await control.push_status()


def make_bark_bank(settings: Settings, book: PersonalityBook) -> BarkBank:
    key = settings.elevenlabs_api_key
    if key is None:
        log.info("No ElevenLabs key, so barks are never generated; cached ones still play")
    synth = ElevenLabsSynth(key.get_secret_value()) if key else None
    return BarkBank(book, synth, settings.barks_dir, settings.tts_model, settings.tts_sample_rate)


async def survive(name: str, work: Coroutine[Any, Any, None]) -> None:
    """Keeps a failure in an optional part, such as no audio device, from ending the brain."""
    try:
        await work
    except Exception:
        log.exception("%s stopped; carrying on without it", name)
