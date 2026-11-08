"""Reads what the talker's context needs. Runs on the voice path, so it never calls an LLM."""

import json
import logging
import sqlite3
from collections.abc import Mapping

from brain.memory.context import DEFAULT_LIMITS, ContextInputs, ContextLimits, fact_from_row
from brain.memory.conversation import partner_line, read_items, without_current
from brain.memory.fact_records import to_question
from brain.memory.models import Fact, Question
from brain.memory.recall import VectorQuery, recall

log = logging.getLogger(__name__)


def _facts(conn: sqlite3.Connection, game: str, limits: ContextLimits) -> list[Fact]:
    """Every current fact the player gave, then the newest few guesses, observed before wiki."""
    current = "f.valid_to IS NULL AND (f.game = ? OR f.game IS NULL)"
    newest = "f.valid_from DESC, f.id DESC"
    player = conn.execute(
        f"SELECT * FROM facts f WHERE {current} AND f.source = 'player' ORDER BY {newest} LIMIT ?",
        (game, limits.max_player_facts),
    ).fetchall()
    others = conn.execute(
        f"SELECT * FROM facts f WHERE {current} AND f.source != 'player'"
        f" ORDER BY CASE f.source WHEN 'observed' THEN 0 ELSE 1 END, {newest} LIMIT ?",
        (game, limits.max_other_facts),
    ).fetchall()
    return [fact_from_row(row) for row in (*player, *others)]


def recall_text(query: str, said: str | None) -> str:
    """The words recalled by: the query plus the partner's last line, so "that" or "it" finds
    what it means. Keyword and meaning-based recall both use this."""
    return f"{query} {said}" if said else query


def last_partner_line(conn: sqlite3.Connection, session_id: int) -> str | None:
    """For embedding the recall text before the rest is read."""
    row = conn.execute(
        "SELECT data FROM events WHERE session_id = ? AND name = 'turn.partner'"
        " ORDER BY ts DESC, id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    try:
        data = json.loads(row["data"]) if row else None
    except (TypeError, ValueError):
        return None
    text = data.get("text") if isinstance(data, dict) else None
    return text if isinstance(text, str) and text.strip() else None


def gather_context(
    conn: sqlite3.Connection,
    game: str,
    session_id: int,
    live_state: Mapping[str, str],
    query: str | None = None,
    limits: ContextLimits = DEFAULT_LIMITS,
    asked_id: int | None = None,
    vector: VectorQuery | None = None,
    current: str | None = None,
    now: float | None = None,
) -> ContextInputs:
    """`conn` must use `sqlite3.Row`, as `brain.memory.db.connect` sets up. `query` is what to
    recall by. `current` is the words being answered, which are left out of the conversation
    because they're the latest message: the transcript on player turns, None otherwise.
    `asked_id` is the question just asked and still waiting for an answer. `vector` is the recall
    text embedded for meaning-based recall; without it, recall matches keywords. `now` is the wall
    clock, for TIME."""
    profile = conn.execute("SELECT brief FROM profile WHERE game = ?", (game,)).fetchone()
    started = conn.execute("SELECT started_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
    note = conn.execute(
        "SELECT id, body FROM session_notes WHERE session_id = ?"
        " ORDER BY created_at DESC, id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    # Looks for the newest session that has a note, so a short or crashed session with none
    # doesn't erase the memory of the one before it.
    last = conn.execute(
        "SELECT n.id, n.body FROM session_notes n JOIN sessions s ON s.id = n.session_id"
        " WHERE s.game = ? AND s.id < ?"
        " ORDER BY s.id DESC, n.kind = 'recap' DESC, n.created_at DESC, n.id DESC LIMIT 1",
        (game, session_id),
    ).fetchone()
    facts = _facts(conn, game, limits)
    items = read_items(conn, session_id, limits.max_turns, limits.max_notes)
    turns = without_current(items, current)

    recalled: list[str] = []
    if query:
        notes = [row["id"] for row in (note, last) if row is not None]
        try:
            skip = [f.id for f in facts]
            text = recall_text(query, partner_line(turns))
            recalled = recall(conn, game, text, skip, notes, limits.max_recalled, vector)
        except sqlite3.Error:
            # Recall is a bonus: losing it must not cost the player a reply.
            log.exception("Recall failed for session %s", session_id)

    # Newest first: the most recent gap is the one most likely to be about what's happening now.
    # Only ones not yet asked: the one being asked shows under ASKED, and the rest were let go.
    unsure = conn.execute(
        "SELECT text FROM questions WHERE status = 'open' AND asked_at IS NULL"
        " AND (game = ? OR game IS NULL) ORDER BY id DESC LIMIT ?",
        (game, limits.max_unsure),
    ).fetchall()
    asked: Question | None = None
    if asked_id is not None:
        row = conn.execute(
            "SELECT * FROM questions WHERE id = ? AND status = 'open'", (asked_id,)
        ).fetchone()
        asked = to_question(row) if row is not None else None

    return ContextInputs(
        game=game,
        brief=profile["brief"] if profile else "",
        live_state=dict(live_state),
        session_note=note["body"] if note else None,
        last_session=last["body"] if last else None,
        facts=facts,
        unsure=[row["text"] for row in unsure],
        recalled=recalled,
        turns=turns,
        asked=asked,
        session_started=started["started_at"] if started else None,
        now=now,
    )
