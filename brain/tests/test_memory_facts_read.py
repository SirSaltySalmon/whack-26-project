import sqlite3
from collections.abc import Iterator
from itertools import count

import pytest

from brain.memory.db import connect
from brain.memory.facts import FactStore

GAME = "Some Game"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def store(conn: sqlite3.Connection) -> FactStore:
    ticks = count(1)
    return FactStore(conn, clock=lambda: float(next(ticks)))


def remember(store: FactStore, value: str, source: str, confidence: float = 0.8):
    return store.remember(GAME, "player", "class", value, source, confidence)  # type: ignore[arg-type]


def current_values(store: FactStore) -> list[str]:
    return [fact.value for fact in store.current(GAME, "player", "class")]


# --- Game scoping ---
def test_games_dont_share_facts(store: FactStore) -> None:
    store.remember("A", "player", "class", "mage", "player", 0.9)
    store.remember("B", "player", "class", "ranger", "observed", 0.9)
    assert [f.value for f in store.current("A")] == ["mage"]
    assert [f.value for f in store.search("A", "ranger")] == []
    assert [f.value for f in store.search("B", "ranger")] == ["ranger"]


def test_cross_game_facts_appear_in_every_game(store: FactStore) -> None:
    store.remember(None, "player", "spoilers", "dislikes them", "player", 0.9)
    store.remember("A", "player", "class", "mage", "player", 0.9)
    assert {f.value for f in store.current("A")} == {"dislikes them", "mage"}
    assert [f.value for f in store.current("B")] == ["dislikes them"]
    assert [f.value for f in store.current(None)] == ["dislikes them"]
    assert [f.value for f in store.search("B", "spoilers")] == ["dislikes them"]


def test_cross_game_and_game_facts_dont_conflict(store: FactStore) -> None:
    store.remember(None, "player", "class", "mage", "player", 0.9)
    result = store.remember("A", "player", "class", "ranger", "observed", 0.9)
    assert result.outcome == "stored"


# --- Reading ---
def test_current_orders_by_authority_then_newest(store: FactStore) -> None:
    store.remember(GAME, "s", "a", "wiki value", "wiki", 0.5)
    store.remember(GAME, "s", "b", "old player", "player", 0.5)
    store.remember(GAME, "s", "c", "observed", "observed", 0.5)
    store.remember(GAME, "s", "d", "new player", "player", 0.5)
    assert [f.value for f in store.current(GAME)] == [
        "new player",
        "old player",
        "observed",
        "wiki value",
    ]


def test_current_filters_and_limits(store: FactStore) -> None:
    store.remember(GAME, "base", "location", "east", "player", 0.9)
    store.remember(GAME, "base", "size", "large", "player", 0.9)
    store.remember(GAME, "player", "class", "mage", "player", 0.9)
    assert len(store.current(GAME, subject="BASE")) == 2
    assert [f.value for f in store.current(GAME, attribute="size")] == ["large"]
    assert [f.value for f in store.current(GAME, "base", "location")] == ["east"]
    assert len(store.current(GAME, limit=1)) == 1


@pytest.mark.parametrize(
    "query", ["what's the boss", "where's the boss?", "boss-fight", 'the "boss" NEAR(', "BOSS*"]
)
def test_search_handles_punctuation(store: FactStore, query: str) -> None:
    store.remember(GAME, "next boss", "plan", "build an arena", "player", 0.9)
    assert [f.value for f in store.search(GAME, query)] == ["build an arena"]


@pytest.mark.parametrize("query", ["", "   ", "?!", "what is it"])
def test_search_with_nothing_to_look_for_is_empty(store: FactStore, query: str) -> None:
    store.remember(GAME, "next boss", "plan", "build an arena", "player", 0.9)
    assert store.search(GAME, query) == []


def test_search_finds_facts_by_subject(store: FactStore) -> None:
    fact = store.remember(GAME, "Eye of Cthulhu", "plan", "fight at night", "player", 0.9).fact
    assert fact is not None
    assert [f.id for f in store.search(GAME, "Cthulhu")] == [fact.id]


def test_search_excludes_closed_facts(store: FactStore) -> None:
    fact = store.remember(GAME, "base", "location", "east", "player", 0.9).fact
    assert fact is not None
    assert store.search(GAME, "east") != []
    store.close(fact.id)
    assert store.search(GAME, "east") == []
    assert store.current(GAME) == []


def test_close_is_idempotent_and_keeps_the_first_time(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    fact = store.remember(GAME, "base", "location", "east", "player", 0.9).fact
    assert fact is not None
    store.close(fact.id)
    first = conn.execute("SELECT valid_to FROM facts").fetchone()[0]
    store.close(fact.id)
    assert conn.execute("SELECT valid_to FROM facts").fetchone()[0] == first
