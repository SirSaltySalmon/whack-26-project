"""Player-requested note changes, including invalidation of derived search indexes."""

import sqlite3

from shared.protocol.admin import AdminNote, MemoryAdminRequest


def list_notes(conn: sqlite3.Connection) -> list[AdminNote]:
    rows = conn.execute(
        "SELECT n.id, n.session_id, s.game, n.kind, n.body, n.created_at"
        " FROM session_notes n JOIN sessions s ON s.id = n.session_id"
        " ORDER BY n.created_at DESC, n.id DESC LIMIT 200"
    ).fetchall()
    return [AdminNote(**dict(row)) for row in rows]


def change_note(conn: sqlite3.Connection, request: MemoryAdminRequest) -> None:
    if request.note_id is None:
        raise ValueError("Choose a session note")
    if request.operation == "edit_note" and not request.body.strip():
        raise ValueError("A note cannot be empty; use Delete note instead")
    has_vectors = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'note_vectors'").fetchone()
    if has_vectors:
        from brain.memory.vectors import load_extension

        load_extension(conn)
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT body FROM session_notes WHERE id = ?", (request.note_id,)
        ).fetchone()
        if row is None:
            raise ValueError("That note no longer exists; refresh memory")
        if request.expected_body is not None and row["body"] != request.expected_body:
            raise ValueError("That note changed since you opened it; refresh before editing")
        if has_vectors:
            conn.execute("DELETE FROM note_vectors WHERE note_id = ?", (request.note_id,))
        if request.operation == "delete_note":
            # The existing delete trigger also removes its full-text search entry.
            conn.execute("DELETE FROM session_notes WHERE id = ?", (request.note_id,))
        else:
            # schema.sql has insert/delete triggers only. Keep this explicit edit atomic with FTS.
            conn.execute(
                "INSERT INTO session_notes_fts (session_notes_fts, rowid, body)"
                " VALUES ('delete', ?, ?)",
                (request.note_id, row["body"]),
            )
            conn.execute(
                "UPDATE session_notes SET body = ? WHERE id = ?", (request.body, request.note_id)
            )
            conn.execute(
                "INSERT INTO session_notes_fts (rowid, body) VALUES (?, ?)",
                (request.note_id, request.body),
            )
