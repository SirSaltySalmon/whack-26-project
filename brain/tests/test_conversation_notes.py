"""Tool and game-event notes in the conversation every reply is sent with (docs/CONTEXT_PLAN.md,
C4): where they land, how floods collapse, and that they stay inside the history budget."""

import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import BaseModel

from brain.agent.schemas import SEEN_LABEL
from brain.agent.tool_notes import note_hook
from brain.agent.tools import Tool, ToolRegistry, TurnContext
from brain.events import EventBus
from brain.llm.base import ChatTurn, LLMUnavailableError, TextLLM, ToolCall
from brain.memory.context import DEFAULT_LIMITS, ContextLimits
from brain.memory.db import Database, connect
from brain.memory.gather import gather_context
from brain.memory.layers import build_context
from brain.memory.models import LoggedEvent, Speaker
from brain.memory.notes import NoteWriter, render_events
from brain.memory.service import MemoryService
from brain.memory.sessions import SessionStore
from shared.protocol import BrainMessage

GAME = "Game"
START = 1000.0


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now


class Log:
    """Writes one session's events at chosen seconds into it."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.clock = Clock()
        self.store = SessionStore(conn, self.clock)
        self.session = self.store.start(GAME).id

    def _at(self, seconds: float) -> None:
        self.clock.now = START + seconds

    def said(self, speaker: Speaker, text: str, at: float) -> None:
        self._at(at)
        self.store.log_turn(self.session, speaker, text)

    def tool(self, name: str, note: str, at: float, ok: bool = True) -> None:
        self._at(at)
        self.store.log_tool(self.session, name, note, ok)

    def event(self, name: str, data: dict[str, Any] | None, at: float) -> None:
        self._at(at)
        self.store.log_event(self.session, name, data)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    yield connection
    connection.close()


def history(
    conn: sqlite3.Connection,
    log: Log,
    current: str | None = None,
    limits: ContextLimits = DEFAULT_LIMITS,
) -> tuple[ChatTurn, ...]:
    inputs = gather_context(conn, GAME, log.session, {}, current=current, limits=limits)
    return build_context(inputs, limits).history


def notes(turns: tuple[ChatTurn, ...]) -> list[str]:
    return [line for turn in turns for line in turn.text.split("\n") if line.startswith("(note")]


def test_notes_land_where_they_happened_on_the_players_side(conn: sqlite3.Connection) -> None:
    log = Log(conn)
    log.said("player", "what's in my hand?", 10)
    log.tool("look_closer", "looked closer at the bottom left: holding a Copper Pickaxe", 12)
    log.said("partner", "A Copper Pickaxe.", 13)
    log.event("danger_started", {"level": "high", "threats": ["Blue Slime"]}, 20)
    log.said("partner", "Slime incoming!", 21)
    log.tool("look_back", "tried look_back, but it timed out", 25, ok=False)
    log.said("player", "thanks", 30)
    assert history(conn, log, current="thanks") == (
        ChatTurn(
            "user",
            "what's in my hand?\n(note, 0:12 into the session) you looked closer at the bottom"
            " left: holding a Copper Pickaxe",
        ),
        ChatTurn("assistant", "A Copper Pickaxe."),
        ChatTurn("user", "(note, 0:20 into the session) game: danger started (high): Blue Slime"),
        ChatTurn("assistant", "Slime incoming!"),
        # The words being answered are the latest message, but what happened before them stays.
        ChatTurn("user", "(note, 0:25 into the session) you tried look_back, but it timed out"),
    )


def test_a_run_of_the_same_event_becomes_one_note(conn: sqlite3.Connection) -> None:
    log = Log(conn)
    log.said("player", "let's mine", 1)
    for i in range(5):
        before, after = 10 + 5 * i, 15 + 5 * i
        log.event("coins_changed", {"value": after, "display": str(after), "from": before}, 2 + i)
    log.event("danger_started", {"level": "medium"}, 8)
    log.event("danger_started", {"level": "medium"}, 9)
    log.said("partner", "Rich already.", 10)
    assert notes(history(conn, log)) == [
        "(note, 0:06 into the session) game: coins changed: 10 to 35 (5 changes)",
        "(note, 0:09 into the session) game: danger started (medium) (2 times)",
    ]


def test_repeats_with_something_said_between_stay_apart(conn: sqlite3.Connection) -> None:
    log = Log(conn)
    log.event("health_low", {"percent": 20}, 1)
    log.said("partner", "Careful!", 2)
    log.event("health_low", {"percent": 15}, 3)
    assert notes(history(conn, log)) == [
        "(note, 0:01 into the session) game: health low (20%)",
        "(note, 0:03 into the session) game: health low (15%)",
    ]


def test_only_the_newest_runs_of_a_game_event_are_kept(conn: sqlite3.Connection) -> None:
    log = Log(conn)
    for i in range(5):
        log.event("mana_low", {"display": f"{i}/200", "value": i}, 2 * i)
        log.said("partner", f"Mana again {i}.", 2 * i + 1)
    kept = notes(history(conn, log))
    assert [line.split("game: ")[1] for line in kept] == [
        "mana low: 2/200",
        "mana low: 3/200",
        "mana low: 4/200",
    ]


def test_tool_notes_never_collapse(conn: sqlite3.Connection) -> None:
    log = Log(conn)
    log.tool("point_at", "pointed at Workbench", 1)
    log.tool("point_at", "pointed at Anvil", 2)
    assert notes(history(conn, log)) == [
        "(note, 0:01 into the session) you pointed at Workbench",
        "(note, 0:02 into the session) you pointed at Anvil",
    ]


def test_notes_stay_inside_the_history_budget(conn: sqlite3.Connection) -> None:
    log = Log(conn)
    for i in range(40):
        log.said("player", f"question number {i}", 3 * i)
        log.tool("look_closer", f"looked closer: thing number {i}", 3 * i + 1)
        log.said("partner", f"answer number {i}", 3 * i + 2)
    limits = ContextLimits(history_chars=600)
    turns = history(conn, log, limits=limits)
    assert sum(len(turn.text) + 1 for turn in turns) <= 600
    # The newest items are the ones kept.
    assert turns[-1] == ChatTurn("assistant", "answer number 39")
    assert notes(turns)[-1].endswith("you looked closer: thing number 39")


def test_notes_from_another_session_never_appear(conn: sqlite3.Connection) -> None:
    mine, other = Log(conn), Log(conn)
    other.tool("lookup_wiki", "checked the wiki on Anvil: crafted from iron", 1)
    other.event("player_died", None, 2)
    mine.said("player", "hello", 3)
    assert history(conn, mine) == (ChatTurn("user", "hello"),)


def test_a_flood_of_events_cant_push_turns_out(conn: sqlite3.Connection) -> None:
    log = Log(conn)
    log.event("early_event", {"display": "before everything"}, 0.5)
    for i in range(6):
        log.said("player" if i % 2 == 0 else "partner", f"line {i}", 1 + i)
    for i in range(200):
        # Different names, so nothing collapses; each name keeps only its newest runs.
        log.event(f"reader_{i % 7}", {"display": str(i)}, 10 + i)
    limits = ContextLimits(max_turns=4, max_notes=60)
    items = gather_context(conn, GAME, log.session, {}, limits=limits).turns
    assert [item.text for item in items if item.kind != "note"] == [
        f"line {i}" for i in range(2, 6)
    ]
    texts = [item.text for item in items if item.kind == "note"]
    # Older than the oldest turn read, so there's no conversation around it.
    assert not any("before everything" in text for text in texts)
    assert len(texts) <= 7 * 3


def test_the_session_note_writer_reads_a_tool_note_as_one_line() -> None:
    event = LoggedEvent(
        1, 1, 5.0, "tool.look_closer", {"text": "looked closer: a chest", "ok": True}
    )
    assert render_events([event]) == "+0s partner's look_closer tool: looked closer: a chest"


class NoInput(BaseModel):
    pass


def no_llm() -> TextLLM:
    raise LLMUnavailableError("no key in tests")


async def test_a_tool_call_reaches_the_next_turns_conversation() -> None:
    database = Database(connect(":memory:"))
    sent: list[BrainMessage] = []

    async def send(message: BrainMessage) -> None:
        sent.append(message)

    memory = MemoryService(database, EventBus(), send, GAME, NoteWriter(no_llm))
    await memory.start()
    try:

        async def look(_arguments: NoInput, _turn: TurnContext) -> str:
            return f"{SEEN_LABEL} a wooden chest"

        registry = ToolRegistry([Tool("look_closer", "Looks.", NoInput, look)])
        registry = registry.reporting(note_hook(memory.record_tool))
        await registry.run(ToolCall("look_closer", {"area": "center"}), TurnContext())
        await memory.record_partner_turn("It's a wooden chest.")
        context = await memory.talker_context({}, "what was that")
        assert "you looked closer at the center: a wooden chest" in context.history[0].text
        assert context.history[-1] == ChatTurn("assistant", "It's a wooden chest.")
    finally:
        database.close()
