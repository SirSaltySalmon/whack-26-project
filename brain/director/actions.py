"""What the rules can tell the director to do. Kept apart so rules.py stays about deciding."""

from dataclasses import dataclass, field
from typing import Any

from brain.latency import Origin


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
    # Where it was first seen, for the frame-to-voice latency log. Not part of what was decided.
    origin: Origin | None = field(default=None, compare=False)


@dataclass(frozen=True)
class PlayBark:
    """React with a pre-generated line, which skips the model and TTS."""

    kind: str  # A LineKind
    event: str  # The GameEvent name, for logs
    data: dict[str, Any]  # Passed on, in case there's no bark and it falls back
    # When the event happened, for the event-to-bark latency log. Not part of what was decided.
    ts: float | None = field(default=None, compare=False)
    origin: Origin | None = field(default=None, compare=False)


@dataclass(frozen=True)
class AskQuestion:
    """Ask the player the next open question, if memory has one."""


@dataclass(frozen=True)
class GiveAdvice:
    """Offer a short tip on what to do next. Skipped when the player turned hints off."""


@dataclass(frozen=True)
class CancelSpeech:
    """The player started talking, so drop any reply still being prepared."""


@dataclass(frozen=True)
class StopSpeaking:
    """The player paused the partner. Unlike CancelSpeech, this also stops a turn running a tool."""


@dataclass(frozen=True)
class SetVoice:
    voice_id: str | None


Action = (
    Say
    | AskTalker
    | ReactToEvent
    | PlayBark
    | AskQuestion
    | GiveAdvice
    | CancelSpeech
    | StopSpeaking
    | SetVoice
)
