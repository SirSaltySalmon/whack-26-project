"""A stand-in for the Gemini SDK's client, so GeminiClient can be tested with no network."""

from collections import deque
from collections.abc import AsyncIterator, Iterable
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from google.genai import errors, types

from brain.llm.base import RateLimiter
from brain.llm.gemini import GeminiClient


class FakeModels:
    def __init__(self, replies: Iterable[Any]) -> None:
        self.replies = deque(replies)
        self.calls: list[SimpleNamespace] = []

    def _next(self) -> Any:
        reply = self.replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def generate_content(self, model: str, contents: Any, config: Any) -> Any:
        # A copy, because a chat keeps appending to the same list after this returns.
        kept = list(contents) if isinstance(contents, list) else contents
        self.calls.append(SimpleNamespace(model=model, contents=kept, config=config))
        return self._next()

    async def generate_content_stream(self, model: str, contents: Any, config: Any) -> Any:
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        reply = self._next()

        async def chunks() -> AsyncIterator[Any]:
            for chunk in reply:
                if isinstance(chunk, Exception):
                    raise chunk
                yield SimpleNamespace(text=chunk)

        return chunks()


def gemini(*replies: Any, rpm: int = 100) -> tuple[GeminiClient, FakeModels]:
    """Each reply is a response, or an error to raise. For streams, a list of chunks."""
    models = FakeModels(replies)
    fake_sdk = SimpleNamespace(aio=SimpleNamespace(models=models))
    # Building the SDK's real client costs nearly a second, which adds up over a test suite.
    with patch("brain.llm.gemini.genai.Client", return_value=fake_sdk):
        client = GeminiClient("test-model", "test-key", RateLimiter(rpm))
    return client, models


def api_error(code: int) -> errors.APIError:
    error_type = errors.ClientError if code < 500 else errors.ServerError
    return error_type(code, {"error": {"code": code, "message": "nope", "status": "NOPE"}})


def model_turn(*parts: types.Part) -> SimpleNamespace:
    content = types.Content(role="model", parts=list(parts))
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)])
