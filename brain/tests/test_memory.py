import sqlite3
import threading
from pathlib import Path

import pytest
import sqlite_vec

from brain.memory.db import Database, connect
from brain.memory.fts import to_match_query


def test_uses_wal_on_disk(tmp_path: Path) -> None:
    conn = connect(tmp_path / "nested" / "brain.sqlite3")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()


def test_reopening_a_current_database_works(tmp_path: Path) -> None:
    path = tmp_path / "brain.sqlite3"
    connect(path).close()
    connect(path).close()


def test_refuses_a_database_from_an_older_schema(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE entities (id INTEGER PRIMARY KEY)")
    old.commit()
    old.close()
    with pytest.raises(RuntimeError, match="memory schema"):
        connect(path)


async def test_database_runs_off_the_event_loop_thread() -> None:
    database = Database(connect(":memory:"))
    caller = threading.get_ident()

    def query(conn: sqlite3.Connection) -> tuple[int, int]:
        return threading.get_ident(), conn.execute("SELECT 1").fetchone()[0]

    worker, value = await database.run(query)
    assert worker != caller
    assert value == 1
    database.close()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("what's the boss", '"s" OR "boss"'),
        ("where is it?", None),
        ("Eye-of-Cthulhu", '"eye" OR "cthulhu"'),
        ("boss OR NEAR(x)", '"boss" OR "near" OR "x"'),
        ("", None),
    ],
)
def test_match_query_is_always_safe(text: str, expected: str | None) -> None:
    assert to_match_query(text) == expected
    if expected is not None:
        conn = connect(":memory:")
        conn.execute("SELECT * FROM facts_fts WHERE facts_fts MATCH ?", (expected,))
        conn.close()


def test_sqlite_vec_loads() -> None:
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    assert conn.execute("SELECT vec_version()").fetchone()[0].startswith("v")
    conn.close()
