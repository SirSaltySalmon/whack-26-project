"""Runs the real director on a real bus with fakes around it, so its speech slot is exercised."""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from contextlib import asynccontextmanager

from brain.agent.tools import Tool, ToolRegistry
from brain.director.director import Director
from brain.director.personalities import Personality, PersonalityBook
from brain.events import Event, EventBus, OverlayConnected, Tick
from brain.llm.base import ToolStep
from brain.tests.fakes import FakeMemory, FakeOverlay, FakeTextLLM, FakeVoice, ScriptedToolLLM
from brain.voice.barks import BarkBank
from shared.protocol.messages import Pacing

QUIET_S = 20.0
GAP_S = 90.0
TONE = "Calm and unhurried."
LOOKING = "Looking."
DONE = "Done."
UNAVAILABLE = "Can't right now."
# One line per kind, so a test knows exactly which line a turn counter will land on.
BOOK = PersonalityBook(
    default="calm",
    personalities={
        "calm": Personality(
            tone=TONE,
            lines={"looking": [LOOKING], "done": [DONE], "unavailable": [UNAVAILABLE]},
        )
    },
)


async def settle(rounds: int = 50) -> None:
    """Lets the director's tasks run until they're all waiting on something.

    No real time passes, so a test can say something never happened without racing it.
    """
    for _ in range(rounds):
        await asyncio.sleep(0)


async def until(check: Callable[[], bool], timeout_s: float = 2.0) -> None:
    """For waits settle() can't cover, such as the director retrying a line on a real timer."""
    deadline = time.monotonic() + timeout_s
    while not check():
        assert time.monotonic() < deadline, "Timed out waiting for the condition"
        await asyncio.sleep(0.001)


class Stuck:
    """A model call that hangs until released, for use as a ScriptedToolLLM step."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.gate = asyncio.Event()
        self.started = False
        self.cancelled = False

    async def __call__(self) -> ToolStep:
        self.started = True
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return ToolStep(self.reply)


class Rig:
    def __init__(
        self,
        *,
        voice: FakeVoice | None = None,
        talker: FakeTextLLM | None = None,
        agent: ScriptedToolLLM | None = None,
        tip_llm: object | None = None,
        tools: Iterable[Tool] = (),
        memory: FakeMemory | None = None,
        context: Callable[[str], Awaitable[str]] | None = None,
        proactive: bool = True,
        quiet_s: float = QUIET_S,
        gap_s: float = GAP_S,
        bark_events: Mapping[str, str] | None = None,
        page_excerpt: Callable[[str], str | None] | None = None,
        barks: BarkBank | None = None,
        voice_id: str | None = None,
        advice_gap_s: float = 0.0,  # Off unless a test is about advice
        advice_quiet_s: float = 20.0,
        advice_first_s: float = 90.0,
        advice_after_learning_s: float = 15.0,
        event_gap_s: float = 8.0,
    ) -> None:
        self.bus = EventBus()
        self.voice = voice or FakeVoice()
        self.overlay = FakeOverlay()
        self.spoken: list[str] = []
        # The director's clock reads the latest published event's time, so a line it says lands
        # on the same timeline as the events a test publishes.
        self.now = time.monotonic()
        self.director = Director(
            self.bus,
            self.voice,
            proactive=lambda: proactive,
            talker=talker,
            context=context,
            on_spoken=self._on_spoken,
            agent=agent,
            tip_llm=tip_llm,  # type: ignore[arg-type]
            tools=ToolRegistry(tools),
            personalities=BOOK,
            take_question=memory.take_question if memory else None,
            release_question=memory.release_question if memory else None,
            pacing=Pacing(
                event_gap_s=event_gap_s,
                question_gap_s=gap_s,
                question_quiet_s=quiet_s,
                advice_gap_s=advice_gap_s,
                advice_quiet_s=advice_quiet_s,
                advice_first_s=advice_first_s,
            ),
            advice_after_learning_s=advice_after_learning_s,
            page_excerpt=page_excerpt,
            barks=barks,
            voice_id=lambda: voice_id,
            bark_events=bark_events or {},
            clock=lambda: self.now,
        )

    async def _on_spoken(self, text: str) -> None:
        self.spoken.append(text)

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """Runs the director's loop, and fails the test if the loop has stopped by the end."""
        task = asyncio.create_task(self.director.run())
        await settle()
        try:
            yield
            await settle()
            assert not task.done(), "The director's loop stopped"
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await settle()

    async def publish(self, event: Event) -> None:
        self.now = event.ts
        self.bus.publish(event)
        await settle()

    async def bring_up_a_question(self) -> None:
        """Connects the overlay, then ticks once the rules allow asking."""
        await self.publish(OverlayConnected(display_scale=1.0, ts=100.0))
        await self.publish(Tick(ts=100.0 + QUIET_S))
