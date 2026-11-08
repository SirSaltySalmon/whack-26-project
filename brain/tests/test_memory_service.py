import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel

from brain.events import EventBus, GameEvent, PlayerSpeech, QuestionAnswered, SettingsChanged
from brain.llm.base import ChatTurn, LLMUnavailableError, System, TextLLM
from brain.memory.db import Database, connect
from brain.memory.notes import NoteWriter
from brain.memory.service import MemoryService
from shared.protocol import BrainMessage
from shared.protocol.messages import MemoryToast

GAME = "Test Game"


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def stream_text(
        self, system: System, prompt: str, max_tokens: int, history: Sequence[ChatTurn] = ()
    ) -> AsyncIterator[str]:
        yield self.reply


def no_llm() -> TextLLM:
    raise LLMUnavailableError("no key in tests")


class Harness:
    def __init__(self, llm_provider=no_llm, vault_dir: Path | None = None, min_events: int = 2):
        self.database = Database(connect(":memory:"))
        self.bus = EventBus()
        self.sent: list[BrainMessage] = []
        self.memory = MemoryService(
            self.database,
            self.bus,
            self._send,
            GAME,
            NoteWriter(llm_provider),
            vault_dir=vault_dir,
            note_min_new_events=min_events,
        )

    async def _send(self, message: BrainMessage) -> None:
        self.sent.append(message)

    async def drain(self) -> None:
        """Handles everything published so far, without running the forever loops."""
        queue = self.memory._events
        while not queue.empty():
            await self.memory._handle_safely(queue.get_nowait())

    @property
    def toasts(self) -> list[MemoryToast]:
        return [m for m in self.sent if isinstance(m, MemoryToast)]


@pytest.fixture
async def harness():
    h = Harness()
    await h.memory.start()
    yield h
    h.database.close()


async def test_bus_events_reach_memory_and_context(harness: Harness) -> None:
    harness.bus.publish(GameEvent(name="boss_killed"))
    harness.bus.publish(PlayerSpeech(transcript="I'm building an arena"))
    await harness.drain()
    await harness.memory.record_partner_turn("Nice, good plan.")

    context = await harness.memory.context({"health": "low"})
    assert "health" in context
    assert "I'm building an arena" in context
    assert "Nice, good plan." in context


async def test_new_fact_shows_a_toast_but_a_repeat_does_not(harness: Harness) -> None:
    await harness.memory.remember("player", "class", "summoner", "player", 0.9)
    await harness.memory.remember("player", "class", "summoner", "player", 0.9)
    assert len(harness.toasts) == 1
    assert "summoner" in harness.toasts[0].text
    assert harness.toasts[0].source == "player"


async def test_failed_toast_still_keeps_the_fact(harness: Harness) -> None:
    async def broken_send(_: BrainMessage) -> None:
        raise ConnectionError("socket closed")

    harness.memory._send = broken_send
    result = await harness.memory.remember("player", "class", "summoner", "player", 0.9)
    assert result.outcome == "stored"
    assert "summoner" in await harness.memory.context({})


async def test_conflict_becomes_a_question_and_the_answer_settles_it(harness: Harness) -> None:
    await harness.memory.remember("player", "base", "east of spawn", "player", 0.9)
    conflict = await harness.memory.remember("player", "base", "west of spawn", "observed", 0.9)
    assert conflict.outcome == "conflict"

    asked = await harness.memory.take_question()
    assert asked is not None
    assert set(asked.options) == {"east of spawn", "west of spawn"}
    # The director's budget depends on one question reaching the player only once.
    assert await harness.memory.take_question() is None

    harness.bus.publish(QuestionAnswered(question_id=asked.question_id, answer="west of spawn"))
    await harness.drain()
    context = await harness.memory.context({})
    assert "west of spawn" in context
    assert "east of spawn" not in context
    assert "west of spawn" in harness.toasts[-1].text


async def test_invalid_question_id_is_ignored(harness: Harness) -> None:
    harness.bus.publish(QuestionAnswered(question_id="not-a-number", answer="yes"))
    harness.bus.publish(QuestionAnswered(question_id="999", answer="yes"))
    await harness.drain()
    assert harness.toasts == []


async def test_a_bad_event_does_not_stop_later_ones(harness: Harness) -> None:
    # A set isn't JSON serializable, so writing this event fails.
    harness.bus.publish(GameEvent(name="bad", data={"x": {1, 2}}))
    harness.bus.publish(PlayerSpeech(transcript="still listening"))
    await harness.drain()
    assert "still listening" in await harness.memory.context({})


async def test_note_waits_for_enough_events(harness: Harness) -> None:
    harness.bus.publish(GameEvent(name="only_one"))
    await harness.drain()
    assert await harness.memory.flush_note() is False


async def test_note_without_an_llm_falls_back_and_appears_in_context(harness: Harness) -> None:
    harness.bus.publish(GameEvent(name="player_died"))
    harness.bus.publish(GameEvent(name="player_died"))
    await harness.drain()
    assert await harness.memory.flush_note() is True
    assert "player_died" in await harness.memory.context({})
    # Those events are already covered, so the same ones can't produce a second note.
    assert await harness.memory.flush_note() is False


async def test_note_stores_drafted_facts_as_player_claims() -> None:
    reply = json.dumps(
        {
            "body": "Player wants to fight the boss.",
            "facts": [
                {"subject": "player", "attribute": "class", "value": "summoner"},
                {"subject": "", "attribute": "bad", "value": "rejected"},
            ],
        }
    )
    h = Harness(lambda: FakeLLM(reply))
    await h.memory.start()
    h.bus.publish(PlayerSpeech(transcript="I play summoner"))
    h.bus.publish(GameEvent(name="boss_seen"))
    await h.drain()
    assert await h.memory.flush_note() is True
    assert [t.source for t in h.toasts] == ["player"]
    assert "summoner" in await h.memory.context({})
    h.database.close()


async def test_finish_saves_queued_events_and_writes_a_recap(tmp_path: Path) -> None:
    database = Database(connect(tmp_path / "brain.sqlite3"))
    bus = EventBus()

    async def send(_: BrainMessage) -> None: ...

    memory = MemoryService(
        database, bus, send, GAME, NoteWriter(no_llm), vault_dir=tmp_path / "vault"
    )
    first = await memory.start()
    bus.publish(PlayerSpeech(transcript="Heading home for tonight"))
    await memory.finish()

    row = database.conn.execute(
        "SELECT ended_at FROM sessions WHERE id = ?", (first.id,)
    ).fetchone()
    assert row["ended_at"] is not None
    assert list((tmp_path / "vault").rglob("*.md"))

    # The next session should pick up where the last one ended.
    bus_two = EventBus()
    memory_two = MemoryService(database, bus_two, send, GAME, NoteWriter(no_llm))
    await memory_two.start()
    assert "Heading home for tonight" in await memory_two.context({})
    database.close()


async def test_run_finishes_cleanly_when_cancelled() -> None:
    h = Harness()
    await h.memory.start()
    task = asyncio.create_task(h.memory.run())
    h.bus.publish(PlayerSpeech(transcript="one last thing"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    row = h.database.conn.execute("SELECT ended_at FROM sessions").fetchone()
    assert row["ended_at"] is not None
    h.database.close()


class FakeSettings(BaseModel):
    proactive: bool = True


async def test_settings_survive_a_restart(harness: Harness) -> None:
    harness.bus.publish(SettingsChanged(settings=FakeSettings(proactive=False)))
    await harness.drain()
    assert (await harness.memory.load_settings(FakeSettings)).proactive is False


async def test_a_finished_sessions_page_shows_its_end(tmp_path: Path) -> None:
    h = Harness(vault_dir=tmp_path / "vault")
    session = await h.memory.start()
    # Enough for a recap, whose export runs before the session is marked ended.
    h.bus.publish(PlayerSpeech(transcript="Heading home for tonight"))
    await h.memory.finish()
    page = next((tmp_path / "vault").rglob(f"* Session {session.id}.md"))
    assert "ended: null" not in page.read_text(encoding="utf-8")
    h.database.close()
