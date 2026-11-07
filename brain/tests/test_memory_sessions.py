from itertools import count

import pytest

from brain.memory.db import connect
from brain.memory.models import Turn
from brain.memory.sessions import SessionStore


@pytest.fixture
def store() -> SessionStore:
    ticks = count(100)
    return SessionStore(connect(":memory:"), clock=lambda: float(next(ticks)))


def test_start_and_end_record_the_session(store: SessionStore) -> None:
    session = store.start("Game A")
    assert session.game == "Game A"
    assert session.ended_at is None
    store.end(session.id)
    later = store.start("Game A")
    previous = store.previous("Game A", later.id)
    assert previous is not None
    assert previous.id == session.id
    assert previous.ended_at is not None


def test_ending_twice_keeps_the_first_end_time(store: SessionStore) -> None:
    session = store.start("Game A")
    store.end(session.id)
    later = store.start("Game A")
    first_end = store.previous("Game A", later.id)
    store.end(session.id)
    assert store.previous("Game A", later.id) == first_end


def test_previous_is_most_recent_earlier_session_of_that_game(store: SessionStore) -> None:
    first = store.start("Game A")
    second = store.start("Game A")
    store.start("Game B")
    current = store.start("Game A")

    found = store.previous("Game A", current.id)
    assert found is not None and found.id == second.id
    found = store.previous("Game A", second.id)
    assert found is not None and found.id == first.id
    assert store.previous("Game A", first.id) is None


def test_recent_turns_are_oldest_first_and_limited(store: SessionStore) -> None:
    session = store.start("Game A")
    for index in range(4):
        store.log_turn(session.id, "player" if index % 2 == 0 else "partner", f"line {index}")
    store.log_event(session.id, "boss.seen")

    turns = store.recent_turns(session.id, limit=3)
    assert [(turn.speaker, turn.text) for turn in turns] == [
        ("partner", "line 1"),
        ("player", "line 2"),
        ("partner", "line 3"),
    ]
    assert all(isinstance(turn, Turn) for turn in turns)


def test_turns_in_the_same_clock_tick_keep_their_order() -> None:
    store = SessionStore(connect(":memory:"), clock=lambda: 5.0)
    session = store.start("Game A")
    store.log_turn(session.id, "player", "first")
    store.log_turn(session.id, "partner", "second")
    assert [turn.text for turn in store.recent_turns(session.id)] == ["first", "second"]


def test_turns_are_scoped_to_the_session(store: SessionStore) -> None:
    one = store.start("Game A")
    two = store.start("Game A")
    store.log_turn(one.id, "player", "from one")
    assert store.recent_turns(two.id) == []


def test_events_since_excludes_the_boundary_and_includes_turns(store: SessionStore) -> None:
    session = store.start("Game A")
    boundary = store.log_event(session.id, "first")
    second = store.log_event(session.id, "second", {"count": 2})
    store.log_turn(session.id, "player", "hello")

    events = store.events_since(session.id, boundary.ts)
    assert [event.name for event in events] == ["second", "turn.player"]
    assert events[0].data == {"count": 2}
    assert events[0] == second
    assert events[1].data == {"text": "hello"}


def test_events_since_keeps_the_newest_when_limited(store: SessionStore) -> None:
    session = store.start("Game A")
    for index in range(5):
        store.log_event(session.id, f"event {index}")
    events = store.events_since(session.id, 0.0, limit=2)
    assert [event.name for event in events] == ["event 3", "event 4"]


def test_event_without_data_round_trips_as_none(store: SessionStore) -> None:
    session = store.start("Game A")
    store.log_event(session.id, "bare")
    assert store.events_since(session.id, 0.0)[0].data is None


def test_latest_note_can_filter_by_kind(store: SessionStore) -> None:
    session = store.start("Game A")
    assert store.latest_note(session.id) is None
    store.add_note(session.id, "rolling", "early", 1.0, 2.0)
    recap = store.add_note(session.id, "recap", "the recap", 1.0, 3.0)
    rolling = store.add_note(session.id, "rolling", "late", 3.0, 4.0)

    assert store.latest_note(session.id) == rolling
    assert store.latest_note(session.id, "recap") == recap
    assert store.latest_note(session.id, "rolling") == rolling


def test_notes_for_session_are_oldest_first_and_scoped(store: SessionStore) -> None:
    one = store.start("Game A")
    two = store.start("Game A")
    store.add_note(one.id, "rolling", "first", 1.0, 2.0)
    store.add_note(two.id, "rolling", "elsewhere", 1.0, 2.0)
    store.add_note(one.id, "recap", "second", 2.0, 3.0)
    assert [note.body for note in store.notes_for_session(one.id)] == ["first", "second"]


def test_search_notes_is_scoped_to_the_game(store: SessionStore) -> None:
    game_a = store.start("Game A")
    game_b = store.start("Game B")
    wanted = store.add_note(game_a.id, "rolling", "Built an arena for the boss", 1.0, 2.0)
    store.add_note(game_b.id, "rolling", "Another boss in another game", 1.0, 2.0)

    assert store.search_notes("Game A", "boss") == [wanted]


@pytest.mark.parametrize(
    "query",
    ["what's the boss?", "boss-fight", 'the "boss" (again)', "boss OR NEAR(x)", "boss*"],
)
def test_search_notes_accepts_punctuation(store: SessionStore, query: str) -> None:
    session = store.start("Game A")
    wanted = store.add_note(session.id, "rolling", "Fought the boss twice", 1.0, 2.0)
    assert store.search_notes("Game A", query) == [wanted]


@pytest.mark.parametrize("query", ["", "?!", "where is it?"])
def test_search_notes_with_nothing_to_search_for_is_empty(store: SessionStore, query: str) -> None:
    session = store.start("Game A")
    store.add_note(session.id, "rolling", "where is it", 1.0, 2.0)
    assert store.search_notes("Game A", query) == []


def test_search_notes_matches_word_variants(store: SessionStore) -> None:
    session = store.start("Game A")
    wanted = store.add_note(session.id, "rolling", "Fought two bosses", 1.0, 2.0)
    assert store.search_notes("Game A", "boss") == [wanted]


def test_search_notes_respects_the_limit(store: SessionStore) -> None:
    session = store.start("Game A")
    for index in range(3):
        store.add_note(session.id, "rolling", f"boss note {index}", 1.0, 2.0)
    assert len(store.search_notes("Game A", "boss", limit=2)) == 2
