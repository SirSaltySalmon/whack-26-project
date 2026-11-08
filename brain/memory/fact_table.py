"""The question queue and row-level writes under FactStore, kept apart so the trust rules in
facts.py stay short.

Nothing here decides what's true. Callers hold the transaction and choose what to close or insert.
"""

import json
import logging
import sqlite3
import time
from collections.abc import Callable, Iterable

from brain.memory.fact_records import NewFact, to_fact, to_question
from brain.memory.models import Fact, Question

log = logging.getLogger(__name__)

AUTHORITY_ORDER = "CASE source WHEN 'player' THEN 0 WHEN 'observed' THEN 1 ELSE 2 END"


class FactTable:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._conn = conn
        self._clock = clock

    # --- Question queue ---
    def next_question(self, game: str | None) -> Question | None:
        rows = self._rows(
            "SELECT * FROM questions WHERE status = 'open' AND asked_at IS NULL"
            " AND (game = ? OR game IS NULL) ORDER BY created_at, id",
            game,
        )
        for question in map(to_question, rows):
            linked = self._facts_by_id(question.fact_ids)
            if not question.fact_ids or any(fact.valid_to is None for fact in linked):
                return question
            # Newer information already settled it, so asking would only be nagging.
            log.info("Dropping question %s: its facts are no longer current", question.id)
            self.drop_question(question.id)
        return None

    def question_status(self, question_id: int) -> str | None:
        rows = self._rows("SELECT status FROM questions WHERE id = ?", question_id)
        return rows[0]["status"] if rows else None

    def mark_asked(self, question_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE questions SET asked_at = ? WHERE id = ? AND status = 'open'"
                " AND asked_at IS NULL",
                (self._clock(), question_id),
            )

    def unmark_asked(self, question_id: int) -> None:
        """The partner never got to say it, so it goes back in the queue."""
        with self._conn:
            self._conn.execute(
                "UPDATE questions SET asked_at = NULL WHERE id = ? AND status = 'open'",
                (question_id,),
            )

    def drop_question(self, question_id: int) -> bool:
        """Returns whether it was still open."""
        with self._conn:
            return self._drop(question_id)

    def drop_stale_asked(self, game: str | None) -> list[int]:
        """Drops questions asked in an earlier run and never answered: nobody is waiting now."""
        with self._conn:
            rows = self._rows(
                "SELECT id FROM questions WHERE status = 'open' AND asked_at IS NOT NULL"
                " AND (game = ? OR game IS NULL)",
                game,
            )
            return [row["id"] for row in rows if self._drop(row["id"])]

    def _rows(self, sql: str, *params: object) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def _question(self, question_id: int) -> Question:
        return to_question(self._rows("SELECT * FROM questions WHERE id = ?", question_id)[0])

    def _open_questions(self, game: str | None) -> list[Question]:
        sql = "SELECT * FROM questions WHERE status = 'open' AND game IS ? ORDER BY id"
        return [to_question(row) for row in self._rows(sql, game)]

    def _fact(self, fact_id: int) -> Fact:
        return to_fact(self._rows("SELECT * FROM facts WHERE id = ?", fact_id)[0])

    def _facts_by_id(self, fact_ids: list[int]) -> list[Fact]:
        """Includes closed facts, and keeps the given order so "first linked fact" is stable."""
        rows = [self._rows("SELECT * FROM facts WHERE id = ?", fact_id) for fact_id in fact_ids]
        return [to_fact(found[0]) for found in rows if found]

    def _current_exact(self, game: str | None, subject: str, attribute: str) -> list[Fact]:
        """Unlike current(), a NULL game only matches NULL, so games never settle each other."""
        sql = (
            "SELECT * FROM facts WHERE valid_to IS NULL AND game IS ? AND subject = ?"
            f" AND attribute = ? ORDER BY {AUTHORITY_ORDER}, valid_from DESC, id DESC"
        )
        return [to_fact(row) for row in self._rows(sql, game, subject, attribute)]

    def _insert(self, new: NewFact, tentative: bool) -> Fact:
        cursor = self._conn.execute(
            "INSERT INTO facts (game, session_id, subject, attribute, value, source, confidence,"
            " tentative, valid_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*new, tentative, self._clock()),
        )
        return self._fact(int(cursor.lastrowid or 0))

    def _close(self, fact_ids: Iterable[int]) -> list[Fact]:
        ids = list(dict.fromkeys(fact_ids))
        if not ids:
            return []
        now = self._clock()
        self._conn.executemany(
            "UPDATE facts SET valid_to = ? WHERE id = ? AND valid_to IS NULL",
            [(now, fact_id) for fact_id in ids],
        )
        return self._facts_by_id(ids)

    def _open_question(
        self, new: NewFact, text: str, options: list[str], fact_ids: list[int]
    ) -> Question:
        now = self._clock()
        cursor = self._conn.execute(
            "INSERT INTO questions (game, session_id, text, options, fact_ids, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (new.game, new.session_id, text, json.dumps(options), json.dumps(fact_ids), now),
        )
        return self._question(int(cursor.lastrowid or 0))

    def _drop(self, question_id: int) -> bool:
        cursor = self._conn.execute(
            "UPDATE questions SET status = 'dropped' WHERE id = ? AND status = 'open'",
            (question_id,),
        )
        return cursor.rowcount > 0

    def _drop_settled(self, closed: list[Fact]) -> None:
        """Drops open questions whose facts all just closed, so nothing settled is asked or listed.

        A dropped question can still be answered, so this can't take an answer away mid-reply.
        """
        ids = {fact.id for fact in closed}
        if not ids:
            return
        for question in self._open_questions(closed[0].game):
            if not ids & set(question.fact_ids):
                continue
            if all(fact.valid_to is not None for fact in self._facts_by_id(question.fact_ids)):
                self._drop(question.id)

    def _settle_unknowns(self, fact: Fact) -> None:
        """A sure fact settles any open question about its key, so it's never asked or listed.

        Only the player can answer one. The screen settling it just means nobody has to.
        """
        if fact.tentative or fact.source == "wiki":
            return
        where = "status = 'open' AND game IS ? AND subject = ? AND attribute = ?"
        key = (fact.game, fact.subject, fact.attribute)
        if not self._rows(f"SELECT 1 FROM questions WHERE {where} LIMIT 1", *key):
            return
        if fact.source == "player":
            self._conn.execute(
                "UPDATE questions SET status = 'answered', answer = ?, answered_at = ?"
                f" WHERE {where}",
                (fact.value, self._clock(), *key),
            )
        else:
            self._conn.execute(f"UPDATE questions SET status = 'dropped' WHERE {where}", key)
