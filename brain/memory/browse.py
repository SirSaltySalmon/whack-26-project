"""Read-only views of memory for the Control Center. Never writes, so the trust rules in facts.py
stay the only way in.

Run these through Database.run so they stay off the event loop and in order with writes.
"""

import json
import sqlite3
from dataclasses import dataclass

from brain.memory.fts import to_match_query
from shared.protocol.control import FactView, NoteView, QuestionView

QUESTION_LIMIT = 20
NOTE_LIMIT = 5


@dataclass(frozen=True)
class Browse:
    facts: list[FactView]
    questions: list[QuestionView]
    notes: list[NoteView]


def _fact(row: sqlite3.Row) -> FactView:
    return FactView(
        id=row["id"],
        subject=row["subject"],
        attribute=row["attribute"],
        value=row["value"],
        source=row["source"],
        confidence=row["confidence"],
        tentative=bool(row["tentative"]),
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
    )


def _question(row: sqlite3.Row) -> QuestionView:
    return QuestionView(
        id=row["id"],
        text=row["text"],
        options=json.loads(row["options"]),
        status=row["status"],
        answer=row["answer"],
    )


def _note(row: sqlite3.Row) -> NoteView:
    return NoteView(id=row["id"], kind=row["kind"], body=row["body"], created_at=row["created_at"])


def facts(
    conn: sqlite3.Connection, game: str, text: str, include_history: bool, limit: int
) -> list[FactView]:
    """Search when the text has words worth matching, otherwise the newest facts first."""
    match = to_match_query(text)
    scope = "(f.game = ? OR f.game IS NULL) AND (? OR f.valid_to IS NULL)"
    if match is None:
        sql = f"SELECT f.* FROM facts f WHERE {scope} ORDER BY f.valid_from DESC, f.id DESC LIMIT ?"
        rows = conn.execute(sql, (game, include_history, limit)).fetchall()
    else:
        sql = (
            "SELECT f.* FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid"
            f" WHERE facts_fts MATCH ? AND {scope} ORDER BY rank LIMIT ?"
        )
        rows = conn.execute(sql, (match, game, include_history, limit)).fetchall()
    return [_fact(row) for row in rows]


def questions(conn: sqlite3.Connection, game: str, include_history: bool) -> list[QuestionView]:
    rows = conn.execute(
        "SELECT * FROM questions WHERE (game = ? OR game IS NULL) AND (? OR status = 'open')"
        " ORDER BY created_at DESC, id DESC LIMIT ?",
        (game, include_history, QUESTION_LIMIT),
    ).fetchall()
    return [_question(row) for row in rows]


def notes(conn: sqlite3.Connection, game: str, text: str) -> list[NoteView]:
    match = to_match_query(text)
    columns = "n.id, n.kind, n.body, n.created_at"
    if match is None:
        rows = conn.execute(
            f"SELECT {columns} FROM session_notes n JOIN sessions s ON s.id = n.session_id"
            " WHERE s.game = ? ORDER BY n.created_at DESC, n.id DESC LIMIT ?",
            (game, NOTE_LIMIT),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {columns} FROM session_notes_fts"
            " JOIN session_notes n ON n.id = session_notes_fts.rowid"
            " JOIN sessions s ON s.id = n.session_id"
            " WHERE session_notes_fts MATCH ? AND s.game = ? ORDER BY rank LIMIT ?",
            (match, game, NOTE_LIMIT),
        ).fetchall()
    return [_note(row) for row in rows]


def browse(
    conn: sqlite3.Connection, game: str, text: str, include_history: bool, limit: int
) -> Browse:
    return Browse(
        facts(conn, game, text, include_history, limit),
        questions(conn, game, include_history),
        notes(conn, game, text),
    )
