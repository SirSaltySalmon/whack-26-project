"""Builds the Control Center's link for a run, so brain/app.py stays a short list of parts."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from brain.agent.handlers import AgentTools
from brain.config import Settings
from brain.control import ControlLink
from brain.events import EventBus
from brain.llm.base import TextLLM
from brain.memory.browse import browse
from brain.memory.db import Database
from brain.memory.service import MemoryService
from brain.perception.observer import Observer
from brain.server import OverlayLink
from brain.voice.pipeline import SubtitleOnlyVoice, Voice
from shared.protocol.control import BrainStatus


@dataclass(frozen=True)
class StatusParts:
    """The run's optional parts. Read when status is asked for, since the wiki is found later."""

    replay: bool
    voice: Voice
    observer: Observer | None
    talker: TextLLM | None
    tools: AgentTools | None
    voice_id: Callable[[], str | None]

    def status(self, settings: Settings, memory: MemoryService) -> BrainStatus:
        listening = not isinstance(self.voice, SubtitleOnlyVoice)
        research = self.tools.research if self.tools else None
        return BrainStatus(
            mode="replay" if self.replay else "live",
            game_title=settings.game_title,
            session_id=memory.session.id,
            watching=self.observer is not None,
            listening=listening,
            speaking=listening
            and settings.elevenlabs_api_key is not None
            and bool(self.voice_id()),
            talking=self.talker is not None,
            tools=self.tools is not None,
            wiki_url=research.site.api_url if research else None,
        )


def build_control(
    settings: Settings,
    link: OverlayLink,
    bus: EventBus,
    database: Database,
    memory: MemoryService,
    parts: StatusParts,
    recall: Callable[[str], Awaitable[str]],
) -> tuple[ControlLink, asyncio.Event]:
    """The link, and the event that is set when the Control Center asks the brain to stop."""
    stop = asyncio.Event()
    control = ControlLink(
        link,
        bus,
        browse=lambda text, history, limit: database.run(
            lambda conn: browse(conn, settings.game_title, text, history, limit)
        ),
        recall=recall,
        status=lambda: parts.status(settings, memory),
        shutdown=stop.set,
    )
    link.mirror = control.mirror
    return control, stop
