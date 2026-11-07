"""Runs the rules against the event bus and carries out their actions."""

import logging
from collections.abc import Callable

from brain.director.rules import Action, AskTalker, DirectorState, Say, decide
from brain.events import EventBus
from brain.voice.pipeline import Voice

log = logging.getLogger(__name__)


class Director:
    def __init__(self, bus: EventBus, voice: Voice, proactive: Callable[[], bool]) -> None:
        self._events = bus.subscribe()
        self._voice = voice
        self._proactive = proactive
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
                # TODO(track 3): stream from brain.llm with the pre-assembled context.
                log.warning("Talker isn't wired yet; ignoring: %s", action.transcript)
