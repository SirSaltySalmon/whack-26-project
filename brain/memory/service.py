"""Connects memory to the rest of the brain. This is the only async entry point other tracks need.

Other tracks call:
- `context()` for the talker's small block, with `CONTEXT_PREAMBLE` in its system prompt
- `record_partner_turn()` whenever the partner finishes speaking
- `take_question()` when the director's question budget allows asking one
- `wonder()` when something about the game is unclear and there's no guess to store
- `remember()` to store a claim about the player or playthrough
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from brain.events import (
    Event,
    EventBus,
    GameEvent,
    PlayerSpeech,
    QuestionAnswered,
    SettingsChanged,
)
from brain.memory.context import render_context
from brain.memory.db import Database
from brain.memory.export import export_vault
from brain.memory.facts import FactStore
from brain.memory.gather import gather_context
from brain.memory.models import NoteKind, Question, RememberResult, Session, Source
from brain.memory.notes import NoteDraft, NoteWriter
from brain.memory.profile import PlayerStore, ProfileStore
from brain.memory.sessions import SessionStore
from brain.memory.toasts import toast_for
from brain.memory.unknowns import MAX_OPEN_QUESTIONS_IN_PROMPT, UnknownStore
from shared.protocol import BrainMessage
from shared.protocol.messages import QuestionAsk

log = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

SLOW_CONTEXT_MS = 50.0


class MemoryService:
    def __init__(
        self,
        database: Database,
        bus: EventBus,
        send: Callable[[BrainMessage], Awaitable[None]],
        game: str,
        note_writer: NoteWriter,
        *,
        vault_dir: Path | None = None,
        note_interval_s: float = 300.0,
        note_min_new_events: int = 5,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._database = database
        self._events = bus.subscribe()
        self._send = send
        self._game = game
        self._note_writer = note_writer
        self._vault_dir = vault_dir
        self._note_interval_s = note_interval_s
        self._note_min_new_events = note_min_new_events
        self._clock = clock
        self._facts = FactStore(database.conn, clock)
        self._sessions = SessionStore(database.conn, clock)
        self._profile = ProfileStore(database.conn, clock)
        self._player = PlayerStore(database.conn, clock)
        self._unknowns = UnknownStore(database.conn, clock)
        # A spoken answer only reaches memory through a note, so it brings the next note forward.
        self._awaiting_answer = False
        self._note_due = asyncio.Event()
        self._session: Session | None = None
        self._last_note_ts = 0.0

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("MemoryService.start() must run first")
        return self._session

    async def start(self) -> Session:
        self._session = await self._database.run(lambda _: self._sessions.start(self._game))
        log.info("Memory session %s started for %s", self._session.id, self._game)
        return self._session

    async def run(self) -> None:
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self._consume())
                tasks.create_task(self._note_loop())
        finally:
            # Shielded because this runs during cancellation and must reach the database.
            await asyncio.shield(self.finish())

    # --- Called by other tracks ---
    async def context(self, live_state: Mapping[str, str], query: str | None = None) -> str:
        started = time.perf_counter()
        session_id = self.session.id
        text = await self._database.run(
            lambda conn: render_context(
                gather_context(conn, self._game, session_id, live_state, query)
            )
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms > SLOW_CONTEXT_MS:
            log.warning("Memory context took %.1f ms", elapsed_ms)
        return text

    async def record_partner_turn(self, text: str) -> None:
        session_id = self.session.id
        await self._database.run(lambda _: self._sessions.log_turn(session_id, "partner", text))

    async def take_question(self) -> QuestionAsk | None:
        def take(_: object) -> QuestionAsk | None:
            question = self._facts.next_question(self._game)
            if question is None:
                return None
            self._facts.mark_asked(question.id)
            return QuestionAsk(
                question_id=str(question.id), text=question.text, options=question.options
            )

        asked = await self._database.run(take)
        self._awaiting_answer = self._awaiting_answer or asked is not None
        return asked

    async def wonder(self, subject: str, attribute: str, text: str) -> Question | None:
        session_id = self.session.id
        return await self._database.run(
            lambda _: self._unknowns.wonder(self._game, subject, attribute, text, session_id)
        )

    async def remember(
        self, subject: str, attribute: str, value: str, source: Source, confidence: float
    ) -> RememberResult:
        session_id = self.session.id
        result = await self._database.run(
            lambda _: self._facts.remember(
                self._game, subject, attribute, value, source, confidence, session_id
            )
        )
        await self._announce(result)
        return result

    async def load_settings(self, model: type[ModelT]) -> ModelT:
        return await self._database.run(lambda _: self._player.load_settings(model))

    # --- Bus and slow loop ---
    async def _consume(self) -> None:
        while True:
            event = await self._events.get()
            await self._handle_safely(event)

    async def _handle_safely(self, event: Event) -> None:
        try:
            await self._handle(event)
        except Exception:
            # Losing one memory must not stop the partner from remembering anything else.
            log.exception("Memory failed to handle %s", type(event).__name__)

    async def _handle(self, event: Event) -> None:
        session_id = self.session.id
        match event:
            case GameEvent():
                await self._database.run(
                    lambda _: self._sessions.log_event(session_id, event.name, event.data)
                )
            case PlayerSpeech():
                await self._database.run(
                    lambda _: self._sessions.log_turn(session_id, "player", event.transcript)
                )
                if self._awaiting_answer:
                    self._awaiting_answer = False
                    self._note_due.set()
            case QuestionAnswered():
                await self._answer(event)
            case SettingsChanged():
                await self._database.run(lambda _: self._player.save_settings(event.settings))

    async def _answer(self, event: QuestionAnswered) -> None:
        try:
            question_id = int(event.question_id)
        except ValueError:
            log.warning("Ignoring answer to invalid question id %r", event.question_id)
            return
        result = await self._database.run(
            lambda _: self._facts.answer_question(question_id, event.answer)
        )
        if result is not None:
            await self._announce(result)

    async def _announce(self, result: RememberResult) -> None:
        toast = toast_for(result)
        if toast is None:
            return
        try:
            await self._send(toast)
        except Exception:
            # The fact is already saved, so a dropped socket only costs the visible notice.
            log.exception("Couldn't send memory toast")

    async def _note_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._note_due.wait(), self._note_interval_s)
                min_events: int | None = 1
            except TimeoutError:
                min_events = None
            self._note_due.clear()
            try:
                await self.flush_note(min_events=min_events)
            except Exception:
                log.exception("Failed to write a session note")

    async def flush_note(self, kind: NoteKind = "rolling", min_events: int | None = None) -> bool:
        """Writes a note if enough has happened. Returns whether one was written."""
        session_id = self.session.id
        since = self._last_note_ts
        events = await self._database.run(lambda _: self._sessions.events_since(session_id, since))
        required = self._note_min_new_events if min_events is None else min_events
        if len(events) < required or not events:
            return False

        def read_inputs(_: object) -> tuple[str, str | None, list[Question]]:
            previous = self._sessions.latest_note(session_id)
            brief = self._profile.get(self._game).brief
            questions = self._unknowns.open_questions(self._game, MAX_OPEN_QUESTIONS_IN_PROMPT)
            return brief, previous.body if previous else None, questions

        brief, previous, questions = await self._database.run(read_inputs)
        # The model call happens outside the database worker so it can't hold up other queries.
        draft = await self._note_writer.write(brief, previous, events, kind, questions)
        from_ts, to_ts = events[0].ts, events[-1].ts
        await self._database.run(
            lambda _: self._sessions.add_note(session_id, kind, draft.body, from_ts, to_ts)
        )
        self._last_note_ts = to_ts
        await self._apply_draft(draft, {question.id for question in questions})
        await self._export()
        return True

    async def _apply_draft(self, draft: NoteDraft, open_ids: set[int]) -> None:
        # Answers go first so a matching drafted fact confirms the answer rather than disputing it.
        for answer in draft.answers:
            # Model output is untrusted, so it can only settle questions it was actually shown.
            if answer.question_id not in open_ids:
                log.warning("Ignoring drafted answer to question %s", answer.question_id)
                continue
            result = await self._database.run(
                lambda _, a=answer: self._facts.answer_question(a.question_id, a.answer)
            )
            if result is not None:
                await self._announce(result)
        for fact in draft.facts:
            await self._remember_drafted(fact.subject, fact.attribute, fact.value, fact.confidence)
        for unknown in draft.unknowns:
            await self.wonder(unknown.subject, unknown.attribute, unknown.question)

    async def _remember_drafted(
        self, subject: str, attribute: str, value: str, confidence: float
    ) -> None:
        try:
            await self.remember(subject, attribute, value, "player", confidence)
        except ValueError:
            # Model output is untrusted, so one bad fact shouldn't discard the rest of the note.
            log.warning("Rejected a drafted fact: %r %r", subject, attribute, exc_info=True)

    async def _export(self) -> None:
        if self._vault_dir is None:
            return
        vault_dir = self._vault_dir
        try:
            await self._database.run(lambda conn: export_vault(conn, vault_dir, self._game))
        except OSError:
            # The vault is only a view: SQLite already has everything.
            log.exception("Vault export to %s failed", vault_dir)

    async def finish(self) -> None:
        """Saves whatever's left, writes the recap and closes the session."""
        if self._session is None:
            return
        session_id = self._session.id
        while not self._events.empty():
            await self._handle_safely(self._events.get_nowait())
        try:
            await self.flush_note("recap", min_events=1)
        except Exception:
            log.exception("Failed to write the session recap")
        await self._database.run(lambda _: self._sessions.end(session_id))
        log.info("Memory session %s ended", session_id)
