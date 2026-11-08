"""Writes session notes on the slow loop, and applies what each note learned through memory's rules.

A note is also the backup path for a spoken answer the talker didn't record itself, so a reply to a
question brings the next note forward. It reads the same conversation the talker's tools wrote
from, so its drafted facts are checked against what they just recorded (see note_keys.py).
"""

import asyncio
import logging
from pathlib import Path
from typing import Protocol

from brain.memory.db import Database
from brain.memory.export import export_quietly
from brain.memory.facts import FactStore
from brain.memory.models import Fact, NoteKind, Question, RememberResult, Session, Source
from brain.memory.note_keys import Key, existing_key, restates
from brain.memory.notes import NoteDraft, NoteWriter
from brain.memory.profile import ProfileStore
from brain.memory.sessions import SessionStore
from brain.memory.unknowns import UnknownStore

log = logging.getLogger(__name__)

# Enough for the model to reuse an exact key when the player corrects one.
MAX_FACTS_IN_PROMPT = 20
# Every key a drafted fact could land beside. Read from the database, so it costs no tokens.
MAX_KNOWN_KEYS = 200
# The talker usually records a reply within about 2 s of the turn ending. A note brought forward
# by that reply waits this long first, so it backs the talker up instead of racing it to file the
# same reply twice.
REPLY_GRACE_S = 5.0


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
        reply_grace_s: float = REPLY_GRACE_S,
    ) -> None:
        self._database = database
        self._reply_grace_s = reply_grace_s
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
            min_events: int | None
            try:
                await asyncio.wait_for(self._due.wait(), self._interval_s)
            except TimeoutError:
                min_events = None
            else:
                min_events = 1
                await asyncio.sleep(self._reply_grace_s)
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
        await self._apply(draft, session, questions, since=from_ts)
        await self.export(session.id)
        return True

    async def export(self, live_session: int) -> None:
        """Refreshes the vault. Only the live session's page is rebuilt, so it stays fast."""
        if self._vault_dir is not None:
            await export_quietly(self._database, self._vault_dir, self._game, live_session)

    async def _apply(
        self, draft: NoteDraft, session: Session, shown: list[Question], since: float
    ) -> None:
        # Answers go first, so a drafted fact restating one is recognised below and skipped.
        shown_ids = {question.id for question in shown}
        for answer in draft.answers:
            # Model output is untrusted, so it can only settle questions it was actually shown.
            if answer.question_id not in shown_ids:
                log.warning("Ignoring drafted answer to question %s", answer.question_id)
                continue
            await self._sink.answer_question(answer.question_id, answer.answer, answer.correction)

        # Read after the answers, so what they filed and what the talker wrote meanwhile both count.
        recorded, known = await self._database.run(lambda _: self._keys(session, since))
        for fact in draft.facts:
            drafted = Key(fact.subject, fact.attribute)
            said = next((key for key in recorded if restates(drafted, key)), None)
            if said is not None:
                log.info(
                    "Skipping drafted fact %s / %s: %s / %s already records it",
                    *drafted,
                    *said,
                )
                continue
            key = existing_key(drafted, known)
            try:
                await self._sink.remember(*key, fact.value, "player", fact.confidence)
            except ValueError:
                # Model output is untrusted, so one bad fact shouldn't discard the rest of the note.
                log.warning("Rejected a drafted fact: %r %r", *key, exc_info=True)
                continue
            recorded.append(key)
            known.append(key)
        for unknown in draft.unknowns:
            # On a known key, wonder() sees it's known or already asked and opens nothing.
            key = existing_key(Key(unknown.subject, unknown.attribute), known)
            try:
                await self._sink.wonder(*key, unknown.question)
            except ValueError:
                log.warning("Rejected a drafted question: %r", unknown.question)

    def _keys(self, session: Session, since: float) -> tuple[list[Key], list[Key]]:
        """What the player said since the note's first event, and every key memory knows."""
        facts = self._facts.current(self._game, limit=MAX_KNOWN_KEYS)
        questions = self._unknowns.answerable_questions(
            self._game, session.started_at, limit=MAX_KNOWN_KEYS
        )
        recorded = [
            Key(fact.subject, fact.attribute)
            for fact in facts
            if fact.source == "player" and fact.valid_from >= since
        ]
        known = [Key(fact.subject, fact.attribute) for fact in facts]
        known += [Key(q.subject, q.attribute) for q in questions if q.subject and q.attribute]
        return recorded, known
