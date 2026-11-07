"""Event types and the bus that connects perception, voice and the director."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    ts: float = field(default_factory=time.monotonic, kw_only=True)


@dataclass(frozen=True)
class OverlayConnected(Event):
    display_scale: float


@dataclass(frozen=True)
class GameEvent(Event):
    """Something noticed in the game. `name` is generic, or comes from the learned profile."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)
    # "observer", "reader" or "replay". Lets replay re-run readers without doubling their events.
    source: str = "observer"


@dataclass(frozen=True)
class ProfileUpdated(Event):
    """The learner saved new regions or readers, so they should be reloaded."""

    game: str


@dataclass(frozen=True)
class ReadersFailing(Event):
    """Learned readers keep failing, so they may be out of date."""

    game: str
    readers: tuple[str, ...]


@dataclass(frozen=True)
class PlayerSpeech(Event):
    transcript: str


@dataclass(frozen=True)
class PlayerSpeechPartial(Event):
    """The turn so far, while the player is still talking. It can change until PlayerSpeech."""

    transcript: str


@dataclass(frozen=True)
class PlayerMood(Event):
    """A rough read of the player's mood from their words and voice."""

    label: str
    valence: float
    intensity: float


@dataclass(frozen=True)
class PlayerStartedSpeaking(Event):
    """Barge-in signal from Deepgram Flux's StartOfTurn."""


@dataclass(frozen=True)
class CardClosedByPlayer(Event):
    card_id: str


@dataclass(frozen=True)
class CardPageChanged(Event):
    """The wiki window's page changed. The URL and title are untrusted website data."""

    card_id: str
    url: str
    title: str | None = None


@dataclass(frozen=True)
class QuestionAnswered(Event):
    question_id: str
    answer: str


@dataclass(frozen=True)
class SettingsChanged(Event):
    """The player changed a setting. Typed loosely so this module stays free of the protocol."""

    settings: BaseModel


@dataclass(frozen=True)
class VoicePreviewRequested(Event):
    """The player asked to hear the current voice from the Control Center."""

    text: str


@dataclass(frozen=True)
class Tick(Event):
    """Time passing. Lets the director's pure rules decide things no other event would prompt."""


class EventBus:
    """Fan-out queues. A slow subscriber loses its oldest events rather than stalling fast loops."""

    def __init__(self, max_queue: int = 256) -> None:
        self._max_queue = max_queue
        self._subscribers: list[asyncio.Queue[Event]] = []

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.append(queue)
        return queue

    def publish(self, event: Event) -> None:
        for queue in self._subscribers:
            if queue.full():
                dropped = queue.get_nowait()
                log.warning("Event queue full; dropped %s", type(dropped).__name__)
            queue.put_nowait(event)
