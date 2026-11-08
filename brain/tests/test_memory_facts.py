import sqlite3
from collections.abc import Iterator
from itertools import count

import pytest

from brain.memory.db import connect
from brain.memory.facts import FactStore
from brain.memory.models import Source

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


# --- Rule 1: same value confirms ---
def test_same_value_confirms_without_a_new_row(store: FactStore, conn: sqlite3.Connection) -> None:
    first = remember(store, "Summoner", "player", 0.6)
    result = remember(store, "  summoner ", "observed", 0.7)
    assert result.outcome == "confirmed"
    assert result.fact is not None and first.fact is not None
    assert result.fact.id == first.fact.id
    assert result.fact.confidence == pytest.approx(0.8)
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1


def test_confirmation_caps_confidence_at_one(store: FactStore) -> None:
    remember(store, "mage", "player", 0.95)
    result = remember(store, "mage", "player", 0.95)
    assert result.fact is not None
    assert result.fact.confidence == 1.0


@pytest.mark.parametrize("source", ["player", "observed"])
def test_trusted_source_clears_tentative_on_a_wiki_fact(store: FactStore, source: str) -> None:
    remember(store, "mage", "wiki")
    result = remember(store, "MAGE", source)
    assert result.fact is not None
    assert result.fact.tentative is False
    assert result.fact.source == "wiki"


def test_wiki_repeating_wiki_stays_tentative(store: FactStore) -> None:
    remember(store, "mage", "wiki")
    result = remember(store, "mage", "wiki")
    assert result.outcome == "confirmed"
    assert result.fact is not None
    assert result.fact.tentative is True


# --- Rule 2: first fact ---
@pytest.mark.parametrize(("source", "tentative"), [("player", False), ("observed", False)])
def test_first_trusted_fact_is_stored(store: FactStore, source: str, tentative: bool) -> None:
    result = remember(store, "mage", source)
    assert result.outcome == "stored"
    assert result.fact is not None
    assert result.fact.tentative is tentative
    assert result.question is None


def test_first_wiki_fact_is_tentative_even_at_low_confidence(store: FactStore) -> None:
    result = remember(store, "mage", "wiki", 0.1)
    assert result.outcome == "stored"
    assert result.fact is not None
    assert result.fact.tentative is True
    assert result.question is None


def test_low_confidence_observation_asks(store: FactStore) -> None:
    result = remember(store, "mage", "observed", 0.3)
    assert result.outcome == "uncertain"
    assert result.fact is not None
    assert result.fact.tentative is True
    assert result.question is not None
    assert result.question.options == ["Yes", "No"]
    assert result.question.fact_ids == [result.fact.id]
    assert result.question.text == "Is your class mage?"


def test_confidence_at_the_threshold_doesnt_ask(store: FactStore) -> None:
    assert remember(store, "mage", "observed", 0.5).outcome == "stored"


# --- Rule 3: different values ---
@pytest.mark.parametrize("trusted", ["player", "observed"])
def test_wiki_never_displaces_a_trusted_fact(
    store: FactStore, conn: sqlite3.Connection, trusted: str
) -> None:
    existing = remember(store, "mage", trusted)
    result = remember(store, "ranger", "wiki")
    assert result.outcome == "ignored"
    assert result.fact == existing.fact
    assert current_values(store) == ["mage"]
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1


def test_wiki_replaces_wiki_and_stays_tentative(store: FactStore) -> None:
    old = remember(store, "mage", "wiki")
    result = remember(store, "ranger", "wiki")
    assert result.outcome == "replaced"
    assert result.fact is not None and old.fact is not None
    assert result.fact.tentative is True
    assert [fact.id for fact in result.closed] == [old.fact.id]
    assert current_values(store) == ["ranger"]


@pytest.mark.parametrize("trusted", ["player", "observed"])
def test_trusted_source_replaces_wiki(store: FactStore, trusted: str) -> None:
    remember(store, "mage", "wiki")
    result = remember(store, "ranger", trusted)
    assert result.outcome == "replaced"
    assert result.fact is not None
    assert result.fact.tentative is False
    assert current_values(store) == ["ranger"]


@pytest.mark.parametrize("source", ["player", "observed"])
def test_same_source_latest_wins(store: FactStore, source: str) -> None:
    remember(store, "mage", source)
    result = remember(store, "ranger", source)
    assert result.outcome == "replaced"
    assert current_values(store) == ["ranger"]


def test_the_screen_disagreeing_with_the_player_asks(store: FactStore) -> None:
    existing = remember(store, "mage", "player")
    result = remember(store, "ranger", "observed")
    assert result.outcome == "conflict"
    assert result.fact is not None and existing.fact is not None
    assert result.fact.tentative is True
    assert result.question is not None
    assert result.question.options == ["mage", "ranger"]
    assert set(result.question.fact_ids) == {existing.fact.id, result.fact.id}
    assert result.question.text == "Is your class mage, or ranger?"
    assert set(current_values(store)) == {"mage", "ranger"}


def test_the_player_overrules_what_was_observed_without_asking(store: FactStore) -> None:
    # Asking the player to choose between their own words and our guess would be wrong.
    existing = remember(store, "mage", "observed")
    result = remember(store, "ranger", "player")
    assert result.outcome == "replaced"
    assert result.question is None
    assert result.fact is not None and result.fact.tentative is False
    assert existing.fact is not None
    assert [fact.id for fact in result.closed] == [existing.fact.id]
    assert current_values(store) == ["ranger"]
    assert store.next_question(GAME) is None


def test_further_disagreement_extends_the_open_question(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    remember(store, "mage", "player")
    first = remember(store, "ranger", "observed")
    second = remember(store, "melee", "observed")
    assert second.outcome == "conflict"
    assert first.question is not None and second.question is not None
    assert second.question.id == first.question.id
    assert second.question.options == ["mage", "ranger", "melee"]
    assert len(second.question.fact_ids) == 3
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1


def test_repeating_a_disputed_value_doesnt_add_a_question(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    remember(store, "mage", "player")
    remember(store, "ranger", "observed")
    assert remember(store, "ranger", "observed").outcome == "confirmed"
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1


def test_uncertain_question_becomes_a_conflict_when_disputed(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    uncertain = remember(store, "mage", "player", 0.3)
    result = remember(store, "ranger", "observed")
    assert result.outcome == "conflict"
    assert uncertain.question is not None and result.question is not None
    assert result.question.id == uncertain.question.id
    assert result.question.options == ["mage", "ranger"]
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1


def test_closed_values_stay_in_the_table(store: FactStore, conn: sqlite3.Connection) -> None:
    remember(store, "mage", "player")
    remember(store, "ranger", "player")
    rows = conn.execute("SELECT value, valid_to FROM facts ORDER BY id").fetchall()
    assert rows[0]["value"] == "mage" and rows[0]["valid_to"] is not None
    assert rows[1]["value"] == "ranger" and rows[1]["valid_to"] is None


# --- Input handling ---
def test_whitespace_is_collapsed_on_write(store: FactStore) -> None:
    result = store.remember(GAME, " the \n base ", " location\t", "east   of spawn", "player", 0.9)
    assert result.fact is not None
    assert result.fact.subject == "the base"
    assert result.fact.attribute == "location"
    assert result.fact.value == "east of spawn"


def test_subject_and_attribute_match_ignoring_case(store: FactStore) -> None:
    remember(store, "mage", "player")
    result = store.remember(GAME, "PLAYER", "Class", "mage", "player", 0.8)
    assert result.outcome == "confirmed"


@pytest.mark.parametrize(
    ("subject", "attribute", "value"),
    [("", "a", "v"), ("s", "   ", "v"), ("s", "a", "\n\t")],
)
def test_empty_text_is_rejected(store: FactStore, subject: str, attribute: str, value: str) -> None:
    with pytest.raises(ValueError):
        store.remember(GAME, subject, attribute, value, "player", 0.5)


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan")])
def test_confidence_out_of_range_is_rejected(store: FactStore, confidence: float) -> None:
    with pytest.raises(ValueError):
        store.remember(GAME, "s", "a", "v", "player", confidence)


def test_unknown_source_is_rejected(store: FactStore) -> None:
    with pytest.raises(ValueError):
        store.remember(GAME, "s", "a", "v", "rumor", 0.5)  # type: ignore[arg-type]


def test_session_id_is_stored(store: FactStore, conn: sqlite3.Connection) -> None:
    with conn:
        session = conn.execute(
            "INSERT INTO sessions (game, started_at) VALUES (?, 1.0)", (GAME,)
        ).lastrowid
    store.remember(GAME, "s", "a", "v", "player", 0.9, session_id=session)
    assert conn.execute("SELECT session_id FROM facts").fetchone()[0] == session


@pytest.mark.parametrize("existing_source", ["player", "observed", "wiki"])
def test_low_confidence_reading_asks_instead_of_replacing(existing_source: Source) -> None:
    store = FactStore(connect(":memory:"))
    first = store.remember("g", "player", "base", "east", existing_source, 0.9)
    assert first.fact is not None

    result = store.remember("g", "player", "base", "west", "observed", 0.3)

    assert result.outcome == "conflict"
    assert result.question is not None
    assert set(result.question.options) == {"east", "west"}
    # The surer fact stays current until the player settles it.
    assert first.fact.id in [fact.id for fact in store.current("g", "player", "base")]
