"""The question the partner just asked: waiting for its answer, and giving up on it for good.

A question is dropped unanswered when no reply starts within the timeout, counted from the later of
when it was asked and the player's last turn, or when more than `max_turns` player turns pass
without an answer. Either way the player moved on, so it's never asked again. An answer that
arrives late still counts, because the player may come back to it.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from brain.memory.db import Database
from brain.memory.facts import FactStore
from brain.memory.models import RememberResult
from shared.protocol.messages import QuestionAsk

log = logging.getLogger(__name__)

GiveUp = tuple[int, str]  # The question's id, and why it was dropped.


@dataclass
class _Waiting:
    question_id: int
    # The later of when it was asked, when a reply last started and when the last turn ended. A
    # reply starting counts too, so a start with no turn after it, such as a cough, can't stall
    # the wait for good.
    since: float
    turns: int = 0


class AnswerWatch:
    """When to give up on the question just asked. Pure state, so tests can drive the clock."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        answer_timeout_s: float = 20.0,
        typed_timeout_s: float = 45.0,
        max_turns: int = 2,
    ) -> None:
        self._clock = clock
        self._answer_timeout_s = answer_timeout_s
        self._typed_timeout_s = typed_timeout_s
        self._max_turns = max_turns
        # Off means the player types replies, which takes longer than saying them.
        self.mic_enabled = True
        self._waiting: _Waiting | None = None
        self._last_asked: int | None = None

    @property
    def pending(self) -> int | None:
        """The question being waited on, shown to the talker under ASKED."""
        return self._waiting.question_id if self._waiting else None

    @property
    def last_asked(self) -> int | None:
        """What an answer with no question id is for: the pending question, or the last one asked
        and dropped, since a late answer still counts."""
        return self._last_asked

    def follow(self, settings: object) -> None:
        """Typed loosely: memory doesn't depend on the protocol's Settings model."""
        self.mic_enabled = bool(getattr(settings, "mic_enabled", True))

    def asked(self, question_id: int) -> None:
        self._waiting = _Waiting(question_id, self._clock())
        self._last_asked = question_id

    def settled(self, question_id: int) -> None:
        """Answered, or handed back unsaid. Either way there's nothing left to wait for."""
        if self._waiting is not None and self._waiting.question_id == question_id:
            self._waiting = None
        if self._last_asked == question_id:
            self._last_asked = None

    def reply_started(self) -> None:
        if self._waiting is not None:
            self._waiting.since = self._clock()

    def turn_ended(self) -> GiveUp | None:
        waiting = self._waiting
        if waiting is None:
            return None
        waiting.turns += 1
        waiting.since = self._clock()
        if waiting.turns > self._max_turns:
            return self._give_up(waiting, f"{waiting.turns} player turns went by without an answer")
        return None

    def overdue(self) -> GiveUp | None:
        waiting = self._waiting
        if waiting is None:
            return None
        timeout = self._answer_timeout_s if self.mic_enabled else self._typed_timeout_s
        if self._clock() - waiting.since < timeout:
            return None
        how = "spoken" if self.mic_enabled else "typed"
        return self._give_up(waiting, f"no {how} reply started within {timeout:g} s")

    def _give_up(self, waiting: _Waiting, reason: str) -> GiveUp:
        # Kept as last_asked, so a late answer with no id still lands on it.
        self._waiting = None
        return waiting.question_id, reason


class Asking:
    """Hands questions to the director and settles them. The one database worker keeps the steps
    in order, and the watch is only touched from the event loop."""

    def __init__(
        self,
        database: Database,
        facts: FactStore,
        game: str,
        watch: AnswerWatch,
        settle: Callable[[RememberResult], Awaitable[None]],
        bring_note_forward: Callable[[], None],
    ) -> None:
        self._database = database
        self._facts = facts
        self._game = game
        self._watch = watch
        self._settle = settle
        self._bring_note_forward = bring_note_forward
        # The talker records most answers itself. The next note is the backup for one it missed.
        self._note_on_reply = False

    async def take(self) -> QuestionAsk | None:
        pending = self._watch.pending
        if pending is not None:
            status = await self._database.run(lambda _: self._facts.question_status(pending))
            if status == "open":
                # One at a time: a second question would bury the first one's answer.
                log.debug("Not taking a question: still waiting on %s", pending)
                return None
            self._watch.settled(pending)

        def take(_: object) -> QuestionAsk | None:
            question = self._facts.next_question(self._game)
            if question is None:
                return None
            self._facts.mark_asked(question.id)
            return QuestionAsk(
                question_id=str(question.id), text=question.text, options=question.options
            )

        asked = await self._database.run(take)
        if asked is not None:
            self._watch.asked(int(asked.question_id))
            self._note_on_reply = True
        return asked

    async def release(self, question_id: str) -> None:
        try:
            number = int(question_id)
        except ValueError:
            log.warning("Ignoring release of invalid question id %r", question_id)
            return
        await self._database.run(lambda _: self._facts.unmark_asked(number))
        self._watch.settled(number)
        self._note_on_reply = False
        log.info("Question %s goes back in the queue: it wasn't said", number)

    async def answer(
        self, question_id: int | None, answer: str, correction: str | None
    ) -> RememberResult | None:
        number = question_id if question_id is not None else self._watch.last_asked
        if number is None:
            log.warning("No question was just asked, so this answer has nowhere to go: %r", answer)
            return None
        result = await self._database.run(
            lambda _: self._facts.answer_question(number, answer, correction)
        )
        if result is None:
            return None
        log.info("Question %s answered (%s)", number, result.outcome)
        self._watch.settled(number)
        await self._settle(result)
        return result

    async def answer_event(self, question_id: str, answer: str) -> None:
        """An answer picked in the overlay, which names its question as a string."""
        try:
            number = int(question_id)
        except ValueError:
            log.warning("Ignoring answer to invalid question id %r", question_id)
            return
        await self.answer(number, answer, None)

    async def turn_ended(self) -> None:
        await self._drop(self._watch.turn_ended())
        if self._note_on_reply:
            self._note_on_reply = False
            self._bring_note_forward()

    async def check(self) -> bool:
        """Drops the question being waited on if its time is up. Returns whether it did."""
        dropped = await self._drop(self._watch.overdue())
        if dropped:
            # Nobody replied, so there's no spoken answer for a note to pick up.
            self._note_on_reply = False
        return dropped

    async def loop(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.check()
            except Exception:
                log.exception("Failed to check the question being waited on")

    async def drop_stale(self) -> None:
        dropped = await self._database.run(lambda _: self._facts.drop_stale_asked(self._game))
        if dropped:
            log.info("Dropped questions asked in an earlier run and never answered: %s", dropped)

    async def _drop(self, give_up: GiveUp | None) -> bool:
        if give_up is None:
            return False
        question_id, reason = give_up
        dropped = await self._database.run(lambda _: self._facts.drop_question(question_id))
        if dropped:
            log.info("Dropped question %s for good, unanswered: %s", question_id, reason)
        else:
            log.debug("Question %s was already settled when its wait ended", question_id)
        return dropped
