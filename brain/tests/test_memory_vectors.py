"""The sqlite-vec index, and keyword, meaning and hybrid recall. FakeEmbedder stands in for the
model, so nothing is downloaded."""

import logging
import sqlite3
from collections.abc import Iterator

import pytest

from brain.memory import vectors
from brain.memory.context import ContextLimits
from brain.memory.db import connect
from brain.memory.gather import gather_context
from brain.memory.models import Hit
from brain.memory.recall import VectorQuery, fuse
from brain.tests.fake_embedder import FakeEmbedder

ALIASES = {"house": "base", "home": "base", "loot": "chest"}
MIN_SIMILARITY = 0.1


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    try:
        vectors.prepare(connection, "fake-embedder", 256)
    except (AttributeError, sqlite3.Error) as error:
        # AttributeError is a Python built without extension loading, as on some Macs.
        pytest.skip(f"sqlite-vec can't load here: {error}")
    yield connection
    connection.close()


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder(ALIASES)


def add_session(conn: sqlite3.Connection, game: str = "Game") -> int:
    cursor = conn.execute("INSERT INTO sessions (game, started_at) VALUES (?, 1)", (game,))
    return int(cursor.lastrowid or 0)


def add_fact(
    conn: sqlite3.Connection,
    subject: str,
    attribute: str,
    value: str,
    *,
    game: str | None = "Game",
    at: float = 1.0,
    closed: bool = False,
) -> int:
    cursor = conn.execute(
        "INSERT INTO facts (game, subject, attribute, value, source, confidence, valid_from,"
        " valid_to) VALUES (?, ?, ?, ?, 'player', 0.9, ?, ?)",
        (game, subject, attribute, value, at, 9.0 if closed else None),
    )
    return int(cursor.lastrowid or 0)


def add_note(conn: sqlite3.Connection, session_id: int, body: str) -> int:
    cursor = conn.execute(
        "INSERT INTO session_notes (session_id, kind, body, from_ts, to_ts, created_at)"
        " VALUES (?, 'rolling', ?, 0, 0, 1)",
        (session_id, body),
    )
    return int(cursor.lastrowid or 0)


def add_filler(conn: sqlite3.Connection) -> None:
    """The talker always gets the newest player facts up to a cap and recall skips those, so
    these push the facts under test out of that list and into recall's reach."""
    for i in range(ContextLimits().max_player_facts):
        add_fact(conn, "filler", f"slot {i}", f"value {i}", at=10.0 + i)


def index(conn: sqlite3.Connection, embedder: FakeEmbedder) -> int:
    """SemanticRecall's sync, without the threads."""
    done = 0
    while items := vectors.pending(conn, 8):
        vectors.store(conn, items, embedder.embed_passages([item.text for item in items]))
        done += len(items)
    return done


def ask(embedder: FakeEmbedder, text: str, *, semantic_only: bool = False) -> VectorQuery:
    return VectorQuery(embedder.embed_query(text), semantic_only, MIN_SIMILARITY)


def recalled(conn: sqlite3.Connection, query: str, vector: VectorQuery | None) -> list[str]:
    session = add_session(conn)
    return list(gather_context(conn, "Game", session, {}, query=query, vector=vector).recalled)


# --- Chunks and indexing ---
def test_note_chunks_are_lines_under_their_heading() -> None:
    body = '**Events**\n- danger_started x2\n\n**Player said**\n- "where is my base"\n'
    assert vectors.note_chunks(body) == [
        "Events: danger_started x2",
        'Player said: "where is my base"',
    ]
    assert vectors.note_chunks("## Plan\n1. Build  a house\nLoose line") == [
        "Plan: Build a house",
        "Plan: Loose line",
    ]
    assert vectors.note_chunks("**Only a heading**") == ["**Only a heading**"]
    assert vectors.note_chunks("  \n ") == []


def test_indexing_covers_current_facts_and_notes_once(
    conn: sqlite3.Connection, embedder: FakeEmbedder
) -> None:
    add_fact(conn, "base", "location", "left of spawn")
    add_fact(conn, "player", "class", "Mage", closed=True)
    add_note(conn, add_session(conn), "**Events**\n- boss_killed x1\n- found_chest x2")
    assert index(conn, embedder) == 3
    assert embedder.passages == [
        "base location: left of spawn",
        "Events: boss_killed x1",
        "Events: found_chest x2",
    ]
    assert vectors.pending(conn, 8) == []


def test_a_note_is_never_split_across_batches(conn: sqlite3.Connection) -> None:
    session = add_session(conn)
    add_note(conn, session, "\n".join(f"- line {i}" for i in range(5)))
    add_note(conn, session, "- another")
    # One item of room still takes the whole first note, and stops there.
    assert [item.item_id for item in vectors.pending(conn, 1)] == [1] * 5


def test_a_new_model_rebuilds_the_index(conn: sqlite3.Connection, embedder: FakeEmbedder) -> None:
    add_fact(conn, "base", "location", "left of spawn")
    index(conn, embedder)
    vectors.prepare(conn, "fake-embedder", 256)
    assert vectors.pending(conn, 8) == []
    vectors.prepare(conn, "another-model", 128)
    assert [item.kind for item in vectors.pending(conn, 8)] == ["fact"]


# --- Search ---
def test_meaning_finds_what_keywords_miss(conn: sqlite3.Connection, embedder: FakeEmbedder) -> None:
    add_fact(conn, "base", "location", "left of spawn")
    add_fact(conn, "player", "class", "Mage")
    add_filler(conn)
    index(conn, embedder)
    assert recalled(conn, "where's my house", None) == []
    found = recalled(conn, "where's my house", ask(embedder, "where's my house"))
    assert found == ["base / location: left of spawn (player said)"]


def test_search_skips_closed_facts_other_games_and_weak_matches(
    conn: sqlite3.Connection, embedder: FakeEmbedder
) -> None:
    add_fact(conn, "base", "location", "old spot", closed=True)
    add_fact(conn, "base", "location", "other world", game="Other")
    add_note(conn, add_session(conn, "Other"), "- our base is by the lake")
    add_fact(conn, "base", "location", "everywhere", game=None)
    add_fact(conn, "pet", "name", "Biscuit")
    index(conn, embedder)
    hits = vectors.search(conn, "Game", embedder.embed_query("my house"), [], [], 5, 0.1)
    assert [hit.text for hit in hits] == ["base / location: everywhere (player said)"]


def test_each_note_is_found_once_by_its_best_line(
    conn: sqlite3.Connection, embedder: FakeEmbedder
) -> None:
    note = add_note(conn, add_session(conn), "- built a base\n- the base has a chest\n- slept")
    index(conn, embedder)
    hits = vectors.search(conn, "Game", embedder.embed_query("base chest"), [], [], 5, 0.1)
    assert hits == [Hit(("note", note), "the base has a chest")]
    assert vectors.search(conn, "Game", embedder.embed_query("base"), [], [note], 5, 0.1) == []


# --- Modes ---
def test_fuse_ranks_what_both_found_first_and_breaks_ties_by_order() -> None:
    a, b, c = (Hit(("fact", i), name) for i, name in enumerate("abc"))
    assert fuse([a, b], [b, c]) == [b, a, c]
    assert fuse([a], [c]) == [a, c]
    note_by_keyword = Hit(("note", 7), "snippet")
    assert fuse([note_by_keyword], [Hit(("note", 7), "chunk")]) == [note_by_keyword]


def test_hybrid_merges_and_semantic_only_drops_keywords(
    conn: sqlite3.Connection, embedder: FakeEmbedder
) -> None:
    add_fact(conn, "spot", "cave", "behind the waterfall")
    add_fact(conn, "base", "location", "left of spawn")
    add_filler(conn)
    index(conn, embedder)
    query = "cave near my house"
    assert recalled(conn, query, None) == ["spot / cave: behind the waterfall (player said)"]
    hybrid = recalled(conn, query, ask(embedder, query))
    assert sorted(hybrid) == [
        "base / location: left of spawn (player said)",
        "spot / cave: behind the waterfall (player said)",
    ]
    strict = VectorQuery(embedder.embed_query(query), semantic_only=True, min_similarity=0.99)
    assert recalled(conn, query, strict) == []


def test_a_broken_index_falls_back_to_keywords(
    conn: sqlite3.Connection, embedder: FakeEmbedder, caplog: pytest.LogCaptureFixture
) -> None:
    add_fact(conn, "spot", "cave", "behind the waterfall")
    add_filler(conn)
    vector = ask(embedder, "the cave", semantic_only=True)
    conn.execute("DROP TABLE fact_vectors")
    with caplog.at_level(logging.ERROR):
        found = recalled(conn, "the cave", vector)
    assert found == ["spot / cave: behind the waterfall (player said)"]
    assert "Vector recall failed" in caplog.text
