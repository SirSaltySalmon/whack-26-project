"""The player's word over guesses, guesses that never ask, and values the player has rejected."""

import sqlite3
from collections.abc import Iterator
from itertools import count

import pytest

from brain.memory.db import connect
from brain.memory.facts import FactStore
from brain.memory.models import RememberResult, Source
from brain.memory.unknowns import UnknownStore

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


def remember(
    store: FactStore, value: str, source: Source, confidence: float = 0.8, tentative: bool = False
) -> RememberResult:
    return store.remember(
        GAME, "playthrough", "progress", value, source, confidence, tentative=tentative
    )


def values(store: FactStore) -> list[str]:
    return [fact.value for fact in store.current(GAME, "playthrough", "progress")]


def statuses(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT status FROM questions ORDER BY id")]


# --- The player overrules guesses ---
def test_player_correction_settles_an_open_dispute(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    remember(store, "early game", "player")
    assert remember(store, "hardmode", "observed").outcome == "conflict"
    result = remember(store, "post-Plantera", "player")
    assert result.outcome == "replaced"
    assert values(store) == ["post-Plantera"]
    # The dispute is about facts that are all closed now, so it must not be asked or listed.
    assert statuses(conn) == ["dropped"]
    assert store.next_question(GAME) is None


def test_a_shaky_player_claim_still_asks_rather_than_replacing(store: FactStore) -> None:
    remember(store, "early game", "observed")
    result = remember(store, "hardmode", "player", 0.3)
    assert result.outcome == "conflict"
    assert set(values(store)) == {"early game", "hardmode"}


# --- Tentative inferences ---
def test_an_inference_is_stored_unconfirmed_without_a_question(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    result = remember(store, "early game", "observed", 0.3, tentative=True)
    assert result.outcome == "stored"
    assert result.fact is not None and result.fact.tentative is True
    assert result.question is None
    assert statuses(conn) == []


def test_an_inference_never_disputes_the_player(store: FactStore, conn: sqlite3.Connection) -> None:
    remember(store, "hardmode", "player")
    result = remember(store, "early game", "observed", 0.9, tentative=True)
    assert result.outcome == "ignored"
    assert values(store) == ["hardmode"]
    assert statuses(conn) == []


def test_a_new_inference_replaces_an_old_one_and_stays_unconfirmed(store: FactStore) -> None:
    remember(store, "early game", "observed", 0.6, tentative=True)
    result = remember(store, "hardmode", "observed", 0.6, tentative=True)
    assert result.outcome == "replaced"
    assert result.fact is not None and result.fact.tentative is True
    assert values(store) == ["hardmode"]


def test_a_shaky_inference_cannot_close_a_sure_reading(store: FactStore) -> None:
    remember(store, "hardmode", "observed", 0.9)
    assert remember(store, "early game", "observed", 0.3, tentative=True).outcome == "ignored"
    assert values(store) == ["hardmode"]


def test_repeating_an_inference_does_not_confirm_it(store: FactStore) -> None:
    remember(store, "early game", "observed", 0.6, tentative=True)
    result = remember(store, "early game", "observed", 0.6, tentative=True)
    assert result.outcome == "confirmed"
    assert result.fact is not None and result.fact.tentative is True


def test_a_tentative_wiki_claim_still_never_displaces_a_reading(store: FactStore) -> None:
    remember(store, "hardmode", "observed")
    assert remember(store, "early game", "wiki", 0.9, tentative=True).outcome == "ignored"


# --- Forgetting and rejected values ---
def test_forget_closes_every_current_value_for_the_key_only(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    remember(store, "early game", "player")
    remember(store, "hardmode", "observed")  # A dispute, so two values are current.
    store.remember(GAME, "player", "class", "mage", "player", 0.9)
    store.remember("Other Game", "playthrough", "progress", "late", "player", 0.9)

    closed = store.forget(GAME, " Playthrough ", "PROGRESS")

    assert {fact.value for fact in closed} == {"early game", "hardmode"}
    assert values(store) == []
    assert [fact.value for fact in store.current(GAME, "player", "class")] == ["mage"]
    assert [f.value for f in store.current("Other Game", "playthrough", "progress")] == ["late"]
    assert statuses(conn) == ["dropped"]
    assert store.forget(GAME, "playthrough", "progress") == []


def test_a_forgotten_value_cannot_come_back_as_a_guess(store: FactStore) -> None:
    remember(store, "early game", "observed")
    store.forget(GAME, "playthrough", "progress")
    assert remember(store, "Early  Game", "observed", 0.9).outcome == "ignored"
    assert remember(store, "early game", "wiki").outcome == "ignored"
    assert remember(store, "early game", "observed", 0.9, tentative=True).outcome == "ignored"
    assert values(store) == []
    # Other values are still learnable.
    assert remember(store, "hardmode", "observed").outcome == "stored"


def test_only_the_player_can_bring_a_rejected_value_back(store: FactStore) -> None:
    remember(store, "early game", "observed")
    store.forget(GAME, "playthrough", "progress")
    assert remember(store, "early game", "player").outcome == "stored"
    store.forget(GAME, "playthrough", "progress")
    remember(store, "early game", "player")
    # Lifted by the player saying it again, so the screen agreeing is fine.
    assert remember(store, "early game", "observed").outcome == "confirmed"


def test_a_guess_the_player_overruled_is_not_raised_again(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    remember(store, "early game", "observed")
    remember(store, "hardmode", "player")
    # Without the rejection this would be a dispute, and the player would be asked again.
    assert remember(store, "early game", "observed").outcome == "ignored"
    assert statuses(conn) == []


def test_the_players_own_old_claim_is_not_rejected(store: FactStore) -> None:
    remember(store, "early game", "player")
    remember(store, "hardmode", "player")
    assert remember(store, "early game", "observed").outcome == "conflict"


def test_answering_no_rejects_the_guess(store: FactStore) -> None:
    question = remember(store, "early game", "observed", 0.3).question
    assert question is not None
    store.answer_question(question.id, "No")
    assert remember(store, "early game", "observed", 0.9).outcome == "ignored"


def test_rejections_are_kept_per_game(store: FactStore) -> None:
    remember(store, "early game", "observed")
    store.forget(GAME, "playthrough", "progress")
    result = store.remember("Other Game", "playthrough", "progress", "early game", "observed", 0.9)
    assert result.outcome == "stored"


# --- Sure facts settle open questions about their key ---
def test_the_player_stating_a_fact_answers_the_open_question_about_it(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    UnknownStore(conn).wonder(GAME, "playthrough", "progress", "Where are you up to?")
    remember(store, "hardmode", "player")
    row = conn.execute("SELECT status, answer FROM questions").fetchone()
    assert (row["status"], row["answer"]) == ("answered", "hardmode")
    assert store.next_question(GAME) is None


def test_a_sure_reading_drops_the_open_question_but_a_guess_does_not(
    store: FactStore, conn: sqlite3.Connection
) -> None:
    UnknownStore(conn).wonder(GAME, "playthrough", "progress", "Where are you up to?")
    remember(store, "early game", "observed", 0.6, tentative=True)
    assert statuses(conn) == ["open"]
    remember(store, "hardmode", "observed", 0.9)
    assert statuses(conn) == ["dropped"]
