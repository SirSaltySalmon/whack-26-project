"""Plain records shared by the memory modules."""

from dataclasses import dataclass, field
from typing import Any, Literal

Source = Literal["player", "observed", "wiki"]
NoteKind = Literal["rolling", "recap"]
Speaker = Literal["player", "partner"]
RememberOutcome = Literal["stored", "confirmed", "replaced", "ignored", "conflict", "uncertain"]


@dataclass(frozen=True)
class Fact:
    id: int
    game: str | None
    subject: str
    attribute: str
    value: str
    source: Source
    confidence: float
    tentative: bool
    valid_from: float
    valid_to: float | None = None


@dataclass(frozen=True)
class Question:
    id: int
    game: str | None
    text: str
    options: list[str] = field(default_factory=list)
    fact_ids: list[int] = field(default_factory=list)
    status: Literal["open", "answered", "dropped"] = "open"
    answer: str | None = None
    asked_at: float | None = None
    subject: str | None = None
    attribute: str | None = None


@dataclass(frozen=True)
class RememberResult:
    """What a write did, so callers can show a toast or queue a question without re-querying."""

    outcome: RememberOutcome
    fact: Fact | None = None  # The current fact. None only when a fact was ignored or dismissed.
    closed: list[Fact] = field(default_factory=list)
    question: Question | None = None


@dataclass(frozen=True)
class Session:
    id: int
    game: str
    started_at: float
    ended_at: float | None = None


@dataclass(frozen=True)
class LoggedEvent:
    id: int
    session_id: int
    ts: float
    name: str
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class Turn:
    speaker: Speaker
    text: str
    ts: float


@dataclass(frozen=True)
class Note:
    id: int
    session_id: int
    kind: NoteKind
    body: str
    from_ts: float
    to_ts: float
    created_at: float


@dataclass(frozen=True)
class GameProfile:
    game: str
    brief: str = ""
    data: dict[str, Any] = field(default_factory=dict)


RecallMode = Literal["keyword", "hybrid", "semantic"]


@dataclass(frozen=True)
class Hit:
    """Something recall found. `key` names the fact or note, so the same one found by keywords
    and by meaning counts once."""

    key: tuple[Literal["fact", "note"], int]
    text: str
