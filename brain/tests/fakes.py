"""Shared fakes, so every test runs with no keys, network, game or microphone.

Each one records what it was given, so a test can assert on what reached the outside world.
"""

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from pydantic import BaseModel

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import Event
from brain.llm.base import Detail, SchemaT, ToolCall, ToolDeclaration, ToolStep
from brain.perception.coords import CropRegion
from brain.voice.barks import Bark
from shared.protocol import BrainMessage
from shared.protocol.messages import QuestionAsk, Rect


class FakeVoice:
    """Set `accepts` to False to act like a voice dropping a line because the player is talking.

    `said` and `played` hold every attempt, accepted or not.
    """

    def __init__(self, accepts: bool = True, live: Mapping[str, str] | None = None) -> None:
        self.accepts = accepts
        self.live = dict(live or {})
        self.said: list[str] = []
        self.played: list[Bark] = []
        self.voice_id: str | None = None

    async def say(self, text: str) -> bool:
        self.said.append(text)
        return self.accepts

    async def play(self, bark: Bark) -> bool:
        self.played.append(bark)
        return self.accepts

    async def set_voice(self, voice_id: str | None) -> None:
        self.voice_id = voice_id

    async def run(self) -> None:
        return

    def live_state(self) -> dict[str, str]:
        return dict(self.live)


class FakeOverlay:
    def __init__(self, display_scale: float = 1.0, rects: Iterable[Rect] = ()) -> None:
        self.display_scale = display_scale
        self.rects = tuple(rects)
        self.sent: list[BrainMessage] = []

    async def send(self, message: BrainMessage) -> None:
        self.sent.append(message)


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


class FakeMemory:
    """Hands out `questions` in order. `wonder` returns `wonder_result`, or None to mean known."""

    def __init__(
        self,
        questions: Iterable[QuestionAsk] = (),
        wonder_result: object | None = "opened",
        context_text: str = "",
    ) -> None:
        self._questions = deque(questions)
        self.wonder_result = wonder_result
        self.context_text = context_text
        self.wondered: list[tuple[str, str, str]] = []
        self.questions_taken = 0
        self.partner_turns: list[str] = []
        self.context_calls: list[tuple[dict[str, str], str | None]] = []

    async def wonder(self, subject: str, attribute: str, text: str) -> object | None:
        self.wondered.append((subject, attribute, text))
        return self.wonder_result

    async def take_question(self) -> QuestionAsk | None:
        self.questions_taken += 1
        return self._questions.popleft() if self._questions else None

    async def record_partner_turn(self, text: str) -> None:
        self.partner_turns.append(text)

    async def context(self, live_state: Mapping[str, str], query: str | None = None) -> str:
        self.context_calls.append((dict(live_state), query))
        return self.context_text


def make_frame(
    width: int = 320,
    height: int = 180,
    *,
    age_s: float = 0.0,
    ts: float | None = None,
    region: CropRegion | None = None,
    rects: Iterable[Rect] = (),
    fill: int = 128,
    image: np.ndarray | None = None,
) -> Frame:
    """A solid frame, taken just now by default. `ts` wins over `age_s`, `image` over the size."""
    pixels = image if image is not None else np.full((height, width, 3), fill, dtype=np.uint8)
    return Frame(
        ts=ts if ts is not None else time.monotonic() - age_s,
        image=pixels,
        overlay_rects=tuple(rects),
        region=region,
    )


def make_buffer(*frames: Frame, capacity: int | None = None) -> RingBuffer:
    buffer = RingBuffer(capacity or max(len(frames), 1))
    for frame in frames:
        buffer.push(frame)
    return buffer


def drain(queue: "asyncio.Queue[Event]") -> list[Event]:
    """Everything already published to a bus subscription, without waiting."""
    events: list[Event] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events
