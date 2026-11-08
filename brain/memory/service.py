"""Connects memory to the rest of the brain. This is the only async entry point other tracks need.

Other tracks call:
- `talker_context()` for what every spoken reply knows, laid out in brain/memory/layers.py, with
  `CONTEXT_PREAMBLE` in the system prompt saying how to treat it
- `record_partner_turn()` whenever the partner finishes speaking, `record_tool()` after a tool
- `take_question()` when the director's question budget allows asking one, and
  `release_question()` if it then couldn't say it
- `answer_question()`, `remember()` and `forget()` from player-turn tools
- `wonder()` when something about the game is unclear and there's no guess to store
- `current_fact()` for the most trusted current value, before spending a model call on it

It publishes `FactLearned` whenever a fact is stored, replaced or confirmed.
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
    FactLearned,
    GameEvent,
    PlayerSpeech,
    PlayerStartedSpeaking,
    QuestionAnswered,
    SettingsChanged,
)
from brain.memory.asking import AnswerWatch, Asking
from brain.memory.assemble import ContextAssembler
from brain.memory.db import Database
from brain.memory.facts import FactStore
from brain.memory.layers import TalkerContext
from brain.memory.models import Fact, NoteKind, Question, RememberResult, Session, Source
from brain.memory.note_flow import NoteFlow
from brain.memory.notes import NoteWriter
from brain.memory.profile import PlayerStore, ProfileStore
from brain.memory.semantic import SemanticRecall
from brain.memory.sessions import SessionStore
from brain.memory.toasts import toast_for
from brain.memory.unknowns import UnknownStore
from shared.protocol import BrainMessage
from shared.protocol.messages import QuestionAsk

log = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

_LEARNED = frozenset({"stored", "replaced", "confirmed"})


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
        question_answer_timeout_s: float = 20.0,
        question_typed_timeout_s: float = 45.0,
        question_max_turns: int = 2,
        question_check_s: float = 1.0,
        semantic: SemanticRecall | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._database = database
        self._semantic = semantic
        self._assembler = ContextAssembler(database, game, semantic, clock)
        self._bus = bus
        self._events = bus.subscribe()
        self._send = send
        self._game = game
        self._question_check_s = question_check_s
        self._facts = FactStore(database.conn, clock)
        self._sessions = SessionStore(database.conn, clock)
        self._player = PlayerStore(database.conn, clock)
        self._unknowns = UnknownStore(database.conn, clock)
        self._watch = AnswerWatch(
            monotonic, question_answer_timeout_s, question_typed_timeout_s, question_max_turns
        )
        self._notes = NoteFlow(
            database,
            game,
            note_writer,
            self,
            vault_dir=vault_dir,
            interval_s=note_interval_s,
            min_new_events=note_min_new_events,
            facts=self._facts,
            sessions=self._sessions,
            profile=ProfileStore(database.conn, clock),
            unknowns=self._unknowns,
        )
        self._asking = Asking(
            database, self._facts, game, self._watch, self._settle, self._notes.bring_forward
        )
        self._session: Session | None = None

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("MemoryService.start() must run first")
        return self._session

    async def start(self) -> Session:
        self._session = await self._database.run(lambda _: self._sessions.start(self._game))
        log.info("Memory session %s started for %s", self._session.id, self._game)
        # Nobody is waiting on an answer from an earlier run, so its asked questions are let go.
        await self._asking.drop_stale()
        return self._session

    async def run(self) -> None:
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self._consume())
                tasks.create_task(self._notes.loop(self.session))
                tasks.create_task(self._asking.loop(self._question_check_s))
        finally:
            # Shielded because this runs during cancellation and must reach the database.
            await asyncio.shield(self.finish())

    # --- Called by other tracks ---
    async def talker_context(
        self, live_state: Mapping[str, str], query: str | None = None, current: str | None = None
    ) -> TalkerContext:
        """`query` is what to recall by. `current` is the words being answered: the transcript on
        player turns, None for game events, tips and think_hard."""
        session_id, asked = self.session.id, self._watch.pending
        return await self._assembler.build(session_id, asked, live_state, query, current)

    async def context(self, live_state: Mapping[str, str], query: str | None = None) -> str:
        """The same as one string, as the Control Center's preview shows it."""
        return (await self.talker_context(live_state, query)).render()

    async def record_partner_turn(self, text: str) -> None:
        session_id = self.session.id
        await self._database.run(lambda _: self._sessions.log_turn(session_id, "partner", text))

    async def record_tool(self, tool: str, note: str, ok: bool) -> None:
        session_id = self.session.id
        await self._database.run(lambda _: self._sessions.log_tool(session_id, tool, note, ok))

    async def take_question(self) -> QuestionAsk | None:
        """Marks it asked and starts waiting for the answer. None while one is still waited on."""
        return await self._asking.take()

    async def release_question(self, question_id: str) -> None:
        """The director couldn't say it, so it goes back in the queue."""
        await self._asking.release(question_id)

    async def answer_question(
        self, question_id: int | None, answer: str, correction: str | None = None
    ) -> RememberResult | None:
        """None as the id means the question just asked. `correction` is the right value after a
        "No". A question dropped as unanswered can still be answered."""
        return await self._asking.answer(question_id, answer, correction)

    async def wonder(self, subject: str, attribute: str, text: str) -> Question | None:
        session_id = self.session.id
        return await self._database.run(
            lambda _: self._unknowns.wonder(self._game, subject, attribute, text, session_id)
        )

    async def remember(
        self,
        subject: str,
        attribute: str,
        value: str,
        source: Source,
        confidence: float,
        *,
        tentative: bool = False,
    ) -> RememberResult:
        """`tentative` is for an inference rather than a reading: stored unconfirmed, no question.
        Raises ValueError for empty text or an out-of-range confidence."""
        game, session_id = self._game, self.session.id
        result = await self._database.run(
            lambda _: self._facts.remember(
                game, subject, attribute, value, source, confidence, session_id, tentative=tentative
            )
        )
        await self._settle(result)
        return result

    async def forget(self, subject: str, attribute: str) -> int:
        """Closes the current values for this exact key without asking anything, and returns how
        many. A guess can't bring a forgotten value back; only the player can."""
        closed = await self._database.run(
            lambda _: self._facts.forget(self._game, subject, attribute)
        )
        if closed:
            log.info("Forgot %s / %s: %s", subject, attribute, [fact.value for fact in closed])
            await self._announce(RememberResult("replaced", closed=closed))
        return len(closed)

    async def current_fact(self, subject: str, attribute: str) -> Fact | None:
        found = await self._database.run(
            lambda _: self._facts.current(self._game, subject, attribute, 1)
        )
        return found[0] if found else None

    async def load_settings(self, model: type[ModelT]) -> ModelT:
        loaded = await self._database.run(lambda _: self._player.load_settings(model))
        # brain/app.py loads settings right after start(), so this is how memory first learns
        # whether replies will be spoken or typed.
        self._watch.follow(loaded)
        return loaded

    async def check_question(self) -> bool:
        """Drops the question being waited on if its time is up. Returns whether it did."""
        return await self._asking.check()

    # --- Bus and loops ---
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
            case PlayerStartedSpeaking():
                self._watch.reply_started()
            case PlayerSpeech():
                await self._database.run(
                    lambda _: self._sessions.log_turn(session_id, "player", event.transcript)
                )
                await self._asking.turn_ended()
            case QuestionAnswered():
                await self._asking.answer_event(event.question_id, event.answer)
            case SettingsChanged():
                await self._database.run(lambda _: self._player.save_settings(event.settings))
                self._watch.follow(event.settings)

    async def _settle(self, result: RememberResult) -> None:
        """Shows what changed, and tells the director when a fact became current."""
        await self._announce(result)
        fact = result.fact
        if fact is not None and result.outcome in _LEARNED:
            self._bus.publish(
                FactLearned(
                    subject=fact.subject,
                    attribute=fact.attribute,
                    source=fact.source,
                    outcome=result.outcome,
                )
            )

    async def _announce(self, result: RememberResult) -> None:
        toast = toast_for(result)
        if toast is None:
            return
        try:
            await self._send(toast)
        except Exception:
            # The fact is already saved, so a dropped socket only costs the visible notice.
            log.exception("Couldn't send memory toast")

    async def flush_note(self, kind: NoteKind = "rolling", min_events: int | None = None) -> bool:
        """Writes a note if enough has happened. Returns whether one was written."""
        return await self._notes.flush(self.session, kind, min_events)

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
        # A past session's page is never rebuilt, so it has to show the end time now.
        await self._notes.export(session_id)
        log.info("Memory session %s ended", session_id)
