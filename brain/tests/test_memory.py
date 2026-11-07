import sqlite3
from pathlib import Path

import sqlite_vec

from brain.memory.store import MemoryStore, connect


def test_uses_wal_on_disk(tmp_path: Path) -> None:
    conn = connect(tmp_path / "nested" / "brain.sqlite3")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()


def test_search_finds_current_facts_only() -> None:
    store = MemoryStore(connect(":memory:"))
    old = store.add_fact("boss", "Eye of Cthulhu", "player", 0.9)
    assert [f.id for f in store.search_current("Cthulhu")] == [old]
    store.close_fact(old)
    assert store.search_current("Cthulhu") == []


def test_wiki_facts_start_tentative() -> None:
    store = MemoryStore(connect(":memory:"))
    store.add_fact("drop", "wood", "wiki", 0.5)
    store.add_fact("goal", "wood", "player", 0.9)
    tentative = {f.source: f.tentative for f in store.search_current("wood")}
    assert tentative == {"wiki": True, "player": False}


def test_sqlite_vec_loads() -> None:
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    assert conn.execute("SELECT vec_version()").fetchone()[0].startswith("v")
    conn.close()
