"""Fakes for the model clients: vision, text and scripted tool turns. See fakes.py."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from brain.llm.base import Detail, SchemaT, ToolCall, ToolDeclaration, ToolStep


@dataclass(frozen=True)
class VisionCall:
    prompt: str
    image: bytes
    media_type: str
    schema: type[BaseModel]
    max_tokens: int
    detail: Detail


# A dict validated into the schema asked for, a callable that returns one, or an error to raise.
VisionReply = Mapping[str, Any] | Callable[[VisionCall], Mapping[str, Any]] | Exception


class FakeVision:
    def __init__(self, reply: VisionReply) -> None:
        self.reply = reply
        self.calls: list[VisionCall] = []

    async def vision_json(
        self,
        prompt: str,
        image: bytes,
        media_type: str,
        schema: type[SchemaT],
        max_tokens: int,
        detail: Detail = "low",
    ) -> SchemaT:
        call = VisionCall(prompt, image, media_type, schema, max_tokens, detail)
        self.calls.append(call)
        if isinstance(self.reply, Exception):
            raise self.reply
        value = self.reply(call) if callable(self.reply) else self.reply
        return schema.model_validate(value)


class FakeTextLLM:
    """Streams `chunks`, or raises `error`. With `gate`, stays stuck until the gate is set."""

    def __init__(
        self,
        chunks: Iterable[str] = (),
        error: Exception | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.chunks = list(chunks)
        self.error = error
        self.gate = gate
        self.system = ""  # From the latest call
        self.prompts: list[str] = []
        self.max_tokens: list[int] = []

    async def stream_text(self, system: str, prompt: str, max_tokens: int) -> AsyncIterator[str]:
        self.system = system
        self.prompts.append(prompt)
        self.max_tokens.append(max_tokens)
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        for chunk in self.chunks:
            yield chunk


# A step is the next model response, an error to raise, or a coroutine function for a slow model.
ScriptStep = ToolStep | Exception | Callable[[], Awaitable[ToolStep]]


@dataclass(frozen=True)
class SentResults:
    results: tuple[tuple[ToolCall, str], ...]
    allow_tools: bool


class ScriptedToolLLM:
    """Plays back one scripted response per model call, across send and send_results."""

    def __init__(self, steps: Iterable[ScriptStep]) -> None:
        self._steps = deque(steps)
        self.system = ""  # From the latest chat
        self.tools: list[ToolDeclaration] = []
        self.max_tokens = 0
        self.sends: list[str] = []
        self.results: list[SentResults] = []

    @property
    def model_calls(self) -> int:
        return len(self.sends) + len(self.results)

    def tool_chat(
        self, system: str, tools: Sequence[ToolDeclaration], max_tokens: int
    ) -> "_ScriptedChat":
        self.system = system
        self.tools = list(tools)
        self.max_tokens = max_tokens
        return _ScriptedChat(self)

    async def next_step(self) -> ToolStep:
        if not self._steps:
            raise AssertionError("The model was called more times than the test scripted")
        step = self._steps.popleft()
        if isinstance(step, Exception):
            raise step
        return step if isinstance(step, ToolStep) else await step()


class _ScriptedChat:
    def __init__(self, llm: ScriptedToolLLM) -> None:
        self._llm = llm

    async def send(self, text: str) -> ToolStep:
        self._llm.sends.append(text)
        return await self._llm.next_step()

    async def send_results(
        self, results: Sequence[tuple[ToolCall, str]], allow_tools: bool = True
    ) -> ToolStep:
        self._llm.results.append(SentResults(tuple(results), allow_tools))
        return await self._llm.next_step()
