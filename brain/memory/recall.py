"""Finds what memory holds about the player's words, by keywords, by meaning, or both.

Runs inside the database worker on the voice path, so it never calls a model: SemanticRecall
embeds the question first and hands over the vector.
"""

import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from brain.memory import vectors
from brain.memory.context import fact_from_row, format_fact
from brain.memory.fts import to_match_query
from brain.memory.models import Hit

log = logging.getLogger(__name__)

# Reciprocal rank fusion's usual constant. Fusing by rank means FTS5's bm25 and cosine similarity
# never need to be on the same scale.
RRF_K = 60


@dataclass(frozen=True)
class VectorQuery:
    vector: Sequence[float]
    # True for "semantic", which skips keywords. False for "hybrid", which merges both.
    semantic_only: bool
    min_similarity: float


def keyword_hits(
    conn: sqlite3.Connection,
    game: str,
    query: str,
    skip_facts: Sequence[int],
    skip_notes: Sequence[int],
    limit: int,
) -> list[Hit]:
    """Facts first, then notes, each in FTS5 rank order."""
    match = to_match_query(query)
    if match is None:
        return []
    fact_marks = ", ".join("?" * len(skip_facts))
    fact_rows = conn.execute(
        "SELECT f.* FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid"
        " WHERE facts_fts MATCH ? AND f.valid_to IS NULL AND (f.game = ? OR f.game IS NULL)"
        f" AND f.id NOT IN ({fact_marks}) ORDER BY rank LIMIT ?",
        (match, game, *skip_facts, limit),
    ).fetchall()
    note_marks = ", ".join("?" * len(skip_notes))
    # A snippet, because a whole note would use up the section on one match.
    note_rows = conn.execute(
        "SELECT n.id, snippet(session_notes_fts, 0, '', '', '…', 24) AS excerpt"
        " FROM session_notes_fts JOIN session_notes n ON n.id = session_notes_fts.rowid"
        " JOIN sessions s ON s.id = n.session_id"
        " WHERE session_notes_fts MATCH ? AND s.game = ?"
        f" AND n.id NOT IN ({note_marks}) ORDER BY rank LIMIT ?",
        (match, game, *skip_notes, limit),
    ).fetchall()
    hits = [Hit(("fact", row["id"]), format_fact(fact_from_row(row))) for row in fact_rows]
    hits.extend(Hit(("note", row["id"]), row["excerpt"]) for row in note_rows)
    return hits


def fuse(*rankings: Sequence[Hit]) -> list[Hit]:
    """Merges ranked lists. Something found by both rises; a tie keeps the earlier list's order.
    The text kept is from the first list that found it, so keywords' snippets win."""
    scores: dict[tuple[str, int], float] = {}
    first: dict[tuple[str, int], Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking):
            scores[hit.key] = scores.get(hit.key, 0.0) + 1 / (RRF_K + rank)
            first.setdefault(hit.key, hit)
    # sorted() is stable and dicts keep insertion order, so ties stay in first-seen order.
    return [first[key] for key in sorted(scores, key=lambda key: -scores[key])]


def recall(
    conn: sqlite3.Connection,
    game: str,
    query: str,
    skip_facts: Sequence[int],
    skip_notes: Sequence[int],
    limit: int,
    vector: VectorQuery | None = None,
) -> list[str]:
    """Text lines for the talker's RECALL section. Without a vector, keywords only."""
    meaning: list[Hit] | None = None
    if vector is not None:
        try:
            meaning = vectors.search(
                conn, game, vector.vector, skip_facts, skip_notes, limit, vector.min_similarity
            )
        except sqlite3.Error:
            # Meaning is a bonus, so losing it falls back to keywords rather than to nothing.
            log.exception("Vector recall failed; recalling by keywords")
    if vector is not None and vector.semantic_only and meaning is not None:
        hits = meaning
    else:
        keyword = keyword_hits(conn, game, query, skip_facts, skip_notes, limit)
        hits = fuse(keyword, meaning) if meaning else keyword
    return list(dict.fromkeys(hit.text for hit in hits))[:limit]
