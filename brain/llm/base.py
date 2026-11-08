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


class TextLLM(Protocol):
    def stream_text(self, system: str, prompt: str, max_tokens: int) -> AsyncIterator[str]: ...


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
    """A single turn's conversation. It holds the history, because providers need it back as-is."""

    async def send(self, text: str) -> ToolStep: ...

    async def send_results(
        self, results: Sequence[tuple[ToolCall, str]], allow_tools: bool = True
    ) -> ToolStep: ...


class ToolLLM(Protocol):
    def tool_chat(
        self, system: str, tools: Sequence[ToolDeclaration], max_tokens: int
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
