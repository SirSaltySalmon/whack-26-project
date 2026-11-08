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

# Any question already about this key, open, answered or given up on. Questions about a guess
# name their key through linked facts. One dropped before it was asked was only made moot by newer
# facts, so it doesn't count.
_ASKED_BEFORE = """
SELECT 1 FROM questions q WHERE q.game IS ? AND (
    (q.subject = ? AND q.attribute = ?)
    OR ((q.status != 'dropped' OR q.asked_at IS NOT NULL) AND EXISTS (
        SELECT 1 FROM json_each(q.fact_ids) linked JOIN facts f ON f.id = linked.value
        WHERE f.subject = ? AND f.attribute = ?))
) LIMIT 1
"""


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
        """Opens a question, or returns None when it's known, was ever asked, or over the limit.

        A question the player answered or let pass is never opened again: they moved on, so asking
        again would nag. The key stays unknown, and the talker says so rather than guessing.
        """
        subject, attribute = clean(subject, "subject"), clean(attribute, "attribute")
        text = clean(text, "question")
        with self._conn:
            if self._is_known(game, subject, attribute):
                return None
            if self._asked_before(game, subject, attribute):
                log.info("Not asking about %s / %s again", subject, attribute)
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

    def answerable_questions(
        self, game: str | None, asked_since: float, limit: int = MAX_OPEN_QUESTIONS_IN_PROMPT
    ) -> list[Question]:
        """Every open question, not just unknowns, because a spoken reply can settle any of them.

        Also ones dropped unanswered since `asked_since`, because the player may come back to one.
        """
        rows = self._conn.execute(
            "SELECT * FROM questions WHERE (game = ? OR game IS NULL) AND (status = 'open'"
            " OR (status = 'dropped' AND asked_at >= ?)) ORDER BY id DESC LIMIT ?",
            (game, asked_since, limit),
        ).fetchall()
        return [to_question(row) for row in rows]

    def _is_known(self, game: str | None, subject: str, attribute: str) -> bool:
        # A wiki claim or a guess doesn't count: it's tentative, so asking is still worthwhile.
        return (
            self._conn.execute(
                "SELECT 1 FROM facts WHERE valid_to IS NULL AND game IS ? AND subject = ?"
                " AND attribute = ? AND source IN ('player', 'observed') AND tentative = 0"
                " LIMIT 1",
                (game, subject, attribute),
            ).fetchone()
            is not None
        )

    def _asked_before(self, game: str | None, subject: str, attribute: str) -> bool:
        params = (game, subject, attribute, subject, attribute)
        return self._conn.execute(_ASKED_BEFORE, params).fetchone() is not None
