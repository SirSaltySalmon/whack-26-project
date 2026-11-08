"""Shared fakes, so every test runs with no keys, network, game or microphone.

Each one records what it was given, so a test can assert on what reached the outside world.
"""

import asyncio
import time
from collections import deque
from collections.abc import Iterable, Mapping

import numpy as np

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import Event
from brain.latency import Origin
from brain.memory.models import Fact, RememberResult, Source
from brain.perception.coords import CropRegion

# The model fakes live in fakes_llm.py, re-exported so tests keep importing them from here.
from brain.tests.fakes_llm import FakeTextLLM as FakeTextLLM
from brain.tests.fakes_llm import FakeVision as FakeVision
from brain.tests.fakes_llm import ScriptedToolLLM as ScriptedToolLLM
from brain.tests.fakes_llm import ScriptStep as ScriptStep
from brain.tests.fakes_llm import SentResults as SentResults
from brain.tests.fakes_llm import VisionCall as VisionCall
from brain.tests.fakes_llm import VisionReply as VisionReply
from brain.voice.barks import Bark
from shared.protocol import BrainMessage
from shared.protocol.messages import QuestionAsk, Rect, Settings


class FakeVoice:
    """Set `accepts` to False to act like a voice dropping a line because the player is talking.

    `said` and `played` hold every attempt, accepted or not.
    """

    def __init__(self, accepts: bool = True, live: Mapping[str, str] | None = None) -> None:
        self.accepts = accepts
        self.live = dict(live or {})
        self.said: list[str] = []
        self.played: list[Bark] = []
        # What each accepted or refused line reacted to, in order, for the latency tests.
        self.origins: list[Origin | None] = []
        self.voice_id: str | None = None

    async def say(self, text: str, *, origin: Origin | None = None) -> bool:
        self.said.append(text)
        self.origins.append(origin)
        return self.accepts

    async def play(self, bark: Bark, *, origin: Origin | None = None) -> bool:
        self.played.append(bark)
        self.origins.append(origin)
        return self.accepts

    async def set_voice(self, voice_id: str | None) -> None:
        self.voice_id = voice_id

    async def run(self) -> None:
        return

    def live_state(self) -> dict[str, str]:
        return dict(self.live)


class FakeBarkSynth:
    """Returns a little silence per line, and records every line it was asked for."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, str, int]] = []

    async def synthesize(self, text: str, voice_id: str, model: str, sample_rate: int) -> bytes:
        self.calls.append((text, voice_id, model, sample_rate))
        if self.fail:
            raise RuntimeError("quota exceeded")
        return bytes(sample_rate // 50 * 2)  # 20 ms


class FakeOverlay:
    def __init__(self, display_scale: float = 1.0, rects: Iterable[Rect] = ()) -> None:
        self.display_scale = display_scale
        self.pinned_display_scale: float | None = None
        self.settings = Settings()
        self.rects = tuple(rects)
        self.sent: list[BrainMessage] = []

    async def send(self, message: BrainMessage) -> None:
        self.sent.append(message)


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
        self.facts: dict[tuple[str, str], Fact] = {}
        self.remembered: list[tuple[str, str, str, str, float]] = []
        self.tentative_remembered: list[tuple[str, str]] = []
        self.released: list[str] = []
        self.answered: list[tuple[int | None, str, str | None]] = []
        self.forgotten: list[tuple[str, str]] = []

    async def wonder(self, subject: str, attribute: str, text: str) -> object | None:
        self.wondered.append((subject, attribute, text))
        return self.wonder_result

    async def take_question(self) -> QuestionAsk | None:
        self.questions_taken += 1
        return self._questions.popleft() if self._questions else None

    async def release_question(self, question_id: str) -> None:
        """The director couldn't say it, so it goes back in the queue."""
        self.released.append(question_id)

    async def answer_question(
        self, question_id: int | None, answer: str, correction: str | None = None
    ) -> RememberResult | None:
        """None as the id means the question just asked."""
        self.answered.append((question_id, answer, correction))
        return RememberResult("replaced")

    async def forget(self, subject: str, attribute: str) -> int:
        """The player said a remembered value is wrong without saying what's right."""
        self.forgotten.append((subject, attribute))
        return 1 if self.facts.pop((subject, attribute), None) is not None else 0

    async def record_partner_turn(self, text: str) -> None:
        self.partner_turns.append(text)

    async def context(self, live_state: Mapping[str, str], query: str | None = None) -> str:
        self.context_calls.append((dict(live_state), query))
        return self.context_text

    async def current_fact(self, subject: str, attribute: str) -> Fact | None:
        return self.facts.get((subject, attribute))

    async def remember(
        self,
        subject: str,
        attribute: str,
        value: str,
        source: Source,
        confidence: float,
        *,
        tentative: bool = False,
    ) -> RememberResult:
        """Stores the latest value as given. The trust rules have their own tests."""
        self.remembered.append((subject, attribute, value, source, confidence))
        if tentative:
            self.tentative_remembered.append((subject, attribute))
        fact = Fact(
            len(self.remembered),
            None,
            subject,
            attribute,
            value,
            source,
            confidence,
            tentative=tentative or confidence < 0.5,
            valid_from=time.time(),
        )
        self.facts[(subject, attribute)] = fact
        return RememberResult("stored", fact=fact)


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
