import sqlite3
from collections.abc import Iterator
from itertools import count

import pytest

from brain.memory.browse import browse
from brain.memory.db import connect
from brain.memory.facts import FactStore
from brain.memory.sessions import SessionStore
from brain.memory.unknowns import UnknownStore

GAME = "Some Game"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def facts(conn: sqlite3.Connection) -> FactStore:
    ticks = count(1)
    return FactStore(conn, clock=lambda: float(next(ticks)))


def test_lists_newest_current_facts_when_there_is_no_query(
    conn: sqlite3.Connection, facts: FactStore
) -> None:
    facts.remember(GAME, "player", "class", "Summoner", "player", 0.9)
    facts.remember(GAME, "player", "weapon", "Night's Edge", "observed", 0.7)
    facts.remember("Other Game", "player", "class", "Mage", "player", 0.9)

    found = browse(conn, GAME, "", include_history=False, limit=10)

    assert [(f.attribute, f.value, f.source) for f in found.facts] == [
        ("weapon", "Night's Edge", "observed"),
        ("class", "Summoner", "player"),
    ]


def test_history_shows_closed_facts_with_their_window(
    conn: sqlite3.Connection, facts: FactStore
) -> None:
    # The player correcting themselves closes the old fact rather than overwriting it.
    facts.remember(GAME, "player", "class", "Summoner", "player", 0.9)
    facts.remember(GAME, "player", "class", "Mage", "player", 0.9)

    current = browse(conn, GAME, "", include_history=False, limit=10).facts
    everything = browse(conn, GAME, "", include_history=True, limit=10).facts

    assert [f.value for f in current] == ["Mage"]
    closed = [f for f in everything if f.valid_to is not None]
    assert [f.value for f in closed] == ["Summoner"]
    assert closed[0].valid_to is not None and closed[0].valid_from < closed[0].valid_to


def test_search_matches_words_and_ignores_fts_syntax(
    conn: sqlite3.Connection, facts: FactStore
) -> None:
    facts.remember(GAME, "player", "weapon", "Night's Edge", "player", 0.9)
    facts.remember(GAME, "player", "class", "Summoner", "player", 0.9)

    found = browse(conn, GAME, 'what weapon" OR', include_history=False, limit=10)

    assert [f.value for f in found.facts] == ["Night's Edge"]


def test_questions_and_notes_are_included(conn: sqlite3.Connection) -> None:
    sessions = SessionStore(conn, clock=lambda: 5.0)
    session = sessions.start(GAME)
    sessions.add_note(session.id, "rolling", "Beat the Eye of Cthulhu.", 1.0, 2.0)
    UnknownStore(conn, clock=lambda: 6.0).wonder(
        GAME, "player", "goal", "What are you aiming for?", session.id
    )

    found = browse(conn, GAME, "", include_history=False, limit=10)
    searched = browse(conn, GAME, "eye", include_history=False, limit=10)

    assert [q.text for q in found.questions] == ["What are you aiming for?"]
    assert found.questions[0].status == "open"
    assert [n.body for n in found.notes] == ["Beat the Eye of Cthulhu."]
    assert [n.body for n in searched.notes] == ["Beat the Eye of Cthulhu."]
