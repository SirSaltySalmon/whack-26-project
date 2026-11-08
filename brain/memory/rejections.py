"""Values the player said are wrong, so a later guess can't quietly bring one back.

Kept as one row per game in the player key/value table, because the schema can't change now that
databases exist. Only the player stating a value again lifts its rejection. Sync, and called inside
FactStore's transaction.
"""

import json
import sqlite3
from collections.abc import Iterable
from typing import Any

# A few per key is plenty: they're wrong readings of one thing, not a history.
MAX_PER_KEY = 8


def _row_key(game: str | None) -> str:
    return f"rejected:{json.dumps(game)}"


def _slot(subject: str, attribute: str) -> str:
    return f"{subject.casefold()} / {attribute.casefold()}"


def _normal(value: str) -> str:
    return " ".join(value.split()).casefold()


def _load(conn: sqlite3.Connection, game: str | None) -> dict[str, list[str]]:
    row = conn.execute("SELECT value FROM player WHERE key = ?", (_row_key(game),)).fetchone()
    data: Any = json.loads(row[0]) if row is not None else {}
    return data if isinstance(data, dict) else {}


def is_rejected(
    conn: sqlite3.Connection, game: str | None, subject: str, attribute: str, value: str
) -> bool:
    return _normal(value) in _load(conn, game).get(_slot(subject, attribute), [])


def update_rejected(
    conn: sqlite3.Connection,
    game: str | None,
    subject: str,
    attribute: str,
    *,
    add: Iterable[str] = (),
    lift: str | None = None,
) -> None:
    """Adds values the player rejected, and lifts one the player has just stated themselves."""
    data = _load(conn, game)
    slot = _slot(subject, attribute)
    before = list(data.get(slot, []))
    lifted = _normal(lift) if lift is not None else None
    values = [value for value in before if value != lifted]
    for value in map(_normal, add):
        if value and value != lifted and value not in values:
            values.append(value)
    values = values[-MAX_PER_KEY:]
    if values == before:
        return
    if values:
        data[slot] = values
    else:
        data.pop(slot, None)
    conn.execute(
        "INSERT INTO player (key, value) VALUES (?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (_row_key(game), json.dumps(data)),
    )
