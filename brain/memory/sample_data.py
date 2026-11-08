"""Explicitly requested fictional memory for testing, isolated from actual games."""

import sqlite3
import time

from brain.memory.facts import FactStore

SAMPLE_GAME = "Memory test (sample)"


def seed_samples(conn: sqlite3.Connection) -> None:
    # Don't restore a sample note the player just deleted when the button is clicked again.
    if conn.execute("SELECT 1 FROM sessions WHERE game = ?", (SAMPLE_GAME,)).fetchone():
        return
    now = time.time()
    with conn:
        session_id = conn.execute(
            "INSERT INTO sessions (game, started_at, ended_at) VALUES (?, ?, ?)",
            (SAMPLE_GAME, now - 600, now),
        ).lastrowid
        notes = [
            (
                "rolling",
                "[SAMPLE — fictional] Built a wooden starter house near spawn. "
                "Next goal: replace the roof with glass. Try editing this note.",
            ),
            (
                "recap",
                "[SAMPLE — fictional] Explored a cave and stored spare tools in a chest. "
                "Try deleting this note, then search for spare tools to check it disappeared.",
            ),
        ]
        conn.executemany(
            "INSERT INTO session_notes"
            " (session_id, kind, body, from_ts, to_ts, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [(session_id, kind, body, now - 600, now, now) for kind, body in notes],
        )
    store = FactStore(conn)
    store.remember(
        SAMPLE_GAME,
        "sample player",
        "goal",
        "Build a glass castle (sample)",
        "player",
        1.0,
        session_id=session_id,
    )
    store.remember(
        SAMPLE_GAME,
        "sample player",
        "preference",
        "Avoid spoilers (sample)",
        "player",
        1.0,
        session_id=session_id,
    )
