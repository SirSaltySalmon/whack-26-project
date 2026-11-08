"""Tools a player turn uses to answer the partner's question or set its memory straight.

The player is the top authority on their own game, so what they say goes in as a player fact and
memory's trust rules close whatever it replaces. These write to the local database and nothing
else, so they're quick: no filler line, and nothing worth surviving a barge-in for.

The model fills these in from the player's words, so every value is data from speech. Memory
stores it as text and never follows it.
"""

import logging
from typing import Protocol

from pydantic import BaseModel, Field

from brain.agent.tools import Tool, TurnContext
from brain.memory.models import Source

log = logging.getLogger(__name__)

# Memory's context is cut to a fixed length, so one rambling value would crowd out the rest.
MAX_VALUE_CHARS = 200
PLAYER_CONFIDENCE = 0.9
MEMORY_TIMEOUT_S = 5.0
_PLAYER: Source = "player"
# "ignored" means memory already had it, which is as good as remembered to the player.
_REMEMBERED = frozenset({"stored", "replaced", "confirmed", "ignored"})


class PlayerMemory(Protocol):
    async def answer_question(
        self, question_id: int | None, answer: str, correction: str | None = None
    ) -> object | None: ...

    async def remember(
        self,
        subject: str,
        attribute: str,
        value: str,
        source: Source,
        confidence: float,
        *,
        tentative: bool = False,
    ) -> object: ...

    async def forget(self, subject: str, attribute: str) -> int: ...


# Every field is required, with 0 or "" for none, like the other tools: a nullable field is one
# more schema feature each vendor's function calling has to get right.
class AnswerInput(BaseModel):
    question_id: int = Field(
        ge=0, description="The number after # under ASKED, or 0 for the question just asked."
    )
    answer: str = Field(
        description="Their answer in a few words. For a yes or no question, exactly Yes or No."
    )
    correction: str = Field(
        description="What's actually true, if they said no and told you. Otherwise empty."
    )


class RememberInput(BaseModel):
    subject: str = Field(
        description="Who or what it's about, such as player or playthrough. When correcting, "
        "exactly as shown under PLAYER."
    )
    attribute: str = Field(
        description="What about it, such as goal or progress. When correcting, exactly as shown "
        "under PLAYER."
    )
    value: str = Field(description="What's true, in a few words.")


class ForgetInput(BaseModel):
    subject: str = Field(description="Exactly as shown under PLAYER.")
    attribute: str = Field(description="Exactly as shown under PLAYER.")


def _outcome(result: object) -> str | None:
    # Typed loosely so this module doesn't depend on memory's result class, only its outcome.
    outcome = getattr(result, "outcome", None)
    return outcome if isinstance(outcome, str) else None


def memory_tools(memory: PlayerMemory) -> list[Tool]:
    async def answer_question(arguments: AnswerInput, _turn: TurnContext) -> str:
        result = await memory.answer_question(
            arguments.question_id or None,
            arguments.answer.strip(),
            arguments.correction.strip()[:MAX_VALUE_CHARS] or None,
        )
        if result is None:
            return "No question was waiting for that answer, so nothing was saved."
        return "Saved their answer."

    async def remember_fact(arguments: RememberInput, _turn: TurnContext) -> str:
        subject, attribute = arguments.subject.strip(), arguments.attribute.strip()
        value = arguments.value.strip()[:MAX_VALUE_CHARS]
        if not (subject and attribute and value):
            return "remember_fact needs a subject, an attribute and a value."
        result = await memory.remember(subject, attribute, value, _PLAYER, PLAYER_CONFIDENCE)
        outcome = _outcome(result)
        if outcome in _REMEMBERED:
            return "Remembered."
        log.info("Player fact %s / %s came back %s", subject, attribute, outcome)
        return "Noted, but it doesn't fit something else remembered, so it'll be checked with them."

    async def forget_fact(arguments: ForgetInput, _turn: TurnContext) -> str:
        closed = await memory.forget(arguments.subject.strip(), arguments.attribute.strip())
        if closed:
            return "Forgotten."
        return "Nothing was remembered under that, so there was nothing to forget."

    return [
        Tool(
            "answer_question",
            "Save the player's answer to the question under ASKED, when their words answer it. "
            "For a yes or no question, answer Yes or No, plus a correction if they said what's "
            "actually true.",
            AnswerInput,
            answer_question,
            MEMORY_TIMEOUT_S,
            quick=True,
        ),
        Tool(
            "remember_fact",
            "Remember something lasting the player says about themselves or this playthrough, "
            "such as their goal or how far they've got, or their correction of something you "
            "remember. When correcting, reuse the subject and attribute shown under PLAYER.",
            RememberInput,
            remember_fact,
            MEMORY_TIMEOUT_S,
            quick=True,
        ),
        Tool(
            "forget_fact",
            "Forget something you remember when the player says it's wrong without saying "
            "what's right.",
            ForgetInput,
            forget_fact,
            MEMORY_TIMEOUT_S,
            quick=True,
        ),
    ]
