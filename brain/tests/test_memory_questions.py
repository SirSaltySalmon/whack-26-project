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


# --- Question queue ---
def test_next_question_is_oldest_unasked(store: FactStore) -> None:
    first = store.remember(GAME, "a", "x", "1", "observed", 0.2).question
    second = store.remember(GAME, "b", "x", "1", "observed", 0.2).question
    assert first is not None and second is not None
    next_up = store.next_question(GAME)
    assert next_up is not None and next_up.id == first.id
    store.mark_asked(first.id)
    next_up = store.next_question(GAME)
    assert next_up is not None and next_up.id == second.id
    store.drop_question(second.id)
    assert store.next_question(GAME) is None


def test_next_question_is_scoped_to_the_game(store: FactStore) -> None:
    store.remember("A", "a", "x", "1", "observed", 0.2)
    assert store.next_question("B") is None
    assert store.next_question("A") is not None
    store.remember(None, "b", "x", "1", "observed", 0.2)
    assert store.next_question("B") is not None


def test_next_question_drops_questions_about_closed_facts(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    result = remember(store, "mage", "observed", 0.3)
    assert result.fact is not None
    store.close(result.fact.id)
    assert store.next_question(GAME) is None
    assert conn.execute("SELECT status FROM questions").fetchone()[0] == "dropped"


def test_confirming_an_uncertain_fact_drops_its_question(store: FactStore) -> None:
    remember(store, "mage", "observed", 0.3)
    assert remember(store, "mage", "player", 0.9).outcome == "confirmed"
    assert store.next_question(GAME) is None


def test_mark_asked_keeps_the_first_time(store: FactStore, conn: sqlite3.Connection) -> None:
    question = remember(store, "mage", "observed", 0.3).question
    assert question is not None
    store.mark_asked(question.id)
    first = conn.execute("SELECT asked_at FROM questions").fetchone()[0]
    assert first is not None
    store.mark_asked(question.id)
    assert conn.execute("SELECT asked_at FROM questions").fetchone()[0] == first


# --- Answers ---
def test_answering_a_conflict_settles_it_with_a_player_fact(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    remember(store, "mage", "player")
    conflict = remember(store, "ranger", "observed")
    assert conflict.question is not None
    result = store.answer_question(conflict.question.id, "ranger")
    assert result is not None and result.fact is not None
    assert result.outcome == "replaced"
    assert result.fact.source == "player"
    assert result.fact.confidence == 1.0
    assert result.fact.tentative is False
    assert result.fact.subject == "player" and result.fact.attribute == "class"
    assert {fact.value for fact in result.closed} == {"mage", "ranger"}
    assert all(fact.valid_to is not None for fact in result.closed)
    assert current_values(store) == ["ranger"]
    row = conn.execute("SELECT status, answer, answered_at FROM questions").fetchone()
    assert row["status"] == "answered" and row["answer"] == "ranger"
    assert row["answered_at"] is not None


def test_answer_outside_the_options_is_accepted(store: FactStore) -> None:
    remember(store, "mage", "player")
    conflict = remember(store, "ranger", "observed")
    assert conflict.question is not None
    result = store.answer_question(conflict.question.id, "  actually   summoner ")
    assert result is not None and result.fact is not None
    assert result.fact.value == "actually summoner"
    assert current_values(store) == ["actually summoner"]


def test_conflict_between_literal_yes_and_no_is_still_a_conflict(store: FactStore) -> None:
    remember(store, "Yes", "player")
    conflict = remember(store, "No", "observed")
    assert conflict.question is not None
    assert conflict.question.options == ["Yes", "No"]
    result = store.answer_question(conflict.question.id, "no")
    assert result is not None and result.fact is not None
    assert result.outcome == "replaced"
    assert current_values(store) == ["no"]


def test_answering_yes_confirms_the_fact(store: FactStore) -> None:
    uncertain = remember(store, "mage", "observed", 0.3)
    assert uncertain.question is not None
    result = store.answer_question(uncertain.question.id, "YES")
    assert result is not None and result.fact is not None
    assert result.outcome == "confirmed"
    assert result.fact.source == "observed"
    assert result.fact.tentative is False
    assert result.fact.confidence == 1.0


def test_answering_no_closes_the_fact(store: FactStore) -> None:
    uncertain = remember(store, "mage", "observed", 0.3)
    assert uncertain.question is not None and uncertain.fact is not None
    result = store.answer_question(uncertain.question.id, "no")
    assert result is not None
    assert result.outcome == "replaced"
    assert result.fact is None
    assert [fact.id for fact in result.closed] == [uncertain.fact.id]
    assert current_values(store) == []


def test_free_text_answer_to_a_yes_no_question_becomes_the_value(store: FactStore) -> None:
    uncertain = remember(store, "mage", "observed", 0.3)
    assert uncertain.question is not None
    result = store.answer_question(uncertain.question.id, "ranger")
    assert result is not None and result.fact is not None
    assert result.outcome == "replaced"
    assert current_values(store) == ["ranger"]


def test_answer_also_closes_newer_unlinked_facts(store: FactStore) -> None:
    uncertain = remember(store, "mage", "observed", 0.3)
    assert uncertain.question is not None and uncertain.fact is not None
    store.close(uncertain.fact.id)
    remember(store, "melee", "observed", 0.9)
    store.answer_question(uncertain.question.id, "ranger")
    assert current_values(store) == ["ranger"]


def test_answer_works_when_linked_facts_were_closed_elsewhere(store: FactStore) -> None:
    first = remember(store, "mage", "player")
    conflict = remember(store, "ranger", "observed")
    assert first.fact is not None and conflict.fact is not None and conflict.question is not None
    store.close(first.fact.id)
    store.close(conflict.fact.id)
    result = store.answer_question(conflict.question.id, "melee")
    assert result is not None and result.fact is not None
    assert result.fact.value == "melee"
    assert current_values(store) == ["melee"]


@pytest.mark.parametrize(("answer", "outcome"), [("yes", "ignored"), ("no", "replaced")])
def test_yes_no_answer_about_a_closed_fact_doesnt_crash(
    store: FactStore, answer: str, outcome: str
) -> None:
    uncertain = remember(store, "mage", "observed", 0.3)
    assert uncertain.question is not None and uncertain.fact is not None
    store.close(uncertain.fact.id)
    result = store.answer_question(uncertain.question.id, answer)
    assert result is not None
    assert result.outcome == outcome
    assert result.fact is None


def test_question_without_linked_facts_can_be_answered(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    with conn:
        question_id = conn.execute(
            "INSERT INTO questions (game, text, created_at) VALUES (?, 'Ready?', 1.0)", (GAME,)
        ).lastrowid
    assert question_id is not None
    result = store.answer_question(question_id, "sure")
    assert result is not None and result.outcome == "ignored"
    assert conn.execute("SELECT status FROM questions").fetchone()[0] == "answered"


def test_unknown_question_is_refused_with_a_warning(
    store: FactStore, caplog: pytest.LogCaptureFixture
) -> None:
    assert store.answer_question(999, "yes") is None
    assert "999" in caplog.text


def test_answered_question_is_refused(store: FactStore, caplog: pytest.LogCaptureFixture) -> None:
    question = remember(store, "mage", "observed", 0.3).question
    assert question is not None
    store.answer_question(question.id, "yes")
    assert store.answer_question(question.id, "no") is None
    assert str(question.id) in caplog.text


def test_a_dropped_question_can_still_be_answered(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    # The player may come back to a question they let pass.
    question = remember(store, "mage", "observed", 0.3).question
    assert question is not None
    assert store.drop_question(question.id) is True
    assert store.drop_question(question.id) is False
    result = store.answer_question(question.id, "ranger")
    assert result is not None and result.outcome == "replaced"
    assert current_values(store) == ["ranger"]
    assert conn.execute("SELECT status FROM questions").fetchone()[0] == "answered"


def test_empty_answer_leaves_the_question_open(store: FactStore) -> None:
    question = remember(store, "mage", "observed", 0.3).question
    assert question is not None
    assert store.answer_question(question.id, "   ") is None
    next_up = store.next_question(GAME)
    assert next_up is not None and next_up.id == question.id


def test_questions_settle_across_a_real_file(tmp_path) -> None:
    # Commits have to reach disk, not just this connection, or a restart would lose memory.
    path = tmp_path / "brain.sqlite3"
    conn = connect(path)
    store = FactStore(conn)
    store.remember(GAME, "player", "class", "mage", "player", 0.9)
    conflict = store.remember(GAME, "player", "class", "ranger", "observed", 0.9)
    assert conflict.question is not None
    store.answer_question(conflict.question.id, "mage")
    conn.close()

    reopened = connect(path)
    assert [f.value for f in FactStore(reopened).current(GAME)] == ["mage"]
    reopened.close()
