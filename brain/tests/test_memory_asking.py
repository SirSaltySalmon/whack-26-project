"""Asking a question, waiting for its answer, and letting it go for good. No real sleeps.

The timing rules themselves are in test_memory_answer_watch.py.
"""

import asyncio
import logging

import pytest

from brain.events import (
    Event,
    EventBus,
    FactLearned,
    PlayerSpeech,
    PlayerStartedSpeaking,
    SettingsChanged,
)
from brain.llm.base import LLMUnavailableError, TextLLM
from brain.memory.db import Database, connect
from brain.memory.notes import NoteWriter
from brain.memory.profile import PlayerStore
from brain.memory.service import MemoryService
from brain.tests.fakes import drain
from shared.protocol import BrainMessage
from shared.protocol.messages import MemoryToast, Settings

GAME = "Some Game"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def no_llm() -> TextLLM:
    raise LLMUnavailableError("no key in tests")


class Rig:
    def __init__(self, database: Database | None = None, check_s: float = 3600.0) -> None:
        self.database = database or Database(connect(":memory:"))
        self.bus = EventBus()
        self.seen = self.bus.subscribe()
        self.sent: list[BrainMessage] = []
        self.clock = Clock()
        self.memory = MemoryService(
            self.database,
            self.bus,
            self._send,
            GAME,
            NoteWriter(no_llm),
            note_interval_s=3600.0,
            question_check_s=check_s,
            monotonic=self.clock,
        )

    async def _send(self, message: BrainMessage) -> None:
        self.sent.append(message)

    async def publish(self, *events: Event) -> None:
        for event in events:
            self.bus.publish(event)
        queue = self.memory._events
        while not queue.empty():
            await self.memory._handle_safely(queue.get_nowait())

    async def turn(self, text: str) -> None:
        await self.publish(PlayerStartedSpeaking(), PlayerSpeech(transcript=text))

    def status(self, question_id: str | int) -> str:
        sql = "SELECT status FROM questions WHERE id = ?"
        return self.database.conn.execute(sql, (int(question_id),)).fetchone()[0]

    def learned(self) -> list[FactLearned]:
        return [event for event in drain(self.seen) if isinstance(event, FactLearned)]


@pytest.fixture
async def rig():
    r = Rig()
    await r.memory.start()
    await r.memory.wonder("playthrough", "progress", "Where are you up to?")
    yield r
    r.database.close()


async def test_an_unanswered_question_is_dropped_and_never_asked_again(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    asked = await rig.memory.take_question()
    assert asked is not None
    assert "ASKED: #1 Where are you up to? (waiting for their answer)" in (
        await rig.memory.context({})
    )
    rig.clock.now += 19
    assert await rig.memory.check_question() is False
    rig.clock.now += 1
    with caplog.at_level(logging.INFO, logger="brain.memory.asking"):
        assert await rig.memory.check_question() is True
    assert "Dropped question 1 for good" in caplog.text
    assert rig.status(asked.question_id) == "dropped"

    context = await rig.memory.context({})
    assert "ASKED" not in context and "UNSURE" not in context
    assert await rig.memory.take_question() is None
    assert await rig.memory.wonder("playthrough", "progress", "How far in?") is None


async def test_a_reply_holds_off_the_timeout(rig: Rig) -> None:
    asked = await rig.memory.take_question()
    assert asked is not None
    rig.clock.now += 15
    await rig.publish(PlayerStartedSpeaking())
    rig.clock.now += 15
    assert await rig.memory.check_question() is False
    await rig.publish(PlayerSpeech(transcript="hmm, let me think"))
    rig.clock.now += 19
    assert await rig.memory.check_question() is False
    rig.clock.now += 1
    assert await rig.memory.check_question() is True


async def test_turns_that_do_not_answer_drop_it(rig: Rig) -> None:
    asked = await rig.memory.take_question()
    assert asked is not None
    await rig.turn("look at that slime")
    await rig.turn("ugh, missed")
    assert rig.status(asked.question_id) == "open"
    await rig.turn("anyway, where's the merchant")
    assert rig.status(asked.question_id) == "dropped"


@pytest.mark.parametrize("how", ["loaded", "changed"])
async def test_with_the_mic_off_replies_get_the_typed_timeout(how: str) -> None:
    r = Rig()
    if how == "loaded":
        PlayerStore(r.database.conn).save_settings(Settings(mic_enabled=False))
    await r.memory.start()
    # brain/app.py does this right after start().
    assert (await r.memory.load_settings(Settings)).mic_enabled is (how == "changed")
    if how == "changed":
        await r.publish(SettingsChanged(settings=Settings(mic_enabled=False)))
    await r.memory.wonder("playthrough", "progress", "Where are you up to?")
    assert await r.memory.take_question() is not None
    r.clock.now += 30
    assert await r.memory.check_question() is False
    r.clock.now += 15
    assert await r.memory.check_question() is True
    r.database.close()


async def test_a_released_question_goes_back_in_the_queue(rig: Rig) -> None:
    asked = await rig.memory.take_question()
    assert asked is not None
    await rig.memory.release_question(asked.question_id)
    await rig.memory.release_question("not-a-number")
    assert "ASKED" not in await rig.memory.context({})
    rig.clock.now += 60
    assert await rig.memory.check_question() is False
    again = await rig.memory.take_question()
    assert again is not None and again.question_id == asked.question_id


async def test_one_question_at_a_time(rig: Rig) -> None:
    await rig.memory.wonder("player", "goal", "What are you aiming for?")
    first = await rig.memory.take_question()
    assert first is not None
    assert await rig.memory.take_question() is None
    assert "UNSURE: What are you aiming for?" in await rig.memory.context({})
    await rig.memory.answer_question(None, "Just beat Skeletron")
    second = await rig.memory.take_question()
    assert second is not None and second.text == "What are you aiming for?"


async def test_an_answer_with_no_id_settles_the_question_just_asked(rig: Rig) -> None:
    asked = await rig.memory.take_question()
    assert asked is not None
    drain(rig.seen)
    result = await rig.memory.answer_question(None, "Just beat Skeletron")
    assert result is not None and result.fact is not None
    assert (result.fact.subject, result.fact.attribute) == ("playthrough", "progress")
    assert result.fact.source == "player"
    assert rig.status(asked.question_id) == "answered"
    assert "ASKED" not in await rig.memory.context({})
    toasts = [m for m in rig.sent if isinstance(m, MemoryToast)]
    assert "Just beat Skeletron" in toasts[-1].text
    learned = [(e.subject, e.attribute, e.source, e.outcome) for e in rig.learned()]
    assert learned == [("playthrough", "progress", "player", "replaced")]


async def test_a_late_answer_to_a_dropped_question_still_counts(rig: Rig) -> None:
    asked = await rig.memory.take_question()
    assert asked is not None
    rig.clock.now += 25
    assert await rig.memory.check_question() is True
    result = await rig.memory.answer_question(None, "hardmode")
    assert result is not None and result.outcome == "replaced"
    assert rig.status(asked.question_id) == "answered"
    fact = await rig.memory.current_fact("playthrough", "progress")
    assert fact is not None and fact.value == "hardmode"


async def test_no_with_a_correction_replaces_the_guess() -> None:
    r = Rig()
    await r.memory.start()
    guess = await r.memory.remember("playthrough", "progress", "early game", "observed", 0.3)
    assert guess.outcome == "uncertain"
    assert await r.memory.take_question() is not None
    result = await r.memory.answer_question(None, "No", correction="hardmode")
    assert result is not None and result.fact is not None
    assert result.fact.value == "hardmode" and result.fact.source == "player"
    assert [fact.value for fact in result.closed] == ["early game"]
    # The player said that guess is wrong, so the screen can't bring it back.
    again = await r.memory.remember("playthrough", "progress", "early game", "observed", 0.9)
    assert again.outcome == "ignored"
    r.database.close()


async def test_an_answer_with_nothing_asked_goes_nowhere(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    assert await rig.memory.answer_question(None, "yes") is None
    assert "nowhere to go" in caplog.text


async def test_fact_learned_only_when_a_fact_becomes_current(rig: Rig) -> None:
    drain(rig.seen)
    memory = rig.memory
    await memory.remember("player", "class", "mage", "player", 0.9)
    await memory.remember("player", "class", "mage", "player", 0.9)
    await memory.remember("player", "class", "ranger", "observed", 0.9)  # A dispute.
    await memory.remember("player", "class", "summoner", "wiki", 0.9)  # Ignored.
    await memory.remember("player", "class", "summoner", "player", 0.9)
    events = [(e.subject, e.attribute, e.source, e.outcome) for e in rig.learned()]
    assert events == [
        ("player", "class", "player", "stored"),
        ("player", "class", "player", "confirmed"),
        ("player", "class", "player", "replaced"),
    ]


async def test_forget_closes_the_key_and_shows_it(rig: Rig) -> None:
    await rig.memory.remember("player", "class", "mage", "observed", 0.8)
    assert await rig.memory.forget("player", "class") == 1
    assert await rig.memory.current_fact("player", "class") is None
    toasts = [message for message in rig.sent if isinstance(message, MemoryToast)]
    assert toasts[-1].text == "Forgot: player class: mage"
    assert await rig.memory.forget("player", "class") == 0
    assert len([m for m in rig.sent if isinstance(m, MemoryToast)]) == len(toasts)
    assert rig.learned()[-1].outcome == "stored"


async def test_questions_asked_before_a_restart_are_let_go(tmp_path) -> None:
    database = Database(connect(tmp_path / "brain.sqlite3"))
    first = Rig(database)
    await first.memory.start()
    await first.memory.wonder("playthrough", "progress", "Where are you up to?")
    asked = await first.memory.take_question()
    assert asked is not None

    second = Rig(database)
    await second.memory.start()
    assert second.status(asked.question_id) == "dropped"
    database.close()


async def test_run_drops_an_overdue_question_on_its_own() -> None:
    r = Rig(check_s=0.0)
    await r.memory.start()
    await r.memory.wonder("playthrough", "progress", "Where are you up to?")
    asked = await r.memory.take_question()
    assert asked is not None
    r.clock.now += 60
    task = asyncio.create_task(r.memory.run())
    # The fake clock is already past the timeout. This only waits for the database thread.
    for _ in range(300):
        await asyncio.sleep(0.01)
        if r.status(asked.question_id) == "dropped":
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert r.status(asked.question_id) == "dropped"
    r.database.close()
