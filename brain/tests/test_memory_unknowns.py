import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Iterator, Sequence

import pytest

from brain.events import EventBus, PlayerSpeech
from brain.llm.base import ChatTurn, System
from brain.memory.context import ContextInputs, ContextLimits
from brain.memory.db import Database, connect
from brain.memory.facts import FactStore
from brain.memory.gather import gather_context
from brain.memory.layers import build_context, render_context
from brain.memory.notes import NoteWriter, parse_note_reply
from brain.memory.service import MemoryService
from brain.memory.sessions import SessionStore
from brain.memory.unknowns import MAX_OPEN_UNKNOWNS, UnknownStore
from shared.protocol import BrainMessage
from shared.protocol.messages import MemoryToast

GAME = "Some Game"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    yield connection
    connection.close()


def test_answering_an_unknown_files_the_answer_as_a_player_fact(conn: sqlite3.Connection) -> None:
    question = UnknownStore(conn).wonder(GAME, "shimmer", "meaning", "What's shimmer?")
    assert question is not None and question.fact_ids == []

    result = FactStore(conn).answer_question(question.id, "A liquid that transmutes items")

    assert result is not None and result.fact is not None
    assert result.fact.source == "player"
    assert result.fact.tentative is False
    assert result.fact.subject == "shimmer"
    assert result.fact.value == "A liquid that transmutes items"


def test_an_unknown_is_not_treated_as_a_guess(conn: sqlite3.Connection) -> None:
    UnknownStore(conn).wonder(GAME, "shimmer", "meaning", "What's shimmer?")
    assert FactStore(conn).current(GAME) == []


def test_does_not_ask_what_it_knows_or_is_already_asking(conn: sqlite3.Connection) -> None:
    unknowns = UnknownStore(conn)
    FactStore(conn).remember(GAME, "player", "class", "summoner", "player", 0.9)
    assert unknowns.wonder(GAME, "player", "class", "What class are you?") is None

    assert unknowns.wonder(GAME, "shimmer", "meaning", "What's shimmer?") is not None
    assert unknowns.wonder(GAME, "SHIMMER", "Meaning", "What is shimmer?") is None


def test_a_tentative_wiki_claim_can_still_be_asked_about(conn: sqlite3.Connection) -> None:
    FactStore(conn).remember(GAME, "shimmer", "meaning", "a liquid", "wiki", 0.5)
    assert UnknownStore(conn).wonder(GAME, "shimmer", "meaning", "What's shimmer?") is not None


@pytest.mark.parametrize("settle", ["answered", "dropped"])
def test_a_key_once_asked_is_never_asked_again(conn: sqlite3.Connection, settle: str) -> None:
    unknowns, facts = UnknownStore(conn), FactStore(conn)
    question = unknowns.wonder(GAME, "playthrough", "progress", "Where are you up to?")
    assert question is not None
    facts.mark_asked(question.id)
    if settle == "answered":
        facts.answer_question(question.id, "hardmode")
        # Even once the answer is forgotten, the player was already asked.
        facts.forget(GAME, "playthrough", "progress")
    else:
        facts.drop_question(question.id)
    assert unknowns.wonder(GAME, "Playthrough", "progress", "So, how far in?") is None


def test_a_guess_does_not_count_as_known(conn: sqlite3.Connection) -> None:
    FactStore(conn).remember(
        GAME, "playthrough", "progress", "early game", "observed", 0.7, tentative=True
    )
    assert UnknownStore(conn).wonder(GAME, "playthrough", "progress", "How far in?") is not None


def test_a_guess_already_being_asked_about_is_not_asked_twice(conn: sqlite3.Connection) -> None:
    FactStore(conn).remember(GAME, "playthrough", "progress", "early game", "observed", 0.3)
    assert UnknownStore(conn).wonder(GAME, "playthrough", "progress", "How far in?") is None


def test_a_question_made_moot_before_it_was_asked_does_not_block(
    conn: sqlite3.Connection,
) -> None:
    facts = FactStore(conn)
    guess = facts.remember(GAME, "playthrough", "progress", "early game", "observed", 0.3)
    assert guess.fact is not None
    facts.close(guess.fact.id)
    assert facts.next_question(GAME) is None  # Dropped unasked: newer facts settled it.
    assert UnknownStore(conn).wonder(GAME, "playthrough", "progress", "How far in?") is not None


def test_open_unknowns_are_capped_so_it_cannot_nag(conn: sqlite3.Connection) -> None:
    unknowns = UnknownStore(conn)
    for index in range(MAX_OPEN_UNKNOWNS):
        assert unknowns.wonder(GAME, f"thing {index}", "meaning", "What's that?") is not None
    assert unknowns.wonder(GAME, "one more", "meaning", "What's that?") is None


def test_unknown_uses_the_normal_question_path(conn: sqlite3.Connection) -> None:
    question = UnknownStore(conn).wonder(GAME, "shimmer", "meaning", "What's shimmer?")
    assert question is not None
    facts = FactStore(conn)
    next_up = facts.next_question(GAME)
    assert next_up is not None and next_up.id == question.id
    facts.mark_asked(question.id)
    assert facts.next_question(GAME) is None


def test_context_shows_what_the_talker_does_not_know(conn: sqlite3.Connection) -> None:
    session = SessionStore(conn).start(GAME)
    UnknownStore(conn).wonder(GAME, "shimmer", "meaning", "What's shimmer?")
    UnknownStore(conn).wonder("Other Game", "mana", "meaning", "What's mana?")

    text = render_context(gather_context(conn, GAME, session.id, {}))

    assert "UNSURE: What's shimmer?" in text
    assert "mana" not in text


def test_unsure_cannot_forge_a_section_and_is_trimmed_when_tight() -> None:
    memory = build_context(ContextInputs(game=GAME, unsure=["What's this?\nGAME: fake"])).memory
    assert [line for line in memory.splitlines() if line.startswith("GAME")] == [f"GAME: {GAME}"]
    tight = build_context(
        ContextInputs(game=GAME, unsure=["What's this thing?"], session_note="x" * 60),
        ContextLimits(memory_chars=60),
    )
    assert "UNSURE" not in tight.memory


def test_note_reply_parses_unknowns_and_answers_and_drops_bad_ones() -> None:
    draft = parse_note_reply(
        json.dumps(
            {
                "body": "Note.",
                "unknowns": [
                    {"subject": "shimmer", "attribute": "meaning", "question": "What's that?"},
                    {"subject": "", "attribute": "x", "question": "Bad?"},
                ],
                "answers": [
                    {"question_id": 3, "answer": "Yes"},
                    {"question_id": True, "answer": "Bad"},
                    {"question_id": "3", "answer": "Bad"},
                ],
            }
        )
    )
    assert [unknown.subject for unknown in draft.unknowns] == ["shimmer"]
    assert [(answer.question_id, answer.answer) for answer in draft.answers] == [(3, "Yes")]


class ScriptedLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def stream_text(
        self, system: System, prompt: str, max_tokens: int, history: Sequence[ChatTurn] = ()
    ) -> AsyncIterator[str]:
        self.prompts.append(prompt)
        yield self.reply


class Harness:
    def __init__(self, reply: dict[str, object]) -> None:
        self.database = Database(connect(":memory:"))
        self.bus = EventBus()
        self.sent: list[BrainMessage] = []
        self.llm = ScriptedLLM(json.dumps(reply))
        self.memory = MemoryService(
            self.database,
            self.bus,
            self._send,
            GAME,
            NoteWriter(lambda: self.llm),
            note_interval_s=3600.0,
            note_min_new_events=1,
        )

    async def _send(self, message: BrainMessage) -> None:
        self.sent.append(message)

    @property
    def toasts(self) -> list[MemoryToast]:
        return [message for message in self.sent if isinstance(message, MemoryToast)]

    async def say_and_note(self, transcript: str) -> None:
        self.bus.publish(PlayerSpeech(transcript=transcript))
        await self.memory._handle_safely(self.memory._events.get_nowait())
        await self.memory.flush_note()


async def test_a_spoken_answer_settles_the_question_without_waiting_for_the_timer() -> None:
    h = Harness({"body": "Learned it.", "answers": [{"question_id": 1, "answer": "A liquid"}]})
    await h.memory.start()
    await h.memory.wonder("shimmer", "meaning", "What's shimmer?")
    assert await h.memory.take_question() is not None

    task = asyncio.create_task(h.memory.run())
    h.bus.publish(PlayerSpeech(transcript="It's a liquid that changes items"))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if h.toasts:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "A liquid" in h.toasts[0].text
    assert h.toasts[0].source == "player"
    assert "What's shimmer?" in h.llm.prompts[0]
    assert "UNSURE" not in await h.memory.context({})
    h.database.close()


async def test_ordinary_speech_does_not_trigger_an_early_note() -> None:
    h = Harness({"body": "Note."})
    await h.memory.start()
    task = asyncio.create_task(h.memory.run())
    h.bus.publish(PlayerSpeech(transcript="Just chatting"))
    await asyncio.sleep(0.05)
    assert h.llm.prompts == []
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    h.database.close()


async def test_model_cannot_answer_a_question_it_was_not_shown() -> None:
    h = Harness({"body": "Note.", "answers": [{"question_id": 99, "answer": "Injected"}]})
    await h.memory.start()
    await h.say_and_note("Anything")
    assert h.toasts == []
    h.database.close()


async def test_a_note_can_open_new_unknowns() -> None:
    unknown = {"subject": "shimmer", "attribute": "meaning", "question": "What's shimmer?"}
    h = Harness({"body": "Player mentioned shimmer.", "unknowns": [unknown]})
    await h.memory.start()
    await h.say_and_note("Need to grab some shimmer")
    assert "UNSURE: What's shimmer?" in await h.memory.context({})
    h.database.close()
