from pathlib import Path

import pytest

from brain.memory.db import connect
from brain.memory.facts import FactStore
from brain.memory.gather import gather_context
from brain.memory.profile import PlayerStore, ProfileStore
from brain.memory.sessions import SessionStore
from brain.memory.snapshot import connect_replay, dump_snapshot
from brain.memory.unknowns import UnknownStore

GAME = "Some Game"


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    conn = connect(":memory:")
    sessions = SessionStore(conn)
    ProfileStore(conn).set_brief(GAME, "A game about things")
    PlayerStore(conn).set("nickname", "O'Brien")
    played = sessions.start(GAME)
    sessions.log_turn(played.id, "player", "it's; DROP TABLE facts; -- 'quoted'\nnext line")
    sessions.add_note(played.id, "recap", "Found the shimmer lake.", 0.0, 1.0)
    sessions.end(played.id)
    FactStore(conn).remember(GAME, "player", "class", "summoner", "player", 0.9)
    UnknownStore(conn).wonder(GAME, "shimmer", "meaning", "What's shimmer?")
    path = tmp_path / "replay_memory.sql"
    path.write_text(dump_snapshot(conn), encoding="utf-8")
    conn.close()
    return path


def test_snapshot_restores_what_the_talker_needs(snapshot: Path) -> None:
    conn = connect_replay(snapshot)
    current = SessionStore(conn).start(GAME)

    inputs = gather_context(conn, GAME, current.id, {})

    assert inputs.brief == "A game about things"
    assert inputs.last_session == "Found the shimmer lake."
    assert [fact.value for fact in inputs.facts] == ["summoner"]
    assert list(inputs.unsure) == ["What's shimmer?"]
    assert PlayerStore(conn).get("nickname") == "O'Brien"
    conn.close()


def test_text_with_sql_in_it_survives_as_plain_data(snapshot: Path) -> None:
    conn = connect_replay(snapshot)
    played = conn.execute("SELECT id FROM sessions").fetchone()["id"]
    turns = SessionStore(conn).recent_turns(played)
    assert turns[0].text == "it's; DROP TABLE facts; -- 'quoted'\nnext line"
    assert len(FactStore(conn).current(GAME)) == 1
    conn.close()


def test_search_indexes_are_rebuilt(snapshot: Path) -> None:
    conn = connect_replay(snapshot)
    assert [fact.value for fact in FactStore(conn).search(GAME, "summoner")] == ["summoner"]
    assert len(SessionStore(conn).search_notes(GAME, "shimmer")) == 1
    conn.close()


def test_every_run_starts_from_the_same_state(snapshot: Path) -> None:
    first = connect_replay(snapshot)
    FactStore(first).remember(GAME, "player", "goal", "added during replay", "player", 0.9)
    first.close()

    second = connect_replay(snapshot)
    assert [fact.value for fact in FactStore(second).current(GAME)] == ["summoner"]
    second.close()


def test_snapshot_is_unchanged_by_a_run(snapshot: Path) -> None:
    before = snapshot.read_bytes()
    conn = connect_replay(snapshot)
    FactStore(conn).remember(GAME, "player", "goal", "added during replay", "player", 0.9)
    conn.close()
    assert snapshot.read_bytes() == before


def test_missing_snapshot_starts_empty(tmp_path: Path) -> None:
    conn = connect_replay(tmp_path / "nope.sql")
    assert FactStore(conn).current(GAME) == []
    conn.close()


def test_broken_snapshot_still_lets_replay_run_with_no_partial_data(tmp_path: Path) -> None:
    path = tmp_path / "broken.sql"
    path.write_text(
        "INSERT INTO player (key, value) VALUES ('loaded', '1');\n"
        "INSERT INTO nowhere VALUES (1);\n",
        encoding="utf-8",
    )
    conn = connect_replay(path)
    assert PlayerStore(conn).get("loaded") is None
    conn.close()
