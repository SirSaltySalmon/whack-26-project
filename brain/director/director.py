"""Runs the rules against the event bus and carries out their actions.
Deciding stays instant because speech runs in its own task. There's one speech slot: a player turn
replaces whatever is in it, the start of their next turn cancels it, and anything else is skipped
while it's busy. A cancelled turn doesn't take back a pointer or card it has already shown, and if
nothing was said for it, its words start the player's next turn (carry.py).

One exception: a turn that has started a tool, such as checking the screen, isn't cancelled.
Players talk while they wait, and cancelling meant the answer they asked for never came. It
finishes, says its answer once they stop talking, and then their next turn runs.

Pausing is the player's own choice, so it cancels the slot even mid-tool, with any turn queued.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping

from brain.agent.tools import ToolRegistry, TurnContext
from brain.director.carry import Carry
from brain.director.context import gather_context, player_context
from brain.director.lines import Lines, play_bark
from brain.director.personalities import PersonalityBook, load_personalities
from brain.director.questions import Questions
from brain.director.rules import (
    Action,
    AskQuestion,
    AskTalker,
    CancelSpeech,
    DirectorState,
    GiveAdvice,
    PartnerSpoke,
    PlayBark,
    ReactToEvent,
    Say,
    SetVoice,
    StopSpeaking,
    apply_pacing,
    decide,
)
from brain.director.slot import SpeechSlot
from brain.director.talker import event_prompt
from brain.director.turns import TIP_QUERY, Persona, give_tip, player_reply, talker_reply
from brain.events import Event, EventBus, Tick
from brain.latency import Origin
from brain.llm.base import ChatLLM, TextLLM, ToolLLM
from brain.voice.barks import BarkBank
from brain.voice.pipeline import Voice
from shared.protocol.messages import Pacing, QuestionAsk

log = logging.getLogger(__name__)

TICK_INTERVAL_S = 5.0
# How long an answer that took a tool, or a question, waits for the player to stop talking.
ANSWER_WAIT_S = 10.0
SPEAK_RETRY_S = 0.5


class Director:
    def __init__(
        self,
        bus: EventBus,
        voice: Voice,
        proactive: Callable[[], bool],
        talker: TextLLM | None = None,
        personality: Callable[[], str] = lambda: "supportive",
        max_words: int = 100,
        context: Callable[[str], Awaitable[str]] | None = None,
        on_spoken: Callable[[str], Awaitable[None]] | None = None,
        *,
        agent: ToolLLM | None = None,
        # Nobody waits on a tip, so it may come from a model that thinks first. Replays have none.
        tip_llm: ChatLLM | None = None,
        tools: ToolRegistry | None = None,
        personalities: PersonalityBook | None = None,
        take_question: Callable[[], Awaitable[QuestionAsk | None]] | None = None,
        release_question: Callable[[str], Awaitable[None]] | None = None,
        # The player's pacing settings at startup. Later changes arrive as SettingsChanged.
        pacing: Pacing | None = None,
        advice_after_learning_s: float = 15.0,
        page_excerpt: Callable[[str], str | None] | None = None,
        barks: BarkBank | None = None,
        voice_id: Callable[[], str | None] = lambda: None,
        custom_instructions: Callable[[], str] = lambda: "",
        bark_events: Mapping[str, str] | None = None,
        # Stamps ticks and spoken lines, so they share a clock with the events the rules see.
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._events = bus.subscribe()
        self._voice = voice
        self._proactive = proactive
        self._talker = talker
        self._custom_instructions = custom_instructions
        self._personality = personality
        self._max_words = max_words
        self._context = context
        self._on_spoken = on_spoken
        self._agent = agent
        self._tip_llm = tip_llm
        self._tools = tools
        self._personalities = personalities or load_personalities()
        self._lines = Lines(self._personalities, personality, voice_id, barks)
        self._questions = Questions(take_question, release_question)
        self._page_excerpt = page_excerpt
        self._clock = clock
        events = self._personalities.event_lines if bark_events is None else bark_events
        self._state = DirectorState(
            advice_after_learning_s=advice_after_learning_s, bark_events=events
        )
        apply_pacing(self._state, pacing or Pacing())
        self._slot = SpeechSlot()
        self._carry = Carry(clock)
        self._background: set[asyncio.Task[None]] = set()
        # True while the turn in the slot is running a tool, so it isn't cancelled.
        self.checking = False

    async def run(self) -> None:
        ticker = asyncio.create_task(self._tick())
        try:
            while True:
                self._handle(await self._events.get())
        finally:
            ticker.cancel()
            self._slot.cancel()

    async def _tick(self) -> None:
        # Not published on the bus: only the rules care, and every subscriber would have to skip it.
        while True:
            await asyncio.sleep(TICK_INTERVAL_S)
            self._handle(Tick(ts=self._clock()))

    def _handle(self, event: Event) -> None:
        if isinstance(event, Tick) and self._slot.busy():
            # A tick only brings up questions and tips, which a busy slot would skip, and deciding
            # one would spend its budget on nothing. The next tick tries again.
            return
        for action in decide(event, self._state):
            self._dispatch(action)

    def _dispatch(self, action: Action) -> None:
        match action:
            case CancelSpeech():
                if self.checking:
                    log.info("Player spoke during a check; it will still answer")
                    return
                self._cancel_slot()
            case StopSpeaking():
                # Not _cancel_slot(): a pause is the player's choice, so nothing carries over.
                log.info("Paused; stopping speech in progress")
                self._slot.cancel()
            case AskTalker():
                if self.checking and self._slot.busy():
                    self._slot.queue(self._perform_safely(action))
                    return
                self._cancel_slot()
                self._slot.start(self._perform_safely(self._carry.into(action)))
            case SetVoice():
                # Separate from speech, because a setting shouldn't wait for or cancel a reply.
                task = asyncio.create_task(self._perform_safely(action))
                self._background.add(task)
                task.add_done_callback(self._background.discard)
            case _:
                if self._slot.busy():
                    log.debug("Busy speaking; skipped %s", action)
                    return
                self._slot.start(self._perform_safely(action))

    def _cancel_slot(self) -> None:
        if self._slot.busy():
            # Keeps the words of a turn nothing was said for, to start the next one (carry.py).
            self._carry.cut_off()
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
                if await self._voice.say(action.text):
                    self._note_line()
            case AskTalker():
                with self._carry.answering(action):
                    if self._agent is not None and self._tools is not None:
                        await self._player_turn(action, self._agent, self._tools)
                    else:
                        await self._talk(action.transcript, query=action.transcript)
            case ReactToEvent():
                await self._talk(event_prompt(action.name, action.data), action.name, action.origin)
            case PlayBark():
                await self._play_bark(action)
            case AskQuestion():
                # Held like an answer: the player may be mid-sentence, and a question is worth it.
                await self._questions.ask(lambda text: self._speak(text, ANSWER_WAIT_S))
            case GiveAdvice():
                # Hints off means the player wants to find things out themselves.
                if self._proactive():
                    await self._advise()
            case SetVoice():
                await self._voice.set_voice(action.voice_id)
                # This task is already off the speech slot, so generating can take its time.
                await self._lines.prepare(action.voice_id)
            case CancelSpeech():
                self._cancel_slot()
            case StopSpeaking():
                self._slot.cancel()

    def _note_line(self) -> None:
        # The quiet stretch before a question or tip counts from lines really said, not attempted.
        self._carry.spoke()
        self._handle(PartnerSpoke(ts=self._clock()))

    async def _said(self, text: str) -> None:
        self._note_line()
        # Only what was really accepted goes into memory, or the partner would remember saying it.
        if self._on_spoken:
            await self._on_spoken(text)

    def _persona(self) -> Persona:
        name = self._personality()
        tone = self._personalities.tone(name)
        instructions = self._custom_instructions().strip()
        if instructions:
            tone += f"\nPlayer custom instructions (keep truth and trust rules): {instructions}"
        return Persona(name, tone, self._max_words, self._proactive())

    async def _play_bark(self, action: PlayBark) -> None:
        bark = self._lines.bark(action.kind)
        if bark is None:
            # Not generated yet, no ElevenLabs key, or no such line: react the slow way instead.
            await self._talk(event_prompt(action.event, action.data), action.event, action.origin)
        elif await play_bark(self._voice, bark, action):
            await self._said(bark.text)

    async def _speak(self, text: str, wait_s: float = 0.0, origin: Origin | None = None) -> bool:
        """Says it, waiting up to wait_s for the player to stop talking first. True if said."""
        deadline = time.monotonic() + wait_s
        while not await self._voice.say(text, origin=origin):
            if time.monotonic() >= deadline:
                if wait_s:
                    log.info("Player kept talking; dropped: %s", text)
                return False
            await asyncio.sleep(SPEAK_RETRY_S)
        await self._said(text)
        return True

    async def _player_turn(self, action: AskTalker, agent: ToolLLM, tools: ToolRegistry) -> None:
        started = time.monotonic()
        context = await player_context(self._context, self._page_excerpt, action.transcript)

        async def looking() -> None:
            self.checking = True
            # The result takes seconds, and silence would read as not having heard them.
            text, bark = self._lines.next("looking")
            if await (self._voice.play(bark) if bark else self._voice.say(text)):
                self._note_line()

        try:
            text = await player_reply(
                agent,
                tools,
                action.transcript,
                TurnContext(action.started_at),
                self._persona(),
                context,
                looking,
                self._lines.text("done"),
                lambda: self._lines.text("unavailable"),
                started,
            )
            if text:
                # After a tool, the player may well be talking while they wait, so hold the answer.
                await self._speak(text, ANSWER_WAIT_S if self.checking else 0.0)
        finally:
            self.checking = False

    async def _advise(self) -> None:
        tip = self._tip_llm
        agent, talker = (tip, tip) if tip else (self._agent, self._talker)
        # Blinded, it can't point, so the model isn't offered the pointer at all.
        tools = None if self._state.blind else self._tools
        context = await gather_context(self._context, TIP_QUERY)
        text = await give_tip(agent, talker, tools, self._persona(), context)
        if text:
            await self._speak(text)

    async def _talk(self, prompt: str, query: str, origin: Origin | None = None) -> None:
        if self._talker is None:
            log.warning("No talker LLM configured; ignoring: %s", prompt)
            return
        context = await gather_context(self._context, query)
        text = await talker_reply(self._talker, prompt, self._persona(), context)
        if text:
            await self._speak(text, origin=origin)
