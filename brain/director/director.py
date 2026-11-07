"""Runs the rules against the event bus and carries out their actions."""

import logging
from collections.abc import Awaitable, Callable

from brain.director.rules import Action, AskTalker, DirectorState, ReactToEvent, Say, decide
from brain.director.talker import event_prompt, reply
from brain.events import EventBus
from brain.llm.base import TextLLM
from brain.voice.pipeline import Voice

log = logging.getLogger(__name__)


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
    ) -> None:
        self._events = bus.subscribe()
        self._voice = voice
        self._proactive = proactive
        self._talker = talker
        self._personality = personality
        self._max_words = max_words
        self._context = context
        self._on_spoken = on_spoken
        self._state = DirectorState()

    async def run(self) -> None:
        while True:
            event = await self._events.get()
            for action in decide(event, self._state, self._proactive()):
                try:
                    await self._perform(action)
                except Exception:
                    # One failed action must not end the loop and leave the partner silent.
                    log.exception("Director action failed: %s", action)

    async def _perform(self, action: Action) -> None:
        match action:
            case Say():
                await self._voice.say(action.text)
            case AskTalker():
                await self._talk(action.transcript, query=action.transcript)
            case ReactToEvent():
                await self._talk(event_prompt(action.name, action.data), query=action.name)

    async def _talk(self, prompt: str, query: str) -> None:
        if self._talker is None:
            log.warning("No talker LLM configured; ignoring: %s", prompt)
            return
        context = await self._gather_context(query)
        text = await reply(self._talker, prompt, self._personality(), self._max_words, context)
        if not text:
            return
        await self._voice.say(text)
        if self._on_spoken:
            await self._on_spoken(text)

    async def _gather_context(self, query: str) -> str:
        if self._context is None:
            return ""
        try:
            return await self._context(query)
        except Exception:
            # A reply without memory beats no reply at all.
            log.exception("Couldn't build the talker's context")
            return ""
