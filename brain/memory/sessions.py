"""Play sessions, what happened in them, and the Markdown notes written about them."""

import json
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from brain.memory.fts import to_match_query
from brain.memory.models import LoggedEvent, Note, NoteKind, Session, Speaker, Turn

TURN_PREFIX = "turn."

_NOTE_COLUMNS = "n.id, n.session_id, n.kind, n.body, n.from_ts, n.to_ts, n.created_at"


def _to_session(row: sqlite3.Row) -> Session:
    return Session(row["id"], row["game"], row["started_at"], row["ended_at"])


def _to_event(row: sqlite3.Row) -> LoggedEvent:
    data = json.loads(row["data"]) if row["data"] is not None else None
    return LoggedEvent(row["id"], row["session_id"], row["ts"], row["name"], data)


def _to_note(row: sqlite3.Row) -> Note:
    return Note(
        row["id"],
        row["session_id"],
        row["kind"],
        row["body"],
        row["from_ts"],
        row["to_ts"],
        row["created_at"],
    )


class SessionStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._conn = conn
        self._clock = clock

    def start(self, game: str) -> Session:
        now = self._clock()
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO sessions (game, started_at) VALUES (?, ?)", (game, now)
            )
        return Session(int(cursor.lastrowid or 0), game, now)

    def end(self, session_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
                (self._clock(), session_id),
            )

    def previous(self, game: str, before_session_id: int) -> Session | None:
        # Ordered by id, not started_at: ids always increase, but the wall clock can step back.
        row = self._conn.execute(
            "SELECT id, game, started_at, ended_at FROM sessions"
            " WHERE game = ? AND id < ? ORDER BY id DESC LIMIT 1",
            (game, before_session_id),
        ).fetchone()
        return _to_session(row) if row is not None else None

    def log_event(
        self, session_id: int, name: str, data: dict[str, Any] | None = None
    ) -> LoggedEvent:
        now = self._clock()
        encoded = json.dumps(data) if data is not None else None
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO events (session_id, ts, name, data) VALUES (?, ?, ?, ?)",
                (session_id, now, name, encoded),
            )
        return LoggedEvent(int(cursor.lastrowid or 0), session_id, now, name, data)

    def log_turn(self, session_id: int, speaker: Speaker, text: str) -> None:
        self.log_event(session_id, f"{TURN_PREFIX}{speaker}", {"text": text})

    def recent_turns(self, session_id: int, limit: int = 6) -> list[Turn]:
        # Ties on ts are broken by id so two turns logged in the same clock tick keep their order.
        rows = self._conn.execute(
            "SELECT id, session_id, ts, name, data FROM events"
            " WHERE session_id = ? AND name IN (?, ?) ORDER BY ts DESC, id DESC LIMIT ?",
            (session_id, f"{TURN_PREFIX}player", f"{TURN_PREFIX}partner", limit),
        ).fetchall()
        turns: list[Turn] = []
        for row in reversed(rows):
            speaker: Speaker = "player" if row["name"] == f"{TURN_PREFIX}player" else "partner"
            turns.append(Turn(speaker, json.loads(row["data"])["text"], row["ts"]))
        return turns

    def events_since(self, session_id: int, since_ts: float, limit: int = 200) -> list[LoggedEvent]:
        # Takes the newest events when over the limit, because the next note builds on the present.
        rows = self._conn.execute(
            "SELECT id, session_id, ts, name, data FROM events"
            " WHERE session_id = ? AND ts > ? ORDER BY ts DESC, id DESC LIMIT ?",
            (session_id, since_ts, limit),
        ).fetchall()
        return [_to_event(row) for row in reversed(rows)]

    def add_note(
        self, session_id: int, kind: NoteKind, body: str, from_ts: float, to_ts: float
    ) -> Note:
        now = self._clock()
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO session_notes (session_id, kind, body, from_ts, to_ts, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, kind, body, from_ts, to_ts, now),
            )
        return Note(int(cursor.lastrowid or 0), session_id, kind, body, from_ts, to_ts, now)

    def latest_note(self, session_id: int, kind: NoteKind | None = None) -> Note | None:
        sql = f"SELECT {_NOTE_COLUMNS} FROM session_notes n WHERE n.session_id = ?"
        params: list[Any] = [session_id]
        if kind is not None:
            sql += " AND n.kind = ?"
            params.append(kind)
        row = self._conn.execute(sql + " ORDER BY n.created_at DESC, n.id DESC LIMIT 1", params)
        found = row.fetchone()
        return _to_note(found) if found is not None else None

    def notes_for_session(self, session_id: int) -> list[Note]:
        rows = self._conn.execute(
            f"SELECT {_NOTE_COLUMNS} FROM session_notes n"
            " WHERE n.session_id = ? ORDER BY n.created_at, n.id",
            (session_id,),
        ).fetchall()
        return [_to_note(row) for row in rows]

    def search_notes(self, game: str, query: str, limit: int = 5) -> list[Note]:
        match = to_match_query(query)
        if match is None:
            return []
        rows = self._conn.execute(
            f"SELECT {_NOTE_COLUMNS} FROM session_notes_fts"
            " JOIN session_notes n ON n.id = session_notes_fts.rowid"
            " JOIN sessions s ON s.id = n.session_id"
            " WHERE session_notes_fts MATCH ? AND s.game = ? ORDER BY rank LIMIT ?",
            (match, game, limit),
        ).fetchall()
        return [_to_note(row) for row in rows]
