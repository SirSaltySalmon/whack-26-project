import io
import json
import sqlite3
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from brain.memory.browse import games, preview_context
from brain.memory.db import connect, connect_readonly
from brain.memory.facts import FactStore
from brain.memory.profile import ProfileStore
from brain.memory.reader import MemoryReader, serve
from brain.memory.sessions import SessionStore
from brain.memory.unknowns import UnknownStore

OLD, NEW = "Terraria", "Minecraft"


def fill(conn: sqlite3.Connection) -> None:
    ticks = count(1)
    sessions = SessionStore(conn, clock=lambda: float(next(ticks)))
    facts = FactStore(conn, clock=lambda: float(next(ticks)))
    played = sessions.start(OLD)
    sessions.add_note(played.id, "recap", "Beat the Eye of Cthulhu.", 0.0, 1.0)
    facts.remember(OLD, "player", "class", "Summoner", "player", 0.9)
    facts.remember(OLD, "player", "class", "Mage", "player", 0.9)
    sessions.start(NEW)
    facts.remember(NEW, "player", "base", "Near the river", "player", 0.9)
    # Facts with no game apply everywhere, so they don't make a game of their own.
    facts.remember(None, "player", "spoilers", "Hates them", "player", 0.9)
    UnknownStore(conn).wonder(NEW, "player", "goal", "What are you building?")
    ProfileStore(conn).set_brief("Never Played", "Learned, then never started")


@pytest.fixture
def memory_file(tmp_path: Path) -> Path:
    path = tmp_path / "brain.sqlite3"
    conn = connect(path)
    fill(conn)
    conn.close()
    return path


def ask(reader: MemoryReader, *requests: dict[str, Any] | str) -> list[dict[str, Any]]:
    lines = [r if isinstance(r, str) else json.dumps(r) for r in requests]
    out = io.StringIO()
    serve(reader, io.StringIO("\n".join(lines) + "\n"), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_games_are_listed_most_recently_played_first() -> None:
    conn = connect(":memory:")
    fill(conn)

    found = games(conn)

    assert [game.title for game in found] == [NEW, OLD, "Never Played"]
    old = found[1]
    # Only current facts count: Summoner was replaced by Mage.
    assert (old.facts, old.questions, old.sessions) == (1, 0, 1)
    assert (found[0].facts, found[0].questions) == (1, 1)
    assert found[2].last_played is None and found[2].sessions == 0


def test_preview_is_what_the_next_session_of_that_game_starts_with() -> None:
    conn = connect(":memory:")
    fill(conn)

    old = preview_context(conn, OLD, "")
    new = preview_context(conn, NEW, "")

    assert "Beat the Eye of Cthulhu." in old and "Mage" in old
    assert "Near the river" not in old
    assert "Near the river" in new and "Beat the Eye" not in new
    assert "Hates them" in old and "Hates them" in new


def test_reader_defaults_to_the_game_played_last_and_can_pick_another(
    memory_file: Path,
) -> None:
    replies = ask(
        MemoryReader(memory_file),
        {"type": "memory.list_games", "request_id": "r1"},
        {"type": "memory.query", "request_id": "r2"},
        {"type": "memory.query", "request_id": "r3", "game": OLD, "include_history": True},
        {"type": "memory.context_preview", "request_id": "r4", "text": "eye", "game": OLD},
    )

    listed, latest, picked, preview = replies
    assert listed["type"] == "memory.games" and listed["live"] is False
    assert listed["current"] == NEW
    assert {f["value"] for f in latest["facts"]} == {"Near the river", "Hates them"}
    assert [q["text"] for q in latest["questions"]] == ["What are you building?"]
    assert {f["value"] for f in picked["facts"]} == {"Summoner", "Mage", "Hates them"}
    assert [n["body"] for n in picked["notes"]] == ["Beat the Eye of Cthulhu."]
    assert preview["type"] == "memory.context" and "Mage" in preview["context"]
    assert [r["request_id"] for r in replies] == ["r1", "r2", "r3", "r4"]


def test_reader_never_writes(memory_file: Path) -> None:
    conn = connect_readonly(memory_file)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("DELETE FROM facts")
    conn.close()


def test_without_memory_yet_it_answers_empty_and_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "data" / "brain.sqlite3"
    reader = MemoryReader(path)

    listed, found = ask(
        reader,
        {"type": "memory.list_games", "request_id": "r1"},
        {"type": "memory.query", "request_id": "r2"},
    )

    assert listed["games"] == [] and listed["current"] is None
    assert found["facts"] == []
    assert not path.parent.exists()

    # Once the partner has written memory, the same reader finds it.
    conn = connect(path)
    fill(conn)
    conn.close()
    (later,) = ask(reader, {"type": "memory.list_games", "request_id": "r3"})
    assert later["current"] == NEW


def test_other_requests_and_bad_lines_get_errors_not_a_crash(memory_file: Path) -> None:
    replies = ask(
        MemoryReader(memory_file),
        "not json",
        "",
        {"type": "voice.preview", "text": "Hi"},
        {"type": "memory.query", "request_id": "r1", "game": NEW},
    )

    invalid, refused, answered = replies
    assert invalid == {"type": "control.error", "request_id": None, "message": "Invalid request"}
    assert refused["type"] == "control.error" and "partner is off" in refused["message"]
    assert answered["type"] == "memory.results"


def test_memory_from_another_schema_says_so(tmp_path: Path) -> None:
    path = tmp_path / "brain.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE facts (id INTEGER)")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    (reply,) = ask(MemoryReader(path), {"type": "memory.list_games", "request_id": "r1"})

    assert reply["type"] == "control.error" and reply["request_id"] == "r1"
    assert "schema 1" in reply["message"]
