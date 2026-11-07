"""Runs the rules against the event bus and carries out their actions.

Deciding stays instant because speech runs in its own task. There's one speech slot: a player turn
replaces whatever is in it, the start of their next turn cancels it, and anything else is skipped
while it's busy. A cancelled turn doesn't take back a pointer or card it has already shown.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from brain.agent.tools import ToolRegistry, TurnContext
from brain.agent.turn import run_turn
from brain.director.personalities import LineKind, PersonalityBook, load_personalities
from brain.director.rules import (
    Action,
    AskQuestion,
    AskTalker,
    CancelSpeech,
    DirectorState,
    ReactToEvent,
    Say,
    SetVoice,
    decide,
)
from brain.director.talker import event_prompt, reply
from brain.events import Event, EventBus, Tick
from brain.llm.base import LLMEmptyResponseError, LLMUnavailableError, TextLLM, ToolLLM
from brain.voice.pipeline import Voice
from shared.protocol import BrainMessage
from shared.protocol.messages import QuestionAsk

log = logging.getLogger(__name__)

TICK_INTERVAL_S = 5.0


class Director:
    def __init__(
        self,
        bus: EventBus,
        voice: Voice,
        proactive: Callable[[], bool],
        talker: TextLLM | None = None,
        personality: Callable[[], str] = lambda: "supportive",
        max_words: int = 12,
        context: Callable[[str], Awaitable[str]] | None = None,
        on_spoken: Callable[[str], Awaitable[None]] | None = None,
        *,
        agent: ToolLLM | None = None,
        tools: ToolRegistry | None = None,
        personalities: PersonalityBook | None = None,
        take_question: Callable[[], Awaitable[QuestionAsk | None]] | None = None,
        send: Callable[[BrainMessage], Awaitable[None]] | None = None,
        question_gap_s: float = 90.0,
        question_quiet_s: float = 20.0,
    ) -> None:
        self._events = bus.subscribe()
        self._voice = voice
        self._proactive = proactive
        self._talker = talker
        self._personality = personality
        self._max_words = max_words
        self._context = context
        self._on_spoken = on_spoken
        self._agent = agent
        self._tools = tools
        self._personalities = personalities or load_personalities()
        self._take_question = take_question
        self._send = send
        self._state = DirectorState(
            question_gap_s=question_gap_s, question_quiet_s=question_quiet_s
        )
        self._slot: asyncio.Task[None] | None = None
        self._background: set[asyncio.Task[None]] = set()
        self._lines_said = 0

    async def run(self) -> None:
        ticker = asyncio.create_task(self._tick())
        try:
            while True:
                self._handle(await self._events.get())
        finally:
            ticker.cancel()
            self._cancel_slot()

    async def _tick(self) -> None:
        # Not published on the bus: only the rules care, and every subscriber would have to skip it.
        while True:
            await asyncio.sleep(TICK_INTERVAL_S)
            self._handle(Tick())

    def _handle(self, event: Event) -> None:
        for action in decide(event, self._state):
            self._dispatch(action)

    def _dispatch(self, action: Action) -> None:
        match action:
            case CancelSpeech():
                self._cancel_slot()
            case AskTalker():
                self._cancel_slot()
                self._slot = asyncio.create_task(self._perform_safely(action))
            case SetVoice():
                # Separate from speech, because a setting shouldn't wait for or cancel a reply.
                task = asyncio.create_task(self._perform_safely(action))
                self._background.add(task)
                task.add_done_callback(self._background.discard)
            case _:
                if self._slot is not None and not self._slot.done():
                    log.debug("Busy speaking; skipped %s", action)
                    return
                self._slot = asyncio.create_task(self._perform_safely(action))

    def _cancel_slot(self) -> None:
        if self._slot is not None and not self._slot.done():
            log.debug("Cancelling speech in progress")
            self._slot.cancel()

    async def _perform_safely(self, action: Action) -> None:
        try:
            await self._perform(action)
        except Exception:
            # One failed action must not leave the partner silent for good.
            log.exception("Director action failed: %s", action)

    async def _perform(self, action: Action) -> None:
        match action:
            case Say():
                await self._voice.say(action.text)
            case AskTalker():
                if self._agent is not None and self._tools is not None:
                    await self._player_turn(action, self._agent, self._tools)
                else:
                    await self._talk(action.transcript, query=action.transcript)
            case ReactToEvent():
                await self._talk(event_prompt(action.name, action.data), query=action.name)
            case AskQuestion():
                await self._ask_question()
            case SetVoice():
                await self._voice.set_voice(action.voice_id)
            case CancelSpeech():
                self._cancel_slot()

    def _line(self, kind: LineKind) -> str:
        self._lines_said += 1
        return self._personalities.line(self._personality(), kind, self._lines_said)

    async def _speak(self, text: str) -> None:
        # Only what was really accepted goes into memory, or the partner would remember saying it.
        if await self._voice.say(text) and self._on_spoken:
            await self._on_spoken(text)

    async def _player_turn(self, action: AskTalker, agent: ToolLLM, tools: ToolRegistry) -> None:
        started = time.monotonic()
        context = await self._gather_context(action.transcript)
        name = self._personality()

        async def looking() -> None:
            # The result takes seconds, and silence would read as not having heard them.
            await self._voice.say(self._line("looking"))

        try:
            text = await run_turn(
                agent,
                tools,
                action.transcript,
                name,
                self._personalities.tone(name),
                self._max_words,
                context,
                TurnContext(action.started_at),
                looking,
                self._line("done"),
                hints=self._proactive(),
            )
        except (LLMUnavailableError, LLMEmptyResponseError) as exc:
            log.warning("Player turn unavailable: %s", exc)
            text = self._line("unavailable")
        except Exception:
            # A vendor error of any kind still gets an answer rather than silence.
            log.exception("Player turn failed")
            text = self._line("unavailable")
        log.info("Latency: player turn took %.0f ms", (time.monotonic() - started) * 1000)
        if text:
            await self._speak(text)
        else:
            log.warning("Player turn produced no reply for: %s", action.transcript)

    async def _ask_question(self) -> None:
        if self._take_question is None:
            return
        question = await self._take_question()
        if question is None:
            return
        # Shown either way, because take_question has already marked it asked.
        if self._send is not None:
            await self._send(question)
        await self._speak(question.text)

    async def _talk(self, prompt: str, query: str) -> None:
        if self._talker is None:
            log.warning("No talker LLM configured; ignoring: %s", prompt)
            return
        context = await self._gather_context(query)
        name = self._personality()
        text = await reply(
            self._talker,
            prompt,
            name,
            self._max_words,
            context,
            self._personalities.tone(name),
            hints=self._proactive(),
        )
        if text:
            await self._speak(text)

    async def _gather_context(self, query: str) -> str:
        if self._context is None:
            return ""
        try:
            return await self._context(query)
        except Exception:
            # A reply without memory beats no reply at all.
            log.exception("Couldn't build the talker's context")
            return ""
