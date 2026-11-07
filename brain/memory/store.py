"""SQLite access. WAL lets the fast loops read while the slow loop writes.

TODO(track 4): conflict handling (when to close a fact and when to ask), the context assembler,
rolling summaries, and vector recall with sqlite-vec and fastembed.
"""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Source = Literal["player", "observed", "wiki"]
SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    return conn


@dataclass(frozen=True)
class Fact:
    id: int
    attribute: str
    value: str
    source: Source
    confidence: float
    tentative: bool


class MemoryStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add_fact(
        self,
        attribute: str,
        value: str,
        source: Source,
        confidence: float,
        entity_id: int | None = None,
    ) -> int:
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO facts (entity_id, attribute, value, source, confidence, tentative,"
                " valid_from) VALUES (?, ?, ?, ?, ?, ?, ?)",
                # Wiki facts stay tentative until the player or the screen confirms them.
                (entity_id, attribute, value, source, confidence, source == "wiki", time.time()),
            )
        return int(cursor.lastrowid or 0)

    def close_fact(self, fact_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE facts SET valid_to = ? WHERE id = ? AND valid_to IS NULL",
                (time.time(), fact_id),
            )

    def search_current(self, query: str, limit: int = 10) -> list[Fact]:
        rows = self._conn.execute(
            "SELECT f.id, f.attribute, f.value, f.source, f.confidence, f.tentative"
            " FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid"
            " WHERE facts_fts MATCH ? AND f.valid_to IS NULL ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
        return [
            Fact(
                r["id"],
                r["attribute"],
                r["value"],
                r["source"],
                r["confidence"],
                bool(r["tentative"]),
            )
            for r in rows
        ]
