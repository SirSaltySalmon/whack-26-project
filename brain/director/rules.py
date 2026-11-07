"""Decides when to speak. Pure and deterministic so every rule can be unit tested.

An LLM never decides this. Models only choose what to do inside a turn these rules started.
"""

from dataclasses import dataclass, field
from typing import Any

from brain.events import (
    Event,
    GameEvent,
    OverlayConnected,
    PlayerSpeech,
    PlayerStartedSpeaking,
    SettingsChanged,
    Tick,
)

# Names the observer's tracker publishes. They describe any game, so this stays game-agnostic.
_DANGER_RISING = frozenset({"danger_started", "danger_high"})
_DANGER_OVER = "danger_ended"


@dataclass(frozen=True)
class Say:
    """Speak fixed text, such as a cached bark."""

    text: str


@dataclass(frozen=True)
class AskTalker:
    """Answer the player. Their turn replaces whatever the partner was about to say."""

    transcript: str
    # When they began speaking (monotonic), so tools can look at what they were seeing then.
    started_at: float | None = None


@dataclass(frozen=True)
class ReactToEvent:
    """Have the fast LLM comment on something seen in the game."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AskQuestion:
    """Ask the player the next open question, if memory has one."""


@dataclass(frozen=True)
class CancelSpeech:
    """The player started talking, so drop any reply still being prepared."""


@dataclass(frozen=True)
class SetVoice:
    voice_id: str | None


Action = Say | AskTalker | ReactToEvent | AskQuestion | CancelSpeech | SetVoice


@dataclass
class DirectorState:
    bark_cooldown_s: float = 8.0
    question_gap_s: float = 90.0
    question_quiet_s: float = 20.0
    last_bark_at: float | None = None
    last_question_at: float | None = None
    # Stays None until the overlay connects, so nothing is asked with no one to answer it.
    last_activity_at: float | None = None
    turn_started_at: float | None = None
    in_danger: bool = False
    greeted: bool = False


def _may_ask(ts: float, state: DirectorState, proactive: bool) -> bool:
    if not proactive or state.in_danger or state.last_activity_at is None:
        return False
    if ts - state.last_activity_at < state.question_quiet_s:
        return False
    return state.last_question_at is None or ts - state.last_question_at >= state.question_gap_s


def decide(event: Event, state: DirectorState, proactive: bool) -> list[Action]:
    match event:
        case OverlayConnected():
            state.last_activity_at = event.ts
            # The overlay can reconnect during a session, and that shouldn't greet again.
            if state.greeted:
                return []
            state.greeted = True
            return [Say("Brain connected.")]
        case PlayerStartedSpeaking():
            state.last_activity_at = event.ts
            state.turn_started_at = event.ts
            return [CancelSpeech()]
        case PlayerSpeech():
            state.last_activity_at = event.ts
            started_at, state.turn_started_at = state.turn_started_at, None
            # Always answer the player, even when proactive hints are off.
            return [AskTalker(event.transcript, started_at)]
        case GameEvent():
            if event.name in _DANGER_RISING:
                state.in_danger = True
            elif event.name == _DANGER_OVER:
                state.in_danger = False
            if not proactive:
                return []
            cooling = (
                state.last_bark_at is not None
                and event.ts - state.last_bark_at < state.bark_cooldown_s
            )
            if cooling:
                return []
            state.last_bark_at = event.ts
            state.last_activity_at = event.ts
            # TODO(track 3): use the personality's pre-generated barks where they fit.
            return [ReactToEvent(event.name, event.data)]
        case Tick():
            if not _may_ask(event.ts, state, proactive):
                return []
            state.last_question_at = event.ts
            return [AskQuestion()]
        case SettingsChanged():
            # Sending the current voice again is harmless, so this needs no change tracking.
            return [SetVoice(getattr(event.settings, "voice_id", None))]
        case _:
            return []
