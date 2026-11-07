"""Decides when to speak. Pure and deterministic so every rule can be unit tested.

TODO(track 3): add priorities, speech budgets and the question budget.
"""

from dataclasses import dataclass, field
from typing import Any

from brain.events import Event, GameEvent, OverlayConnected, PlayerSpeech


@dataclass(frozen=True)
class Say:
    """Speak fixed text, such as a cached bark."""

    text: str


@dataclass(frozen=True)
class AskTalker:
    """Generate a reply with the fast LLM."""

    transcript: str


@dataclass(frozen=True)
class ReactToEvent:
    """Have the fast LLM comment on something seen in the game."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)


Action = Say | AskTalker | ReactToEvent


@dataclass
class DirectorState:
    bark_cooldown_s: float = 8.0
    last_bark_at: float | None = None


def decide(event: Event, state: DirectorState, proactive: bool) -> list[Action]:
    match event:
        case OverlayConnected():
            return [Say("Brain connected.")]
        case PlayerSpeech():
            # Always answer the player, even when proactive hints are off.
            return [AskTalker(event.transcript)]
        case GameEvent():
            if not proactive:
                return []
            cooling = (
                state.last_bark_at is not None
                and event.ts - state.last_bark_at < state.bark_cooldown_s
            )
            if cooling:
                return []
            state.last_bark_at = event.ts
            # TODO(track 3): use the personality's pre-generated barks where they fit.
            return [ReactToEvent(event.name, event.data)]
        case _:
            return []
