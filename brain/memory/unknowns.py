"""Things the partner hasn't understood about the game yet, and has no guess for.

Low confidence isn't only a shaky reading of a known fact. Often the partner just hasn't discovered
a detail, so the right move is to talk to the player about it instead of inventing a value. These
are questions with no fact behind them: the player's answer becomes the fact.
"""

import logging
import sqlite3
import time
from collections.abc import Callable

from brain.memory.fact_records import clean, to_question
from brain.memory.models import Question

log = logging.getLogger(__name__)

# Curiosity shouldn't pile up faster than the director's question budget can spend it.
MAX_OPEN_UNKNOWNS = 5
MAX_OPEN_QUESTIONS_IN_PROMPT = 10


class UnknownStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._conn = conn
        self._clock = clock

    def wonder(
        self,
        game: str | None,
        subject: str,
        attribute: str,
        text: str,
        session_id: int | None = None,
    ) -> Question | None:
        """Opens a question, or returns None when it's already known, asked or over the limit."""
        subject, attribute = clean(subject, "subject"), clean(attribute, "attribute")
        text = clean(text, "question")
        with self._conn:
            if self._is_known(game, subject, attribute) or self._is_open(game, subject, attribute):
                return None
            open_count = self._conn.execute(
                "SELECT COUNT(*) FROM questions WHERE status = 'open' AND game IS ?"
                " AND subject IS NOT NULL",
                (game,),
            ).fetchone()[0]
            if open_count >= MAX_OPEN_UNKNOWNS:
                log.info("Not opening a question about %s: too many are open", subject)
                return None
            cursor = self._conn.execute(
                "INSERT INTO questions (game, session_id, text, subject, attribute, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (game, session_id, text, subject, attribute, self._clock()),
            )
            row = self._conn.execute(
                "SELECT * FROM questions WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return to_question(row)

    def open_questions(self, game: str | None, limit: int = 10) -> list[Question]:
        """Every open question, not just unknowns, because a spoken reply can settle any of them."""
        rows = self._conn.execute(
            "SELECT * FROM questions WHERE status = 'open' AND (game = ? OR game IS NULL)"
            " ORDER BY id DESC LIMIT ?",
            (game, limit),
        ).fetchall()
        return [to_question(row) for row in rows]

    def _is_known(self, game: str | None, subject: str, attribute: str) -> bool:
        # A wiki claim doesn't count: it's tentative, so asking the player is still worthwhile.
        return (
            self._conn.execute(
                "SELECT 1 FROM facts WHERE valid_to IS NULL AND game IS ? AND subject = ?"
                " AND attribute = ? AND source IN ('player', 'observed') LIMIT 1",
                (game, subject, attribute),
            ).fetchone()
            is not None
        )

    def _is_open(self, game: str | None, subject: str, attribute: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM questions WHERE status = 'open' AND game IS ? AND subject = ?"
                " AND attribute = ? LIMIT 1",
                (game, subject, attribute),
            ).fetchone()
            is not None
        )
