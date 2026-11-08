"""Provider-neutral LLM interfaces. Nothing outside brain/llm imports a vendor SDK."""

import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# How closely a vision model should look. Low is the default; high is for when the player asks.
Detail = Literal["low", "high"]


class LLMUnavailableError(RuntimeError):
    """No call was possible: no key, or over quota. Fall back to barks or stay quiet."""


class LLMEmptyResponseError(RuntimeError):
    """The model returned nothing usable, for example because a safety filter blocked it."""


@dataclass(frozen=True)
class SystemPart:
    """One block of a system prompt. `cache` asks the vendor to cache the prompt up to and
    including this block, so it should only mark text that stays the same from call to call."""

    text: str
    cache: bool = False


# A plain string, or blocks in order: a stable, cached start, then what changes every call.
System = str | tuple[SystemPart, ...]


def system_text(system: System) -> str:
    """The whole prompt as one string, for vendors and fakes that take plain text."""
    if isinstance(system, str):
        return system
    return "\n\n".join(part.text for part in system if part.text)


@dataclass(frozen=True)
class ChatTurn:
    """One earlier message: the player's words or a note as `user`, the partner's line as
    `assistant`. Sent as plain text, so no earlier turn's thinking ever goes back to the model."""

    role: Literal["user", "assistant"]
    text: str


# The APIs want a user message first, and a stretch of conversation can open with the partner.
OPENING_LINE = "(Earlier in this conversation.)"


def merged_turns(history: Sequence[ChatTurn]) -> list[ChatTurn]:
    """Turns from the same side joined into one, with a user line first if the partner opened."""
    merged: list[ChatTurn] = []
    for turn in history:
        if not turn.text.strip():
            continue
        if merged and merged[-1].role == turn.role:
            merged[-1] = ChatTurn(turn.role, f"{merged[-1].text}\n{turn.text}")
        else:
            merged.append(turn)
    if merged and merged[0].role == "assistant":
        merged.insert(0, ChatTurn("user", OPENING_LINE))
    return merged


class TextLLM(Protocol):
    def stream_text(
        self, system: System, prompt: str, max_tokens: int, history: Sequence[ChatTurn] = ()
    ) -> AsyncIterator[str]: ...


class VisionLLM(Protocol):
    async def vision_json(
        self,
        prompt: str,
        image: bytes,
        media_type: str,
        schema: type[SchemaT],
        max_tokens: int,
        detail: Detail = "low",
    ) -> SchemaT: ...


@dataclass(frozen=True)
class ToolDeclaration:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class ToolStep:
    """One model response: tools it wants to run, or the text of its reply."""

    text: str
    calls: tuple[ToolCall, ...] = ()


class ToolChat(Protocol):
    """A single turn's conversation, after any earlier turns it was started with. It holds this
    turn's messages, because providers need them back as they were sent."""

    async def send(self, text: str) -> ToolStep: ...

    async def send_results(
        self, results: Sequence[tuple[ToolCall, str]], allow_tools: bool = True
    ) -> ToolStep: ...


class ToolLLM(Protocol):
    def tool_chat(
        self,
        system: System,
        tools: Sequence[ToolDeclaration],
        max_tokens: int,
        history: Sequence[ChatTurn] = (),
    ) -> ToolChat: ...


class ChatLLM(TextLLM, ToolLLM, Protocol):
    """Replies with or without tools, for a role such as tips that may need either."""


class PointTarget(BaseModel):
    """Ask vision models for boxes in this form; convert with brain.perception.coords."""

    label: str
    box_2d: list[float]  # [ymin, xmin, ymax, xmax], 0-1000, relative to the image sent


# The share of each model's budget that only calls the player is waiting on may use, so a busy
# observer or a background note is never why the player's own turn gets refused.
PLAYER_SHARE = 0.1


class Limiter(Protocol):
    def try_acquire(self) -> bool: ...


class RateLimiter:
    """Refuses instead of waiting: on the voice path a late reply is worse than a bark."""

    def __init__(
        self, requests_per_minute: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = requests_per_minute
        self._clock = clock
        self._calls: deque[float] = deque()

    def try_acquire(self, headroom: int = 0) -> bool:
        """`headroom` is how many of the minute's calls to leave unused for others."""
        now = self._clock()
        while self._calls and now - self._calls[0] >= 60.0:
            self._calls.popleft()
        if len(self._calls) >= self._limit - headroom:
            return False
        self._calls.append(now)
        return True

    def for_background(self) -> "BackgroundLimiter":
        return BackgroundLimiter(self, self._limit)


class BackgroundLimiter:
    """The same budget, less the player's share. A model allowed one call a minute keeps none."""

    def __init__(self, shared: RateLimiter, limit: int) -> None:
        self._shared = shared
        self._headroom = max(1, round(limit * PLAYER_SHARE)) if limit > 1 else 0

    def try_acquire(self) -> bool:
        return self._shared.try_acquire(self._headroom)
