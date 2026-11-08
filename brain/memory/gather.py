"""Reads what the talker's context needs. Runs on the voice path, so it never calls an LLM."""

import json
import logging
import sqlite3
from collections.abc import Mapping
from typing import Any

from brain.memory.context import DEFAULT_LIMITS, ContextInputs, ContextLimits, fact_from_row
from brain.memory.fact_records import to_question
from brain.memory.models import Question, Speaker, Turn
from brain.memory.recall import VectorQuery, recall

log = logging.getLogger(__name__)


def _turn_text(data: str | None) -> str | None:
    try:
        parsed: Any = json.loads(data) if data else None
    except (TypeError, ValueError):
        return None
    text = parsed.get("text") if isinstance(parsed, dict) else None
    return text if isinstance(text, str) and text.strip() else None


def _recent_turns(conn: sqlite3.Connection, session_id: int, limit: int) -> list[Turn]:
    rows = conn.execute(
        "SELECT name, data, ts FROM events WHERE session_id = ?"
        " AND name IN ('turn.player', 'turn.partner') ORDER BY ts DESC, id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    turns: list[Turn] = []
    for row in reversed(rows):
        text = _turn_text(row["data"])
        if text is None:
            log.warning("Skipping a turn with unusable data in session %s", session_id)
            continue
        speaker: Speaker = "player" if row["name"] == "turn.player" else "partner"
        turns.append(Turn(speaker=speaker, text=text, ts=row["ts"]))
    return turns


def gather_context(
    conn: sqlite3.Connection,
    game: str,
    session_id: int,
    live_state: Mapping[str, str],
    query: str | None = None,
    limits: ContextLimits = DEFAULT_LIMITS,
    asked_id: int | None = None,
    vector: VectorQuery | None = None,
) -> ContextInputs:
    """`conn` must use `sqlite3.Row`, as `brain.memory.db.connect` sets up. `asked_id` is the
    question just asked and still waiting for an answer. `vector` is the query embedded for
    meaning-based recall; without it, recall matches keywords."""
    profile = conn.execute("SELECT brief FROM profile WHERE game = ?", (game,)).fetchone()
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
    fact_rows = conn.execute(
        "SELECT * FROM facts f WHERE f.valid_to IS NULL AND (f.game = ? OR f.game IS NULL)"
        " ORDER BY CASE f.source WHEN 'player' THEN 0 WHEN 'observed' THEN 1 ELSE 2 END,"
        " f.valid_from DESC, f.id DESC LIMIT ?",
        (game, limits.max_facts),
    ).fetchall()
    facts = [fact_from_row(row) for row in fact_rows]

    recalled: list[str] = []
    if query:
        notes = [row["id"] for row in (note, last) if row is not None]
        try:
            skip = [f.id for f in facts]
            recalled = recall(conn, game, query, skip, notes, limits.max_recalled, vector)
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
        turns=_recent_turns(conn, session_id, limits.max_turns),
        asked=asked,
    )
