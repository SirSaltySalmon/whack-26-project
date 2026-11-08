"""The vector index for memory recall: sqlite-vec tables beside the facts and session notes.

It's derived data. The rows stay the source of truth, vectors are added after the rows are
written, and a change of model rebuilds them because vectors from two models can't be compared.
The tables only appear once meaning-based search is turned on, and nothing else reads them, so a
connection without the extension still opens the database and works normally.
"""

import logging
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import sqlite_vec
from sqlite_vec import serialize_float32

from brain.memory.context import fact_from_row, format_fact
from brain.memory.models import Hit

log = logging.getLogger(__name__)

# Long enough for a note bullet with its heading, short enough that one idea fills the vector.
_CHUNK_CHARS = 300
_HEADING = re.compile(r"^(?:#{1,6}\s+(.+)|\*\*(.+?)\*\*:?)$")
_BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
# Rows read per note search. Notes are found one chunk at a time, then kept once per note.
_NOTE_CANDIDATES = 50


@dataclass(frozen=True)
class Pending:
    kind: Literal["fact", "note"]
    item_id: int
    text: str


def load_extension(conn: sqlite3.Connection) -> None:
    """Raises on a Python that can't load SQLite extensions, as some macOS builds can't."""
    try:
        conn.execute("SELECT vec_version()")
        return
    except sqlite3.OperationalError:
        pass
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


def prepare(conn: sqlite3.Connection, model: str, dims: int) -> None:
    if dims <= 0:
        raise ValueError(f"Embedding model {model} returned {dims} dimensions")
    load_extension(conn)
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS vector_model"
            " (id INTEGER PRIMARY KEY CHECK (id = 1), model TEXT NOT NULL, dims INTEGER NOT NULL)"
        )
        row = conn.execute("SELECT model, dims FROM vector_model").fetchone()
        if row is not None and (row["model"], row["dims"]) != (model, dims):
            log.info("Embedding model is now %s, was %s: rebuilding vectors", model, row["model"])
            conn.execute("DROP TABLE IF EXISTS fact_vectors")
            conn.execute("DROP TABLE IF EXISTS note_vectors")
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fact_vectors"
            f" USING vec0 (embedding float[{int(dims)}] distance_metric=cosine)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS note_vectors USING vec0"
            f" (embedding float[{int(dims)}] distance_metric=cosine, note_id INTEGER, +chunk TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO vector_model (id, model, dims) VALUES (1, ?, ?)", (model, dims)
        )


def fact_text(subject: str, attribute: str, value: str) -> str:
    # No " / " as in the talker's format: it's noise to the model, and the words are what matter.
    return f"{subject} {attribute}: {value}"


def note_chunks(body: str) -> list[str]:
    """One chunk per line under its heading, so a question about one moment in a note matches
    that line rather than the whole note's average."""
    chunks: list[str] = []
    heading = ""
    for raw in body.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        if found := _HEADING.match(line):
            heading = (found[1] or found[2]).strip()
            continue
        text = _BULLET.sub("", line)
        chunks.append((f"{heading}: {text}" if heading else text)[:_CHUNK_CHARS])
    # A note of nothing but headings still gets a vector, or it would stay pending forever.
    if not chunks and body.strip():
        chunks.append(" ".join(body.split())[:_CHUNK_CHARS])
    return chunks


def pending(conn: sqlite3.Connection, max_items: int) -> list[Pending]:
    """Current facts and notes without vectors, oldest first. A note's chunks always come
    together, so a note is never left half indexed."""
    facts = conn.execute(
        "SELECT id, subject, attribute, value FROM facts WHERE valid_to IS NULL"
        " AND id NOT IN (SELECT rowid FROM fact_vectors) ORDER BY id LIMIT ?",
        (max_items,),
    ).fetchall()
    found = [
        Pending("fact", row["id"], fact_text(row["subject"], row["attribute"], row["value"]))
        for row in facts
    ]
    if len(found) >= max_items:
        return found
    notes = conn.execute(
        "SELECT id, body FROM session_notes WHERE trim(body) != ''"
        " AND id NOT IN (SELECT note_id FROM note_vectors) ORDER BY id LIMIT ?",
        (max_items - len(found),),
    ).fetchall()
    for row in notes:
        found.extend(Pending("note", row["id"], chunk) for chunk in note_chunks(row["body"]))
    return found


def store(
    conn: sqlite3.Connection, items: Sequence[Pending], vectors: Sequence[Sequence[float]]
) -> None:
    with conn:
        for item, vector in zip(items, vectors, strict=True):
            blob = serialize_float32(vector)
            if item.kind == "fact":
                conn.execute(
                    "INSERT INTO fact_vectors (rowid, embedding) VALUES (?, ?)",
                    (item.item_id, blob),
                )
            else:
                conn.execute(
                    "INSERT INTO note_vectors (embedding, note_id, chunk) VALUES (?, ?, ?)",
                    (blob, item.item_id, item.text),
                )


def search(
    conn: sqlite3.Connection,
    game: str,
    vector: Sequence[float],
    skip_facts: Sequence[int],
    skip_notes: Sequence[int],
    limit: int,
    min_similarity: float,
) -> list[Hit]:
    """Current facts and this game's notes, most similar first, above `min_similarity`.

    Exact distances over every row rather than vec0's nearest-neighbour search, which picks its
    neighbours before these filters run and so finds nothing once most facts are closed or belong
    to another game. Memory holds hundreds of rows, not millions, so this takes a millisecond.
    """
    blob = serialize_float32(vector)
    fact_marks = ", ".join("?" * len(skip_facts))
    fact_rows = conn.execute(
        "SELECT f.*, 1 - vec_distance_cosine(v.embedding, ?) AS similarity"
        " FROM fact_vectors v CROSS JOIN facts f ON f.id = v.rowid"
        " WHERE f.valid_to IS NULL AND (f.game = ? OR f.game IS NULL)"
        f" AND f.id NOT IN ({fact_marks}) ORDER BY similarity DESC LIMIT ?",
        (blob, game, *skip_facts, limit),
    ).fetchall()
    note_marks = ", ".join("?" * len(skip_notes))
    note_rows = conn.execute(
        "SELECT v.note_id, v.chunk, 1 - vec_distance_cosine(v.embedding, ?) AS similarity"
        " FROM note_vectors v CROSS JOIN session_notes n ON n.id = v.note_id"
        " JOIN sessions s ON s.id = n.session_id"
        f" WHERE s.game = ? AND n.id NOT IN ({note_marks}) ORDER BY similarity DESC LIMIT ?",
        (blob, game, *skip_notes, _NOTE_CANDIDATES),
    ).fetchall()

    scored: list[tuple[float, Hit]] = [
        (row["similarity"], Hit(("fact", row["id"]), format_fact(fact_from_row(row))))
        for row in fact_rows
    ]
    seen_notes: set[int] = set()
    for row in note_rows:
        if row["note_id"] not in seen_notes:
            seen_notes.add(row["note_id"])
            scored.append((row["similarity"], Hit(("note", row["note_id"]), row["chunk"])))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [hit for similarity, hit in scored if similarity >= min_similarity][:limit]
