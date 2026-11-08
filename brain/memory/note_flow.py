"""Writes session notes on the slow loop, and applies what each note learned through memory's rules.

A note is also the backup path for a spoken answer the talker didn't record itself, so a reply to a
question brings the next note forward.
"""

import asyncio
import logging
from pathlib import Path
from typing import Protocol

from brain.memory.db import Database
from brain.memory.export import export_quietly
from brain.memory.facts import FactStore
from brain.memory.models import Fact, NoteKind, Question, RememberResult, Session, Source
from brain.memory.notes import NoteDraft, NoteWriter
from brain.memory.profile import ProfileStore
from brain.memory.sessions import SessionStore
from brain.memory.unknowns import UnknownStore

log = logging.getLogger(__name__)

# Enough for the model to reuse an exact key when the player corrects one.
MAX_FACTS_IN_PROMPT = 20


class DraftSink(Protocol):
    """Where a note's drafted facts, answers and questions go: memory's own trust rules."""

    async def remember(
        self,
        subject: str,
        attribute: str,
        value: str,
        source: Source,
        confidence: float,
        *,
        tentative: bool = False,
    ) -> RememberResult: ...

    async def answer_question(
        self, question_id: int | None, answer: str, correction: str | None = None
    ) -> RememberResult | None: ...

    async def wonder(self, subject: str, attribute: str, text: str) -> Question | None: ...


class NoteFlow:
    def __init__(
        self,
        database: Database,
        game: str,
        writer: NoteWriter,
        sink: DraftSink,
        *,
        vault_dir: Path | None,
        interval_s: float,
        min_new_events: int,
        facts: FactStore,
        sessions: SessionStore,
        profile: ProfileStore,
        unknowns: UnknownStore,
    ) -> None:
        self._database = database
        self._game = game
        self._writer = writer
        self._sink = sink
        self._vault_dir = vault_dir
        self._interval_s = interval_s
        self._min_new_events = min_new_events
        self._facts = facts
        self._sessions = sessions
        self._profile = profile
        self._unknowns = unknowns
        self._due = asyncio.Event()
        self._last_note_ts = 0.0

    def bring_forward(self) -> None:
        self._due.set()

    async def loop(self, session: Session) -> None:
        while True:
            try:
                await asyncio.wait_for(self._due.wait(), self._interval_s)
                min_events: int | None = 1
            except TimeoutError:
                min_events = None
            self._due.clear()
            try:
                await self.flush(session, min_events=min_events)
            except Exception:
                log.exception("Failed to write a session note")

    async def flush(
        self, session: Session, kind: NoteKind = "rolling", min_events: int | None = None
    ) -> bool:
        """Writes a note if enough has happened. Returns whether one was written."""
        since = self._last_note_ts
        events = await self._database.run(lambda _: self._sessions.events_since(session.id, since))
        required = self._min_new_events if min_events is None else min_events
        if len(events) < required or not events:
            return False

        def read_inputs(_: object) -> tuple[str, str | None, list[Question], list[Fact]]:
            previous = self._sessions.latest_note(session.id)
            brief = self._profile.get(self._game).brief
            questions = self._unknowns.answerable_questions(self._game, session.started_at)
            facts = self._facts.current(self._game, limit=MAX_FACTS_IN_PROMPT)
            return brief, previous.body if previous else None, questions, facts

        brief, previous, questions, facts = await self._database.run(read_inputs)
        # The model call happens outside the database worker so it can't hold up other queries.
        draft = await self._writer.write(brief, previous, events, kind, questions, facts)
        from_ts, to_ts = events[0].ts, events[-1].ts
        await self._database.run(
            lambda _: self._sessions.add_note(session.id, kind, draft.body, from_ts, to_ts)
        )
        self._last_note_ts = to_ts
        await self._apply(draft, {question.id for question in questions})
        await self.export(session.id)
        return True

    async def export(self, live_session: int) -> None:
        """Refreshes the vault. Only the live session's page is rebuilt, so it stays fast."""
        if self._vault_dir is not None:
            await export_quietly(self._database, self._vault_dir, self._game, live_session)

    async def _apply(self, draft: NoteDraft, shown_ids: set[int]) -> None:
        # Answers go first so a matching drafted fact confirms the answer rather than disputing it.
        for answer in draft.answers:
            # Model output is untrusted, so it can only settle questions it was actually shown.
            if answer.question_id not in shown_ids:
                log.warning("Ignoring drafted answer to question %s", answer.question_id)
                continue
            await self._sink.answer_question(answer.question_id, answer.answer, answer.correction)
        for fact in draft.facts:
            try:
                await self._sink.remember(
                    fact.subject, fact.attribute, fact.value, "player", fact.confidence
                )
            except ValueError:
                # Model output is untrusted, so one bad fact shouldn't discard the rest of the note.
                log.warning(
                    "Rejected a drafted fact: %r %r", fact.subject, fact.attribute, exc_info=True
                )
        for unknown in draft.unknowns:
            try:
                await self._sink.wonder(unknown.subject, unknown.attribute, unknown.question)
            except ValueError:
                log.warning("Rejected a drafted question: %r", unknown.question)
