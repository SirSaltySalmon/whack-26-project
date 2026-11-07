"""Runs the rules against the event bus and carries out their actions."""

import logging
from collections.abc import Callable

from brain.director.rules import Action, AskTalker, DirectorState, Say, decide
from brain.director.talker import reply
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
    ) -> None:
        self._events = bus.subscribe()
        self._voice = voice
        self._proactive = proactive
        self._talker = talker
        self._personality = personality
        self._max_words = max_words
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
                if self._talker is None:
                    log.warning("No talker LLM configured; ignoring: %s", action.transcript)
                    return
                # TODO(track 3): add the pre-assembled memory context once track 4 exposes it.
                text = await reply(
                    self._talker, action.transcript, self._personality(), self._max_words
                )
                if text:
                    await self._voice.say(text)
