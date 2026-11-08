import json
import sqlite3
import time
from collections.abc import Iterator

import pytest

from brain.memory.context import ContextLimits, format_fact
from brain.memory.db import connect
from brain.memory.gather import gather_context
from brain.memory.layers import render_context
from brain.memory.models import Fact, Source

# How the layers are laid out and trimmed is in test_memory_layers.py.


def fact(
    subject: str = "base",
    attribute: str = "location",
    value: str = "east of spawn",
    source: Source = "player",
    tentative: bool = False,
) -> Fact:
    return Fact(1, "Game", subject, attribute, value, source, 0.9, tentative, 1.0)


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (fact(), "base / location: east of spawn (player said)"),
        (fact(source="observed"), "base / location: east of spawn (observed)"),
        (fact(source="wiki", tentative=True), "base / location: east of spawn (wiki, unconfirmed)"),
        (fact(subject="boss", attribute="boss", value="x"), "boss / boss: x (player said)"),
    ],
)
def test_fact_labels(item: Fact, expected: str) -> None:
    assert format_fact(item) == expected


# --- gather_context ---
@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    yield connection
    connection.close()


def add_session(conn: sqlite3.Connection, game: str = "Game", at: float = 1.0) -> int:
    cursor = conn.execute("INSERT INTO sessions (game, started_at) VALUES (?, ?)", (game, at))
    return int(cursor.lastrowid or 0)


def add_note(conn: sqlite3.Connection, session_id: int, kind: str, body: str, at: float) -> None:
    conn.execute(
        "INSERT INTO session_notes (session_id, kind, body, from_ts, to_ts, created_at)"
        " VALUES (?, ?, ?, 0, 0, ?)",
        (session_id, kind, body, at),
    )


def add_fact(
    conn: sqlite3.Connection,
    value: str,
    game: str | None = "Game",
    source: str = "player",
    at: float = 1.0,
    closed: bool = False,
    subject: str = "base",
) -> None:
    conn.execute(
        "INSERT INTO facts (game, subject, attribute, value, source, confidence, tentative,"
        " valid_from, valid_to) VALUES (?, ?, 'location', ?, ?, 0.9, ?, ?, ?)",
        (game, subject, value, source, source == "wiki", at, 9.0 if closed else None),
    )


def add_turn(conn: sqlite3.Connection, sid: int, name: str, data: str | None, at: float) -> None:
    conn.execute(
        "INSERT INTO events (session_id, ts, name, data) VALUES (?, ?, ?, ?)",
        (sid, at, name, data),
    )


def test_gather_reads_the_brief_note_and_live_state(conn: sqlite3.Connection) -> None:
    session = add_session(conn)
    conn.execute("INSERT INTO profile (game, brief, updated_at) VALUES ('Game', 'Sandbox', 1)")
    add_note(conn, session, "rolling", "older", 1.0)
    add_note(conn, session, "rolling", "newer", 2.0)
    inputs = gather_context(conn, "Game", session, {"health": "20"})
    assert inputs.brief == "Sandbox"
    assert inputs.session_note == "newer"
    assert inputs.live_state == {"health": "20"}


def test_last_session_prefers_a_recap_over_rolling_notes(conn: sqlite3.Connection) -> None:
    earlier = add_session(conn)
    add_note(conn, earlier, "recap", "the recap", 1.0)
    add_note(conn, earlier, "rolling", "a later rolling note", 2.0)
    current = add_session(conn, at=5.0)
    assert gather_context(conn, "Game", current, {}).last_session == "the recap"


def test_last_session_falls_back_to_newest_rolling_note(conn: sqlite3.Connection) -> None:
    earlier = add_session(conn)
    add_note(conn, earlier, "rolling", "first", 1.0)
    add_note(conn, earlier, "rolling", "second", 2.0)
    current = add_session(conn, at=5.0)
    assert gather_context(conn, "Game", current, {}).last_session == "second"


def test_a_session_with_no_notes_does_not_erase_the_one_before(conn: sqlite3.Connection) -> None:
    add_note(conn, add_session(conn), "recap", "real recap", 1.0)
    add_session(conn, at=2.0)  # Crashed before writing a note.
    current = add_session(conn, at=3.0)
    assert gather_context(conn, "Game", current, {}).last_session == "real recap"


def test_other_games_are_excluded(conn: sqlite3.Connection) -> None:
    other = add_session(conn, game="Other")
    add_note(conn, other, "recap", "secret dungeon", 1.0)
    add_fact(conn, "secret dungeon", game="Other")
    current = add_session(conn, game="Game", at=5.0)
    inputs = gather_context(conn, "Game", current, {}, query="secret dungeon")
    assert inputs.last_session is None
    assert inputs.facts == []
    assert inputs.recalled == []


def test_facts_are_current_and_ordered_by_authority_then_recency(conn: sqlite3.Connection) -> None:
    session = add_session(conn)
    add_fact(conn, "wiki claim", source="wiki", at=9.0)
    add_fact(conn, "seen", source="observed", at=8.0)
    add_fact(conn, "said old", at=1.0)
    add_fact(conn, "said new", at=2.0)
    add_fact(conn, "cross game", game=None, at=0.5)
    add_fact(conn, "closed", at=3.0, closed=True)
    values = [f.value for f in gather_context(conn, "Game", session, {}).facts]
    assert values == ["said new", "said old", "cross game", "seen", "wiki claim"]


def test_recall_finds_facts_and_notes_not_already_included(conn: sqlite3.Connection) -> None:
    earlier = add_session(conn)
    add_note(conn, earlier, "rolling", "Found a hidden cave near the lake", 1.0)
    add_note(conn, earlier, "recap", "Fought the cave boss", 2.0)
    current = add_session(conn, at=5.0)
    for i in range(ContextLimits().max_player_facts):
        add_fact(conn, f"filler {i}", at=10.0 + i)
    add_fact(conn, "cave entrance", at=1.0, subject="spot")
    inputs = gather_context(conn, "Game", current, {}, query="the cave?")
    assert inputs.last_session == "Fought the cave boss"
    assert any("cave entrance" in item for item in inputs.recalled)
    assert any("hidden cave" in item for item in inputs.recalled)
    assert not any("Fought" in item for item in inputs.recalled)


@pytest.mark.parametrize(
    "query", ["what's the boss", "where is it?", "Eye-of-Cthulhu", 'a"b', "NEAR(", "*", "", "?"]
)
def test_punctuation_in_a_query_never_raises(conn: sqlite3.Connection, query: str) -> None:
    gather_context(conn, "Game", add_session(conn), {}, query=query)


def test_turns_are_oldest_first_and_limited(conn: sqlite3.Connection) -> None:
    session = add_session(conn)
    for i in range(8):
        name = "turn.player" if i % 2 == 0 else "turn.partner"
        add_turn(conn, session, name, json.dumps({"text": f"line{i}"}), float(i))
    add_turn(conn, session, "boss_seen", None, 100.0)
    items = gather_context(conn, "Game", session, {}, limits=ContextLimits(max_turns=6)).turns
    turns = [item for item in items if item.kind != "note"]
    assert [t.text for t in turns] == [f"line{i}" for i in range(2, 8)]
    assert turns[-1].kind == "partner"
    # A game event isn't a turn and doesn't count toward max_turns: it comes back as a note.
    assert [(item.kind, item.text) for item in items[len(turns) :]] == [("note", "game: boss seen")]


@pytest.mark.parametrize("data", [None, "[1, 2]", '"text"', "{}", '{"text": 5}', '{"text": " "}'])
def test_turns_with_odd_data_are_skipped(conn: sqlite3.Connection, data: str | None) -> None:
    session = add_session(conn)
    add_turn(conn, session, "turn.player", data, 1.0)
    add_turn(conn, session, "turn.player", '{"text": "good"}', 2.0)
    assert [t.text for t in gather_context(conn, "Game", session, {}).turns] == ["good"]


def test_gather_is_fast_enough_for_the_voice_path(conn: sqlite3.Connection) -> None:
    session = add_session(conn)
    for i in range(500):
        add_fact(conn, f"value number {i} about caves", at=float(i), subject=f"subject {i}")
        add_turn(conn, session, "turn.player", json.dumps({"text": f"line {i}"}), float(i))
    conn.commit()
    best = float("inf")
    # The best of several runs, so another busy process can't fail this test.
    for _ in range(5):
        start = time.perf_counter()
        render_context(gather_context(conn, "Game", session, {"hp": "1"}, query="the caves?"))
        best = min(best, time.perf_counter() - start)
    assert best < 0.020
