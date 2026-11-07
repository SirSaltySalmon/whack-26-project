"""Provider-neutral LLM interfaces. Nothing outside brain/llm imports a vendor SDK."""

import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Protocol, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMUnavailableError(RuntimeError):
    """No call was possible: no key, or over quota. Fall back to barks or stay quiet."""


class LLMEmptyResponseError(RuntimeError):
    """The model returned nothing usable, for example because a safety filter blocked it."""


class TextLLM(Protocol):
    def stream_text(self, system: str, prompt: str, max_tokens: int) -> AsyncIterator[str]: ...


class VisionLLM(Protocol):
    async def vision_json(
        self, prompt: str, image: bytes, media_type: str, schema: type[SchemaT], max_tokens: int
    ) -> SchemaT: ...


class PointTarget(BaseModel):
    """Ask vision models for boxes in this form; convert with brain.perception.coords."""

    label: str
    box_2d: list[float]  # [ymin, xmin, ymax, xmax], 0-1000, relative to the image sent


class RateLimiter:
    """Refuses instead of waiting: on the voice path a late reply is worse than a bark."""

    def __init__(
        self, requests_per_minute: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = requests_per_minute
        self._clock = clock
        self._calls: deque[float] = deque()

    def try_acquire(self) -> bool:
        now = self._clock()
        while self._calls and now - self._calls[0] >= 60.0:
            self._calls.popleft()
        if len(self._calls) >= self._limit:
            return False
        self._calls.append(now)
        return True
