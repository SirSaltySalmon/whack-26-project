"""The conversation every reply is sent with. Shaped on a real session where the 1,200-character
cap left only the player's newest line, so the partner asked the same question twice."""

import sqlite3
from collections.abc import Iterator
from itertools import count

import pytest

from brain.llm.base import ChatTurn
from brain.memory.context import ContextInputs, ContextLimits
from brain.memory.conversation import ConversationItem, history_turns, without_current
from brain.memory.db import connect
from brain.memory.gather import gather_context
from brain.memory.layers import build_context
from brain.memory.models import Fact, Speaker
from brain.memory.sessions import SessionStore

GAME = "Minecraft"
FIRST_ASK = "Do you prefer building, exploring, redstone stuff, or fighting?"
SECOND_ASK = "A relaxed wander, then. Are you more into building, exploring, redstone, or fighting?"
COMPLAINT = "You just asked me that."
# About the sizes in the real session: a whole brief, a recap, sight and mood, and 8 facts.
BRIEF = "A sandbox survival and building game set in a procedurally generated block world. " * 4
NOTE = "## Session recap The player is on a relaxed, nostalgic revisit and likes building. " * 4
LIVE = {"mood": "calm", "danger": "none", "health": "120/200 (60%)", "seen": "forest at dusk " * 8}
SCRIPT: list[tuple[Speaker, str]] = [
    ("partner", "Hey! What should I call you?"),
    ("player", "Call me Sam."),
    ("partner", FIRST_ASK),
    ("player", "I like building a lot, but I'm not doing that"),
    ("player", "today."),
    ("partner", SECOND_ASK),
    ("player", COMPLAINT),
]


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    yield connection
    connection.close()


def add_fact(
    conn: sqlite3.Connection,
    value: str,
    attribute: str,
    source: str = "player",
    subject: str = "player",
) -> None:
    # Each fact is newer than the one before, so the expected order is the insertion order.
    newest = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    conn.execute(
        "INSERT INTO facts (game, subject, attribute, value, source, confidence, tentative,"
        " valid_from) VALUES (?, ?, ?, ?, ?, 0.9, 0, ?)",
        (GAME, subject, attribute, value, source, float(newest)),
    )


def sessions(conn: sqlite3.Connection) -> SessionStore:
    ticks = count(1)
    return SessionStore(conn, lambda: float(next(ticks)))


def play_the_repeated_question(conn: sqlite3.Connection) -> int:
    store = sessions(conn)
    session = store.start(GAME).id
    conn.execute("INSERT INTO profile (game, brief, updated_at) VALUES (?, ?, 1)", (GAME, BRIEF))
    store.add_note(session, "recap", NOTE, 0.0, 1.0)
    for i in range(8):
        add_fact(conn, f"likes building a lot, number {i}", f"playstyle {i}")
    for speaker, text in SCRIPT:
        store.log_turn(session, speaker, text)
    return session


def test_the_partners_last_line_reaches_the_next_player_turn(conn: sqlite3.Connection) -> None:
    session = play_the_repeated_question(conn)
    inputs = gather_context(conn, GAME, session, LIVE, query=COMPLAINT, current=COMPLAINT)
    context = build_context(inputs)
    assert context.history == (
        ChatTurn("assistant", "Hey! What should I call you?"),
        ChatTurn("user", "Call me Sam."),
        ChatTurn("assistant", FIRST_ASK),
        ChatTurn("user", "I like building a lot, but I'm not doing that\ntoday."),
        ChatTurn("assistant", SECOND_ASK),
    )
    # The words being answered are the model's latest message, so they aren't listed again.
    assert all(COMPLAINT not in turn.text for turn in context.history)
    assert all(f"playstyle {i}" in context.memory for i in range(8))


def test_events_and_tips_keep_the_players_newest_line(conn: sqlite3.Connection) -> None:
    session = play_the_repeated_question(conn)
    for query in ("danger_started", "progress goal next"):
        context = build_context(gather_context(conn, GAME, session, LIVE, query=query))
        assert context.history[-1] == ChatTurn("user", COMPLAINT)


ITEMS = [
    ConversationItem("partner", FIRST_ASK, 1.0),
    ConversationItem("player", "I like building a lot", 2.0),
    ConversationItem("player", "today.", 3.0),
]


@pytest.mark.parametrize(
    ("current", "kept"),
    [
        ("today.", 2),
        # A carried turn: the cut-off words, then the newest ones, so both are the message.
        ("I like building a lot today.", 1),
        ("  TODAY. ", 2),
        # A line of theirs that isn't part of the message stays.
        ("what about today. ok", 2),
        (None, 3),
        ("", 3),
    ],
)
def test_only_the_words_being_answered_are_left_out(current: str | None, kept: int) -> None:
    assert without_current(ITEMS, current) == ITEMS[:kept]


def test_the_partners_newest_line_is_never_left_out() -> None:
    items = [*ITEMS, ConversationItem("partner", "today.", 4.0)]
    assert without_current(items, "today.") == items


def test_a_short_line_is_only_left_out_when_said_whole() -> None:
    items = [ConversationItem("player", "no", 1.0), ConversationItem("player", "notes please", 2.0)]
    assert without_current(items, "notes please") == items[:1]


def test_notes_logged_since_are_kept_and_skipped_over() -> None:
    note = ConversationItem("note", "danger started", 4.0)
    assert without_current([*ITEMS, note], "today.") == [*ITEMS[:2], note]


def test_notes_join_the_players_message_with_their_time_into_the_session() -> None:
    items = [
        ConversationItem("partner", "Watch out.", 100.0),
        ConversationItem("player", "what", 130.0),
        ConversationItem("note", "danger started: Blue Slime", 140.0),
    ]
    turns, left_out = history_turns(items, 1_000, 400, started=100.0)
    assert turns == (
        ChatTurn("assistant", "Watch out."),
        ChatTurn("user", "what\n(note, 0:40 into the session) danger started: Blue Slime"),
    )
    assert left_out == 0
    # Room for the note alone: the two older lines are left to the session note.
    assert history_turns(items, 60, 400, started=100.0)[1] == 2


def test_every_player_fact_and_a_few_guesses_are_kept(conn: sqlite3.Connection) -> None:
    session = sessions(conn).start(GAME).id
    for i in range(20):
        add_fact(conn, f"said {i}", f"a{i}")
    for i in range(8):
        add_fact(conn, f"seen {i}", f"o{i}", source="observed")
    inputs = gather_context(conn, GAME, session, {})
    values = [fact.value for fact in inputs.facts]
    assert values == [f"said {i}" for i in reversed(range(20))] + [
        f"seen {i}" for i in reversed(range(3, 8))
    ]
    memory = build_context(inputs).memory
    assert all(f"said {i} (player said)" in memory for i in range(20))


def test_facts_and_the_conversation_never_compete_for_room() -> None:
    turns = [
        ConversationItem("player" if i % 2 else "partner", f"line{i} " + "x" * 50, float(i))
        for i in range(8)
    ]
    facts = [
        Fact(i, GAME, "player", f"a{i}", "y" * 90, "player", 0.9, False, 0.0) for i in range(10)
    ]
    inputs = ContextInputs(game=GAME, live_state={"health": "low"}, facts=facts, turns=turns)
    tight = build_context(inputs, ContextLimits(memory_chars=600))
    # MEMORY lost facts to its own budget, and every turn is still there.
    assert 0 < tight.memory.count("(player said)") < len(facts)
    assert all(any(f"line{i} " in turn.text for turn in tight.history) for i in range(8))


def test_recall_resolves_that_through_the_partners_last_line(conn: sqlite3.Connection) -> None:
    store = sessions(conn)
    add_fact(conn, "behind the waterfall", "location", source="observed", subject="hidden cave")
    # Keeps the guess out of PLAYER, so only recall can find it.
    limits = ContextLimits(max_other_facts=0)

    alone = store.start(GAME).id
    store.log_turn(alone, "player", "Where is that?")
    assert gather_context(conn, GAME, alone, {}, "Where is that?", limits).recalled == []

    session = store.start(GAME).id
    store.log_turn(session, "partner", "Want to go back to the hidden cave?")
    store.log_turn(session, "player", "Where is that?")
    inputs = gather_context(conn, GAME, session, {}, "Where is that?", limits)
    assert any("behind the waterfall" in item for item in inputs.recalled)
