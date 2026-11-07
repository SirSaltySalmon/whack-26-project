"""Fixed starting memory for replay runs, so the same recording always behaves the same way.

The snapshot is SQL text rather than a database file because it gets committed to fixtures/, where
a reviewer needs to read it. Search indexes aren't dumped: the insert triggers rebuild them.
"""

import logging
import sqlite3
from pathlib import Path

from brain.memory.db import connect

log = logging.getLogger(__name__)

# Parents before children, for the foreign keys. wiki_cache is left out: it's lookup material,
# and a replay shouldn't depend on it.
SNAPSHOT_TABLES = (
    "profile",
    "player",
    "sessions",
    "events",
    "session_notes",
    "facts",
    "questions",
)


def dump_snapshot(conn: sqlite3.Connection) -> str:
    lines: list[str] = []
    for table in SNAPSHOT_TABLES:
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        # quote() makes SQLite write the literals, so no text in memory can break out of a value.
        values = " || ',' || ".join(f"quote({column})" for column in columns)
        names = ", ".join(columns)
        for row in conn.execute(f"SELECT {values} FROM {table} ORDER BY rowid"):
            lines.append(f"INSERT INTO {table} ({names}) VALUES ({row[0]});")
    return "\n".join(lines) + "\n"


def connect_replay(snapshot: Path) -> sqlite3.Connection:
    """Always in memory, so nothing from a replay can reach the player's real memory."""
    conn = connect(":memory:")
    if not snapshot.exists():
        log.info("No replay memory snapshot at %s; starting empty", snapshot)
        return conn
    try:
        conn.executescript(snapshot.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, sqlite3.Error):
        # Replay is the stage fallback, so a stale snapshot must not stop it from running. A new
        # connection is needed because the failed script may have loaded only part of the file.
        log.exception("Couldn't load replay memory snapshot %s; starting empty", snapshot)
        conn.close()
        return connect(":memory:")
    log.info("Loaded replay memory snapshot from %s", snapshot)
    return conn
